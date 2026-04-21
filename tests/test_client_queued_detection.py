"""Detection flow: classify gRPC-successful orders as FILLED / QUEUED / AMBIGUOUS.

The gRPC NewMarketOrder response is byte-identical for filled vs queued orders;
XTBClient._build_trade_result uses get_positions() / get_orders() as the
tie-breaker. See spec §2 for the full probe sequence.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from xtb_api.client import XTBClient
from xtb_api.types.trading import PendingOrder, Position, TradeOutcome


def _make_client(monkeypatch: pytest.MonkeyPatch) -> XTBClient:
    c = XTBClient(email="x@y.z", password="p", account_number=1, session_file=None)
    c._auth = MagicMock()
    c._ws = MagicMock()
    c._ws.get_positions = AsyncMock(return_value=[])
    c._ws.get_orders = AsyncMock(return_value=[])
    fake_grpc = MagicMock()
    fake_grpc.execute_order = AsyncMock()
    fake_grpc.invalidate_jwt = MagicMock()
    monkeypatch.setattr(c, "_ensure_grpc", lambda: fake_grpc)
    monkeypatch.setattr(c, "_resolve_instrument_id", AsyncMock(return_value=42))
    # Disable the 500 ms sleep in tests — nothing depends on real time.
    monkeypatch.setattr("xtb_api.client.asyncio.sleep", AsyncMock(return_value=None))
    c._fake_grpc = fake_grpc  # type: ignore[attr-defined]
    return c


@pytest.mark.asyncio
async def test_filled_order_matched_by_position(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _make_client(monkeypatch)
    client._fake_grpc.execute_order = AsyncMock(  # type: ignore[attr-defined]
        return_value=MagicMock(
            success=True,
            order_id="UUID-1",
            order_number=872069505,
            error=None,
            grpc_status=0,
        )
    )
    pos = Position(
        symbol="CIG.PL",
        volume=1,
        open_price=10.0,
        current_price=10.0,
        side="buy",
        order_id="UUID-1",
    )
    client._ws.get_positions = AsyncMock(return_value=[pos])

    result = await client.buy("CIG.PL", volume=1)

    assert result.status is TradeOutcome.FILLED
    assert result.order_id == "UUID-1"
    assert result.order_number == 872069505
    # get_orders should not even be consulted on the filled path
    client._ws.get_orders.assert_not_awaited()


@pytest.mark.asyncio
async def test_queued_order_matched_by_pending_orders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _make_client(monkeypatch)
    client._fake_grpc.execute_order = AsyncMock(  # type: ignore[attr-defined]
        return_value=MagicMock(
            success=True,
            order_id="UUID-2",
            order_number=872077045,
            error=None,
            grpc_status=0,
        )
    )
    client._ws.get_positions = AsyncMock(return_value=[])
    pending = PendingOrder(
        symbol="AAPL.US",
        volume=1,
        price=0.0,
        side="buy",
        order_id="872077045",
    )
    client._ws.get_orders = AsyncMock(return_value=[pending])

    result = await client.buy("AAPL.US", volume=1)

    assert result.status is TradeOutcome.QUEUED
    assert result.order_number == 872077045
    assert result.order_id == "UUID-2"
    assert result.error_code is None


@pytest.mark.asyncio
async def test_neither_position_nor_order_falls_back_to_queued(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Probes ran cleanly but found nothing → QUEUED.

    ``getAllOrders`` does not surface queued market-closed orders in
    practice, so a gRPC success plus an ``order_number`` plus clean-but-
    empty probes is XTB's own receipt that the order is queued."""
    client = _make_client(monkeypatch)
    client._fake_grpc.execute_order = AsyncMock(  # type: ignore[attr-defined]
        return_value=MagicMock(
            success=True,
            order_id="UUID-3",
            order_number=999,
            error=None,
            grpc_status=0,
        )
    )
    client._ws.get_positions = AsyncMock(return_value=[])
    client._ws.get_orders = AsyncMock(return_value=[])

    result = await client.buy("AAPL.US", volume=1)

    assert result.status is TradeOutcome.QUEUED
    assert result.order_number == 999
    assert result.order_id == "UUID-3"
    assert result.error_code is None
    assert result.error is None
    # The probe must still retry once before committing to the QUEUED fallback.
    assert client._ws.get_positions.await_count == 2
    assert client._ws.get_orders.await_count == 2


