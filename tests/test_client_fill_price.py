"""XTBClient.buy/sell populate TradeResult.price from a post-trade position poll."""

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
    monkeypatch.setattr(c, "_ensure_grpc", lambda: fake_grpc)
    monkeypatch.setattr(c, "_resolve_instrument_id", AsyncMock(return_value=42))
    monkeypatch.setattr("xtb_api.client.asyncio.sleep", AsyncMock(return_value=None))
    c._fake_grpc = fake_grpc  # type: ignore[attr-defined]
    return c


def _pos(symbol: str, price: float) -> Position:
    return Position(
        symbol=symbol,
        volume=1,
        open_price=price,
        current_price=price,
        side="buy",
        order_id="O1",
    )


@pytest.mark.asyncio
async def test_buy_populates_fill_price_from_positions(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client(monkeypatch)
    client._fake_grpc.execute_order = AsyncMock(  # type: ignore[attr-defined]
        return_value=MagicMock(success=True, order_id="O1", error=None)
    )
    client._ws.get_positions = AsyncMock(return_value=[_pos("CIG.PL", 23.17)])

    result = await client.buy("CIG.PL", volume=1)

    assert result.success is True
    assert result.price == 23.17


@pytest.mark.asyncio
async def test_fill_price_retries_three_times(monkeypatch: pytest.MonkeyPatch) -> None:
    """_poll_fill_price retries up to 3 times after classification finds the position."""
    client = _make_client(monkeypatch)
    client._fake_grpc.execute_order = AsyncMock(  # type: ignore[attr-defined]
        return_value=MagicMock(success=True, order_id="O1", error=None)
    )
    # Classification probe (call 1) finds the position immediately, triggering FILLED path.
    # _poll_fill_price then retries: calls 2 and 3 return empty, call 4 returns the price.
    client._ws.get_positions = AsyncMock(side_effect=[[_pos("CIG.PL", 0.0)], [], [], [_pos("CIG.PL", 99.0)]])

    result = await client.buy("CIG.PL", volume=1)

    assert result.price == 99.0
    assert client._ws.get_positions.await_count == 4


@pytest.mark.asyncio
async def test_fill_price_none_when_position_never_appears(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without an order_number we have no server-side receipt, so empty
    probes stay AMBIGUOUS (not FILLED)."""
    client = _make_client(monkeypatch)
    client._fake_grpc.execute_order = AsyncMock(  # type: ignore[attr-defined]
        return_value=MagicMock(success=True, order_id="O1", order_number=None, error=None)
    )
    client._ws.get_positions = AsyncMock(return_value=[])  # always empty

    result = await client.buy("CIG.PL", volume=1)

    assert result.status is TradeOutcome.AMBIGUOUS
    assert result.error_code == "FILL_STATE_UNKNOWN"
    assert result.price is None


@pytest.mark.asyncio
async def test_failed_trade_does_not_poll_positions(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client(monkeypatch)
    client._fake_grpc.execute_order = AsyncMock(  # type: ignore[attr-defined]
        return_value=MagicMock(success=False, order_id=None, error="NO_FUNDS")
    )
    client._ws.get_positions = AsyncMock(return_value=[])

    result = await client.buy("CIG.PL", volume=1)

    assert result.success is False
    client._ws.get_positions.assert_not_awaited()


@pytest.mark.asyncio
async def test_fill_price_unknown_sets_error_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without an order_number, empty probes stay AMBIGUOUS with error code."""
    client = _make_client(monkeypatch)
    client._fake_grpc.execute_order = AsyncMock(  # type: ignore[attr-defined]
        return_value=MagicMock(success=True, order_id="O1", order_number=None, error=None, grpc_status=0)
    )
    client._ws.get_positions = AsyncMock(return_value=[])  # never appears

    result = await client.buy("CIG.PL", volume=1)

    assert result.status is TradeOutcome.AMBIGUOUS
    assert result.price is None
    assert result.error_code == "FILL_STATE_UNKNOWN"


@pytest.mark.asyncio
async def test_fill_price_known_no_error_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy path: error_code is None when fill price was observed."""
    client = _make_client(monkeypatch)
    client._fake_grpc.execute_order = AsyncMock(  # type: ignore[attr-defined]
        return_value=MagicMock(success=True, order_id="O1", error=None, grpc_status=0)
    )
    client._ws.get_positions = AsyncMock(return_value=[_pos("CIG.PL", 42.5)])

    result = await client.buy("CIG.PL", volume=1)

    assert result.status is TradeOutcome.FILLED
    assert result.price == 42.5
    assert result.error_code is None


@pytest.mark.asyncio
async def test_fill_price_poll_exception_does_not_mask_fill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An exception in get_positions must not crash the client; outcome is AMBIGUOUS."""
    client = _make_client(monkeypatch)
    client._fake_grpc.execute_order = AsyncMock(  # type: ignore[attr-defined]
        return_value=MagicMock(success=True, order_id="O1", error=None, grpc_status=0)
    )
    client._ws.get_positions = AsyncMock(side_effect=RuntimeError("network blip"))

    result = await client.buy("CIG.PL", volume=1)

    assert result.order_id == "O1"
    # get_positions raised on both probe attempts — no fill confirmed → AMBIGUOUS
    assert result.status is TradeOutcome.AMBIGUOUS
    assert result.error_code == "FILL_STATE_UNKNOWN"
