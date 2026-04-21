"""JWT-refresh retry must not duplicate an already-filled order (F02)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from xtb_api.client import XTBClient
from xtb_api.types.trading import Position, TradeOutcome


def _make_client(monkeypatch: pytest.MonkeyPatch) -> XTBClient:
    c = XTBClient(email="x@y.z", password="p", account_number=1, session_file=None)
    c._auth = MagicMock()
    c._ws = MagicMock()
    c._ws.get_orders = AsyncMock(return_value=[])
    fake_grpc = MagicMock()
    fake_grpc.execute_order = AsyncMock()
    fake_grpc.invalidate_jwt = MagicMock()
    monkeypatch.setattr(c, "_ensure_grpc", lambda: fake_grpc)
    monkeypatch.setattr(c, "_resolve_instrument_id", AsyncMock(return_value=42))
    monkeypatch.setattr("xtb_api.client.asyncio.sleep", AsyncMock(return_value=None))
    c._fake_grpc = fake_grpc  # type: ignore[attr-defined]
    return c


def _pos(symbol: str, volume: float, side: str, order_id: str, price: float = 1.0) -> Position:
    return Position(
        symbol=symbol,
        volume=volume,
        side=side,  # type: ignore[arg-type]
        order_id=order_id,
        open_price=price,
        current_price=price,
    )


@pytest.mark.asyncio
async def test_rbac_retry_detects_already_filled_position(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the first call returns RBAC but a matching position already exists,
    return FILLED with that order_id — do not resubmit."""
    client = _make_client(monkeypatch)

    rbac_result = MagicMock(
        success=False,
        order_id=None,
        error="gRPC RBAC: access denied",
        grpc_status=7,
    )
    client._fake_grpc.execute_order = AsyncMock(return_value=rbac_result)  # type: ignore[attr-defined]

    # A position with matching symbol/side/volume is already live.
    already_filled = _pos("CIG.PL", 5, "buy", "ALREADY-EXEC", price=23.17)
    client._ws.get_positions = AsyncMock(return_value=[already_filled])

    result = await client.buy("CIG.PL", volume=5)

    assert result.status is TradeOutcome.FILLED
    assert result.order_id == "ALREADY-EXEC"
    # Crucially, execute_order was called ONCE, not twice — no retry.
    assert client._fake_grpc.execute_order.await_count == 1  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_rbac_retry_proceeds_when_no_matching_position(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No matching position → invalidate JWT and retry."""
    client = _make_client(monkeypatch)

    rbac_result = MagicMock(
        success=False,
        order_id=None,
        error="gRPC RBAC: access denied",
        grpc_status=7,
    )
    retry_result = MagicMock(success=True, order_id="NEW-OK", error=None, grpc_status=0)
    client._fake_grpc.execute_order = AsyncMock(  # type: ignore[attr-defined]
        side_effect=[rbac_result, retry_result]
    )
    # Idempotency probe: no existing position. After retry succeeds, position appears.
    new_pos = _pos("CIG.PL", 5, "buy", "NEW-OK")
    client._ws.get_positions = AsyncMock(side_effect=[[], [new_pos], [new_pos]])

    result = await client.buy("CIG.PL", volume=5)

    assert result.status is TradeOutcome.FILLED
    assert result.order_id == "NEW-OK"
    assert client._fake_grpc.execute_order.await_count == 2  # type: ignore[attr-defined]
    client._fake_grpc.invalidate_jwt.assert_called_once()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_rbac_retry_position_wrong_side_does_not_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A position with the right symbol but wrong side must not short-circuit."""
    client = _make_client(monkeypatch)

    rbac_result = MagicMock(
        success=False,
        order_id=None,
        error="RBAC",
        grpc_status=7,
    )
    retry_result = MagicMock(success=True, order_id="NEW", error=None, grpc_status=0)
    client._fake_grpc.execute_order = AsyncMock(  # type: ignore[attr-defined]
        side_effect=[rbac_result, retry_result]
    )

    # Idempotency probe sees only the wrong-side position → no match → retry proceeds.
    # After retry, classification probe sees the new buy position too.
    other_side = _pos("CIG.PL", 5, "sell", "OTHER")
    new_buy = _pos("CIG.PL", 5, "buy", "NEW")
    client._ws.get_positions = AsyncMock(
        side_effect=[[other_side], [other_side, new_buy], [other_side, new_buy]]
    )

    result = await client.buy("CIG.PL", volume=5)

    assert result.status is TradeOutcome.FILLED
    assert result.order_id == "NEW"
    assert client._fake_grpc.execute_order.await_count == 2  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_non_rbac_rejection_does_not_probe_positions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A plain rejection (e.g. NO_FUNDS) must not trigger the idempotency probe."""
    client = _make_client(monkeypatch)

    reject_result = MagicMock(
        success=False,
        order_id=None,
        error="NO_FUNDS",
        grpc_status=9,
    )
    client._fake_grpc.execute_order = AsyncMock(return_value=reject_result)  # type: ignore[attr-defined]
    client._ws.get_positions = AsyncMock(return_value=[])

    result = await client.buy("CIG.PL", volume=5)

    assert result.status is TradeOutcome.REJECTED
    # Positions not polled on a non-RBAC rejection.
    client._ws.get_positions.assert_not_awaited()
    assert client._fake_grpc.execute_order.await_count == 1  # type: ignore[attr-defined]
