"""Smoke test: the WebSocket trade path constructs TradeResult with TradeOutcome.

Regression guard — prior to W1 the WS path used the removed ``success=`` kwarg
and raised ``pydantic.ValidationError`` on any trade attempt.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from xtb_api.types.trading import TradeOutcome, TradeResult
from xtb_api.ws.ws_client import XTBWebSocketClient


def _make_ws_client() -> XTBWebSocketClient:
    """Build a minimally-configured WS client for shape testing."""
    cfg = MagicMock()
    cfg.account_number = 1
    cfg.endpoint = "test"
    client = XTBWebSocketClient.__new__(XTBWebSocketClient)
    client._config = cfg
    client.subscribe_request_status = AsyncMock()
    return client


@pytest.mark.asyncio
async def test_ws_buy_instrument_not_found_returns_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _make_ws_client()
    client.search_instrument = AsyncMock(return_value=[])

    result = await client.buy("UNKNOWN", volume=1)

    assert isinstance(result, TradeResult)
    assert result.status is TradeOutcome.REJECTED
    assert result.error_code == "INSTRUMENT_NOT_FOUND"
    assert result.success is False


@pytest.mark.asyncio
async def test_ws_buy_broker_error_returns_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _make_ws_client()
    instr = MagicMock()
    instr.symbol = "CIG.PL"
    instr.instrument_id = 42
    client.search_instrument = AsyncMock(return_value=[instr])
    err_response = MagicMock(error={"message": "NO_FUNDS"}, response=None)
    client.send = AsyncMock(return_value=err_response)

    result = await client.buy("CIG.PL", volume=1)

    assert result.status is TradeOutcome.REJECTED
    assert "NO_FUNDS" in (result.error or "")
    assert result.success is False


@pytest.mark.asyncio
async def test_ws_buy_success_returns_filled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _make_ws_client()
    instr = MagicMock()
    instr.symbol = "CIG.PL"
    instr.instrument_id = 42
    client.search_instrument = AsyncMock(return_value=[instr])
    ok_response = MagicMock(error=None)
    client.send = AsyncMock(return_value=ok_response)
    monkeypatch.setattr(
        client,
        "_extract_response_data",
        lambda _: {"orderId": "abc-123", "price": 12.34},
    )

    result = await client.buy("CIG.PL", volume=5)

    assert result.status is TradeOutcome.FILLED
    assert result.success is True
    assert result.order_id == "abc-123"
    assert result.price == 12.34