@pytest.mark.asyncio
async def test_queued_fallback_requires_order_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without an ``order_number`` we have no server-side receipt to trust,
    so clean-but-empty probes stay AMBIGUOUS."""
    client = _make_client(monkeypatch)
    client._fake_grpc.execute_order = AsyncMock(  # type: ignore[attr-defined]
        return_value=MagicMock(
            success=True,
            order_id="UUID-NO-NUM",
            order_number=None,
            error=None,
            grpc_status=0,
        )
    )
    client._ws.get_positions = AsyncMock(return_value=[])
    client._ws.get_orders = AsyncMock(return_value=[])

    result = await client.buy("AAPL.US", volume=1)

    assert result.status is TradeOutcome.AMBIGUOUS
    assert result.error_code == "FILL_STATE_UNKNOWN"


@pytest.mark.asyncio
async def test_get_positions_failure_falls_through_to_orders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _make_client(monkeypatch)
    client._fake_grpc.execute_order = AsyncMock(  # type: ignore[attr-defined]
        return_value=MagicMock(
            success=True,
            order_id="UUID-4",
            order_number=111,
            error=None,
            grpc_status=0,
        )
    )
    client._ws.get_positions = AsyncMock(side_effect=RuntimeError("ws bounced"))
    pending = PendingOrder(
        symbol="AAPL.US",
        volume=1,
        price=0.0,
        side="buy",
        order_id="111",
    )
    client._ws.get_orders = AsyncMock(return_value=[pending])

    result = await client.buy("AAPL.US", volume=1)

    assert result.status is TradeOutcome.QUEUED
    assert result.order_number == 111


@pytest.mark.asyncio
async def test_order_id_disambiguates_against_preexisting_identical_position(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When positions carry order_ids, a pre-existing identical position
    must not be claimed as the fill. The classifier uses the grpc-returned
    order_id to pick the right one."""
    client = _make_client(monkeypatch)
    client._fake_grpc.execute_order = AsyncMock(  # type: ignore[attr-defined]
        return_value=MagicMock(
            success=True,
            order_id="UUID-NEW",
            order_number=555,
            error=None,
            grpc_status=0,
        )
    )
    preexisting = Position(
        symbol="CIG.PL",
        volume=1,
        open_price=9.0,
        current_price=9.0,
        side="buy",
        order_id="UUID-OLD",
    )
    new_pos = Position(
        symbol="CIG.PL",
        volume=1,
        open_price=10.0,
        current_price=10.0,
        side="buy",
        order_id="UUID-NEW",
    )
    client._ws.get_positions = AsyncMock(return_value=[preexisting, new_pos])

    result = await client.buy("CIG.PL", volume=1)

    assert result.status is TradeOutcome.FILLED
    assert result.order_id == "UUID-NEW"
    assert result.price == 10.0


@pytest.mark.asyncio
async def test_order_id_mismatch_does_not_fall_back_when_ids_populated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the WS snapshot has order_ids but ours isn't among them, the
    classifier must NOT fall back to symbol+side+volume matching against
    a pre-existing identical position. With a valid order_number and
    clean-but-unmatching probes, the result is QUEUED (XTB's receipt)."""
    client = _make_client(monkeypatch)
    client._fake_grpc.execute_order = AsyncMock(  # type: ignore[attr-defined]
        return_value=MagicMock(
            success=True,
            order_id="UUID-NEW",
            order_number=555,
            error=None,
            grpc_status=0,
        )
    )
    preexisting = Position(
        symbol="CIG.PL",
        volume=1,
        open_price=9.0,
        current_price=9.0,
        side="buy",
        order_id="UUID-OLD",
    )
    client._ws.get_positions = AsyncMock(return_value=[preexisting])
    client._ws.get_orders = AsyncMock(return_value=[])

    result = await client.buy("CIG.PL", volume=1)

    assert result.status is TradeOutcome.QUEUED
    assert result.order_id == "UUID-NEW"
    assert result.order_number == 555
    # Both attempts must have consulted get_orders too — the classifier
    # didn't silently fall back to heuristic position matching.
    assert client._ws.get_positions.await_count == 2
    assert client._ws.get_orders.await_count == 2


@pytest.mark.asyncio
async def test_falls_back_to_volume_match_when_no_order_ids_populated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When no position in the snapshot carries an order_id (e.g. WS
    hasn't populated ids yet), the classifier must fall back to the
    legacy (symbol, side, volume) match rather than returning AMBIGUOUS."""
    client = _make_client(monkeypatch)
    client._fake_grpc.execute_order = AsyncMock(  # type: ignore[attr-defined]
        return_value=MagicMock(
            success=True,
            order_id="UUID-NEW",
            order_number=555,
            error=None,
            grpc_status=0,
        )
    )
    pos = Position(
        symbol="CIG.PL",
        volume=1,
        open_price=10.0,
        current_price=10.0,
        side="buy",
        order_id=None,
    )
    client._ws.get_positions = AsyncMock(return_value=[pos])

    result = await client.buy("CIG.PL", volume=1)

    assert result.status is TradeOutcome.FILLED
    assert result.price == 10.0


@pytest.mark.asyncio
async def test_queued_detection_matches_int_shaped_order_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PendingOrder.order_id with an int-parseable but non-identical
    string (e.g. leading zero) must still be recognized via int fallback."""
    client = _make_client(monkeypatch)
    client._fake_grpc.execute_order = AsyncMock(  # type: ignore[attr-defined]
        return_value=MagicMock(
            success=True,
            order_id="UUID-Z",
            order_number=872077045,
            error=None,
            grpc_status=0,
        )
    )
    client._ws.get_positions = AsyncMock(return_value=[])
    pending = PendingOrder(
        symbol="AAPL.US",
        volume=1,
        price=0.0,
        side="buy",
        order_id="0872077045",
    )
    client._ws.get_orders = AsyncMock(return_value=[pending])

    result = await client.buy("AAPL.US", volume=1)

    assert result.status is TradeOutcome.QUEUED
    assert result.order_number == 872077045


@pytest.mark.asyncio
async def test_both_probes_raising_gives_ambiguous_with_underlying_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _make_client(monkeypatch)
    client._fake_grpc.execute_order = AsyncMock(  # type: ignore[attr-defined]
        return_value=MagicMock(
            success=True,
            order_id="UUID-5",
            order_number=222,
            error=None,
            grpc_status=0,
        )
    )
    client._ws.get_positions = AsyncMock(side_effect=RuntimeError("pos bounced"))
    client._ws.get_orders = AsyncMock(side_effect=RuntimeError("orders bounced"))

    result = await client.buy("AAPL.US", volume=1)

    assert result.status is TradeOutcome.AMBIGUOUS
    assert result.error_code == "FILL_STATE_UNKNOWN"
    assert result.error is not None and ("pos bounced" in result.error or "orders bounced" in result.error)
