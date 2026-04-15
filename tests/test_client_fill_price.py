"""XTBClient.buy/sell populate TradeResult.price from a post-trade position poll."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from xtb_api.client import XTBClient
from xtb_api.types.trading import Position


def _make_client(monkeypatch: pytest.MonkeyPatch) -> XTBClient:
    c = XTBClient(email="x@y.z", password="p", account_number=1, session_file=None)
    c._auth = MagicMock()
    c._ws = MagicMock()
    fake_grpc = MagicMock()
    fake_grpc.execute_order = AsyncMock()
    monkeypatch.setattr(c, "_ensure_grpc", lambda: fake_grpc)
    monkeypatch.setattr(c, "_resolve_instrument_id", AsyncMock(return_value=42))
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

    result = await client.buy("CIG.PL", volume=5)

    assert result.success is True
    assert result.price == 23.17


@pytest.mark.asyncio
async def test_fill_price_retries_three_times(monkeypatch: pytest.MonkeyPatch) -> None:
    """If positions is empty on first poll, retry up to 3 times."""
    client = _make_client(monkeypatch)
    client._fake_grpc.execute_order = AsyncMock(  # type: ignore[attr-defined]
        return_value=MagicMock(success=True, order_id="O1", error=None)
    )
    # First two polls: empty. Third poll: position shows up.
    client._ws.get_positions = AsyncMock(side_effect=[[], [], [_pos("CIG.PL", 99.0)]])
    # Zero sleep so the test isn't slow.
    monkeypatch.setattr("asyncio.sleep", AsyncMock())

    result = await client.buy("CIG.PL", volume=1)

    assert result.price == 99.0
    assert client._ws.get_positions.await_count == 3


@pytest.mark.asyncio
async def test_fill_price_none_when_position_never_appears(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client(monkeypatch)
    client._fake_grpc.execute_order = AsyncMock(  # type: ignore[attr-defined]
        return_value=MagicMock(success=True, order_id="O1", error=None)
    )
    client._ws.get_positions = AsyncMock(return_value=[])  # always empty
    monkeypatch.setattr("asyncio.sleep", AsyncMock())

    result = await client.buy("CIG.PL", volume=1)

    assert result.success is True  # trade still succeeded
    assert result.price is None  # but we couldn't determine fill price


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
