"""Regression tests for get_balance vs the TOTAL_BALANCE snapshot race.

XTB acks the getAndSubscribeElement call immediately with an empty
element list; the populated ``xtotalbalance`` snapshot lands later. The
naive single-shot implementation returned zeros until the snapshot
happened to be cached server-side. These tests pin the retry contract.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from xtb_api.types.websocket import WSClientConfig, WSResponse, XLoginAccountInfo, XLoginResult
from xtb_api.ws import ws_client as _wsc
from xtb_api.ws.ws_client import XTBWebSocketClient


def _make_authenticated_client(monkeypatch: pytest.MonkeyPatch) -> XTBWebSocketClient:
    cfg = WSClientConfig(url="wss://t.example/x", account_number=42, endpoint="meta1", auto_reconnect=False)
    c = XTBWebSocketClient(cfg, auth_manager=None)
    c._authenticated = True
    c._login_result = XLoginResult(accountList=[XLoginAccountInfo(accountNo=42, currency="PLN", endpointType="DEMO")])
    monkeypatch.setattr(_wsc, "_BALANCE_SNAPSHOT_POLL_MS", 10)
    monkeypatch.setattr(_wsc, "_BALANCE_SNAPSHOT_MAX_WAIT_MS", 200)
    return c


def _empty_response() -> WSResponse:
    return WSResponse(reqId="r1", response=[], data=None, error=None, status=0, events=None, completed=True)


def _populated_response(balance: float) -> WSResponse:
    return WSResponse(
        reqId="r1",
        response=[
            {
                "element": {
                    "elements": [
                        {
                            "state": 1,
                            "value": {
                                "xtotalbalance": {
                                    "balance": balance,
                                    "equity": balance,
                                    "freeMargin": balance,
                                }
                            },
                        }
                    ]
                }
            }
        ],
        data=None,
        error=None,
        status=0,
        events=None,
        completed=True,
    )


@pytest.mark.asyncio
async def test_get_balance_polls_until_snapshot_populated(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_authenticated_client(monkeypatch)
    client.send = AsyncMock(side_effect=[_empty_response(), _empty_response(), _populated_response(442.64)])

    result = await client.get_balance()

    assert result.balance == 442.64
    assert result.equity == 442.64
    assert result.free_margin == 442.64
    assert client.send.await_count == 3


@pytest.mark.asyncio
async def test_get_balance_returns_fast_when_first_response_populated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _make_authenticated_client(monkeypatch)
    client.send = AsyncMock(return_value=_populated_response(1000.0))

    result = await client.get_balance()

    assert result.balance == 1000.0
    assert client.send.await_count == 1


@pytest.mark.asyncio
async def test_get_balance_falls_back_to_zeros_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_authenticated_client(monkeypatch)
    client.send = AsyncMock(return_value=_empty_response())

    result = await client.get_balance()

    assert result.balance == 0.0
    assert result.currency == "PLN"
    assert client.send.await_count >= 2
