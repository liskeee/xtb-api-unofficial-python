"""`get_positions()` consumes the POSITIONS subscription's push channel.

XTB's xStation5 CoreAPI doesn't echo a `reqId`-correlated response for
`getPositions`; position data arrives via `status=1` push events with
`eid=POSITIONS`. These tests verify the push-collecting implementation.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from xtb_api.types.enums import SocketStatus
from xtb_api.types.websocket import WSClientConfig
from xtb_api.ws.parsers import parse_position_trade
from xtb_api.ws.ws_client import XTBWebSocketClient


def _mock_ws_send() -> AsyncMock:
    return AsyncMock(return_value=None)


def _trade(position_id: str, symbol: str = "CIG.PL", side: int = 0) -> dict:
    return {
        "positionId": position_id,
        "symbol": symbol,
        "side": side,
        "volume": 10,
        "openPrice": 23.17,
        "sl": 22.0,
        "tp": 25.0,
        "swap": 0.0,
        "commission": 0.1,
        "margin": 50.0,
        "openTime": 1700000000,
        "idQuote": 123,
    }


def _make_client() -> XTBWebSocketClient:
    config = WSClientConfig(
        url="wss://api5demoa.x-station.eu/v1/xstation",
        account_number=12345678,
    )
    client = XTBWebSocketClient(config)
    # Bypass real connect: set status to CONNECTED (what is_connected reads)
    # and stub the underlying socket.
    client._status = SocketStatus.CONNECTED
    client._ws = MagicMock()
    client._ws.send = _mock_ws_send()
    return client


# ── parse_position_trade (extracted helper) ────────────────────────

def test_parse_position_trade_extracts_expected_fields() -> None:
    pos = parse_position_trade(_trade("P1"))
    assert pos.symbol == "CIG.PL"
    assert pos.order_id == "P1"
    assert pos.volume == 10
    assert pos.open_price == 23.17
    assert pos.side == "buy"
    assert pos.stop_loss == 22.0
    assert pos.take_profit == 25.0


def test_parse_position_trade_side_sell() -> None:
    pos = parse_position_trade(_trade("P1", side=1))
    assert pos.side == "sell"


def test_parse_position_trade_zero_sl_tp_become_none() -> None:
    trade = _trade("P1")
    trade["sl"] = 0
    trade["tp"] = 0
    pos = parse_position_trade(trade)
    assert pos.stop_loss is None
    assert pos.take_profit is None


# ── get_positions push-collection ──────────────────────────────────

@pytest.mark.asyncio
async def test_get_positions_collects_first_burst(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client()

    async def fire_pushes_after_subscribe() -> None:
        # Give the coroutine a moment to register its 'position' listener.
        await asyncio.sleep(0.05)
        client._emit("position", _trade("P1", "CIG.PL"))
        client._emit("position", _trade("P2", "AAPL.US"))

    # Run the push firing concurrently with get_positions.
    pushes_task = asyncio.create_task(fire_pushes_after_subscribe())
    positions = await client.get_positions(max_wait_ms=2000, quiet_ms=300)
    await pushes_task

    assert len(positions) == 2
    assert {p.order_id for p in positions} == {"P1", "P2"}
    client._ws.send.assert_awaited()  # subscription was fired


@pytest.mark.asyncio
async def test_get_positions_dedups_by_position_id() -> None:
    client = _make_client()

    async def fire_duplicates() -> None:
        await asyncio.sleep(0.05)
        client._emit("position", _trade("P1", "CIG.PL"))
        client._emit("position", _trade("P1", "CIG.PL"))  # duplicate update
        client._emit("position", _trade("P2", "LPP.PL"))

    task = asyncio.create_task(fire_duplicates())
    positions = await client.get_positions(max_wait_ms=2000, quiet_ms=300)
    await task

    assert len(positions) == 2
    assert {p.order_id for p in positions} == {"P1", "P2"}


@pytest.mark.asyncio
async def test_get_positions_returns_empty_on_no_pushes() -> None:
    client = _make_client()
    # No pushes fired — must return quickly after max_wait.
    positions = await client.get_positions(max_wait_ms=300, quiet_ms=50)
    assert positions == []


@pytest.mark.asyncio
async def test_get_positions_removes_listener_on_exit() -> None:
    client = _make_client()
    # Record initial listener count on the 'position' event (may be non-zero
    # from other hooks registered in the live client).
    before = len(client._event_handlers.get("position", []))
    await client.get_positions(max_wait_ms=200, quiet_ms=50)
    after = len(client._event_handlers.get("position", []))
    assert before == after, "Handler leaked after get_positions exits"


@pytest.mark.asyncio
async def test_get_positions_raises_when_not_connected() -> None:
    config = WSClientConfig(
        url="wss://api5demoa.x-station.eu/v1/xstation",
        account_number=12345678,
    )
    client = XTBWebSocketClient(config)
    # Default state: not connected.
    from xtb_api.exceptions import XTBConnectionError
    with pytest.raises(XTBConnectionError):
        await client.get_positions(max_wait_ms=100)
