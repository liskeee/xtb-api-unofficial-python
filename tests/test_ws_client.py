"""Tests for WebSocket client."""

import json
from unittest.mock import MagicMock

import pytest

from xtb_api.exceptions import AuthenticationError, XTBConnectionError
from xtb_api.types.enums import SocketStatus, SubscriptionEid
from xtb_api.types.websocket import (
    WSAuthOptions,
    WSClientConfig,
    WSCredentials,
    WSResponse,
    XLoginAccountInfo,
    XLoginResult,
)
from xtb_api.ws.ws_client import XTBWebSocketClient


class TestWSClientInit:
    """Tests for WebSocket client initialization."""

    def test_default_config(self):
        config = WSClientConfig(
            url="wss://api5demoa.x-station.eu/v1/xstation",
            account_number=12345678,
        )
        client = XTBWebSocketClient(config)
        assert client.connection_status == SocketStatus.CLOSED
        assert not client.is_connected
        assert not client.is_authenticated
        assert client.account_info is None

    def test_account_id(self):
        config = WSClientConfig(
            url="wss://api5demoa.x-station.eu/v1/xstation",
            account_number=12345678,
            endpoint="meta1",
        )
        client = XTBWebSocketClient(config)
        assert client.account_id == "meta1_12345678"

    def test_custom_endpoint(self):
        config = WSClientConfig(
            url="wss://api5demoa.x-station.eu/v1/xstation",
            account_number=87654321,
            endpoint="meta2",
        )
        client = XTBWebSocketClient(config)
        assert client.account_id == "meta2_87654321"

    def test_cas_client_initialized_with_credentials(self):
        config = WSClientConfig(
            url="wss://api5demoa.x-station.eu/v1/xstation",
            account_number=12345678,
            auth=WSAuthOptions(
                credentials=WSCredentials(email="test@test.com", password="pass")
            ),
        )
        client = XTBWebSocketClient(config)
        assert client._cas_client is not None

    def test_no_cas_client_without_credentials(self):
        config = WSClientConfig(
            url="wss://api5demoa.x-station.eu/v1/xstation",
            account_number=12345678,
        )
        client = XTBWebSocketClient(config)
        assert client._cas_client is None


class TestWSClientEvents:
    """Tests for WebSocket client event system."""

    def test_on_and_emit(self):
        config = WSClientConfig(
            url="wss://test.example.com/ws",
            account_number=1234,
        )
        client = XTBWebSocketClient(config)

        received = []
        client.on("test_event", lambda data: received.append(data))
        client._emit("test_event", "hello")

        assert received == ["hello"]

    def test_multiple_handlers(self):
        config = WSClientConfig(
            url="wss://test.example.com/ws",
            account_number=1234,
        )
        client = XTBWebSocketClient(config)

        results1 = []
        results2 = []
        client.on("event", lambda d: results1.append(d))
        client.on("event", lambda d: results2.append(d))

        client._emit("event", 42)
        assert results1 == [42]
        assert results2 == [42]

    def test_off_removes_handler(self):
        config = WSClientConfig(
            url="wss://test.example.com/ws",
            account_number=1234,
        )
        client = XTBWebSocketClient(config)

        results = []

        def handler(d):
            results.append(d)

        client.on("event", handler)
        client.off("event", handler)

        client._emit("event", "data")
        assert results == []

    def test_status_update_on_status_change(self):
        config = WSClientConfig(
            url="wss://test.example.com/ws",
            account_number=1234,
        )
        client = XTBWebSocketClient(config)

        statuses = []
        client.on("status_update", lambda s: statuses.append(s))
        client._update_status(SocketStatus.CONNECTING)
        client._update_status(SocketStatus.CONNECTED)

        assert statuses == [SocketStatus.CONNECTING, SocketStatus.CONNECTED]


class TestWSClientMessageHandling:
    """Tests for WebSocket message handling."""

    def test_handle_push_tick(self):
        config = WSClientConfig(
            url="wss://test.example.com/ws",
            account_number=1234,
        )
        client = XTBWebSocketClient(config)

        ticks = []
        client.on("tick", lambda t: ticks.append(t))

        msg = json.dumps({
            "reqId": "",
            "status": 1,
            "events": [
                {
                    "eid": SubscriptionEid.TICKS,
                    "row": {
                        "key": "9_CIG.PL_6",
                        "value": {
                            "xcfdtick": {
                                "symbol": "CIG.PL",
                                "bid": 2.62,
                                "ask": 2.64,
                                "high": 2.70,
                                "low": 2.55,
                            }
                        },
                    },
                }
            ],
        })

        client._handle_message(msg)
        assert len(ticks) == 1
        assert ticks[0]["symbol"] == "CIG.PL"
        assert ticks[0]["bid"] == 2.62
        assert ticks[0]["ask"] == 2.64

    def test_handle_push_position(self):
        config = WSClientConfig(
            url="wss://test.example.com/ws",
            account_number=1234,
        )
        client = XTBWebSocketClient(config)

        positions = []
        client.on("position", lambda p: positions.append(p))

        msg = json.dumps({
            "reqId": "",
            "status": 1,
            "events": [
                {
                    "eid": SubscriptionEid.POSITIONS,
                    "row": {
                        "key": "pos_1",
                        "value": {
                            "xcfdtrade": {
                                "symbol": "AAPL.US",
                                "side": 1,
                                "openPrice": 150.25,
                                "volume": 100,
                            }
                        },
                    },
                }
            ],
        })

        client._handle_message(msg)
        assert len(positions) == 1
        assert positions[0]["symbol"] == "AAPL.US"
        assert positions[0]["volume"] == 100

    def test_handle_push_symbol(self):
        config = WSClientConfig(
            url="wss://test.example.com/ws",
            account_number=1234,
        )
        client = XTBWebSocketClient(config)

        symbols = []
        client.on("symbol", lambda s: symbols.append(s))

        msg = json.dumps({
            "reqId": "",
            "status": 1,
            "events": [
                {
                    "eid": SubscriptionEid.SYMBOLS,
                    "row": {
                        "key": "9_MSFT.US_6",
                        "value": {
                            "xcfdsymbol": {
                                "name": "MSFT.US",
                                "quoteId": 99999,
                                "description": "Microsoft Corporation",
                            }
                        },
                    },
                }
            ],
        })

        client._handle_message(msg)
        assert len(symbols) == 1
        assert symbols[0]["name"] == "MSFT.US"

    def test_handle_invalid_json(self):
        config = WSClientConfig(
            url="wss://test.example.com/ws",
            account_number=1234,
        )
        client = XTBWebSocketClient(config)

        errors = []
        client.on("error", lambda e: errors.append(e))

        client._handle_message("not valid json {{{")
        assert len(errors) == 1

    def test_handle_generic_message(self):
        config = WSClientConfig(
            url="wss://test.example.com/ws",
            account_number=1234,
        )
        client = XTBWebSocketClient(config)

        messages = []
        client.on("message", lambda m: messages.append(m))

        msg = json.dumps({"reqId": "unknown_123", "response": [{"xpong": {"time": 12345}}]})
        client._handle_message(msg)
        assert len(messages) == 1


class TestWSClientHelpers:
    """Tests for WebSocket client helper methods."""

    def test_next_req_id(self):
        config = WSClientConfig(
            url="wss://test.example.com/ws",
            account_number=1234,
        )
        client = XTBWebSocketClient(config)

        id1 = client._next_req_id("ping")
        id2 = client._next_req_id("ping")
        assert id1 != id2
        assert id1.startswith("ping_")
        assert id2.startswith("ping_")

    def test_extract_elements(self):
        config = WSClientConfig(
            url="wss://test.example.com/ws",
            account_number=1234,
        )
        client = XTBWebSocketClient(config)

        res = WSResponse(
            reqId="test_1",
            response=[
                {
                    "element": {
                        "elements": [
                            {"key": "k1", "value": {"xcfdtick": {"bid": 1.5}}},
                            {"key": "k2", "value": {"xcfdtick": {"bid": 2.5}}},
                        ]
                    }
                }
            ],
        )
        elements = client._extract_elements(res)
        assert len(elements) == 2
        assert elements[0]["value"]["xcfdtick"]["bid"] == 1.5

    def test_extract_elements_empty(self):
        config = WSClientConfig(
            url="wss://test.example.com/ws",
            account_number=1234,
        )
        client = XTBWebSocketClient(config)

        res = WSResponse(reqId="test_2")
        elements = client._extract_elements(res)
        assert elements == []

    def test_get_account_number_from_config(self):
        config = WSClientConfig(
            url="wss://test.example.com/ws",
            account_number=99887766,
        )
        client = XTBWebSocketClient(config)
        assert client.get_account_number() == 99887766

    def test_get_account_number_from_login_result(self):
        config = WSClientConfig(
            url="wss://test.example.com/ws",
            account_number=12345678,
        )
        client = XTBWebSocketClient(config)
        client._login_result = XLoginResult(
            accountList=[
                XLoginAccountInfo(accountNo=12345678, currency="PLN", endpointType="meta1"),
                XLoginAccountInfo(accountNo=87654321, currency="USD", endpointType="meta1"),
            ]
        )
        assert client.get_account_number() == 12345678

    def test_cleanup(self):
        config = WSClientConfig(
            url="wss://test.example.com/ws",
            account_number=1234,
        )
        client = XTBWebSocketClient(config)
        client._authenticated = True
        client._login_result = XLoginResult(accountList=[])
        client._symbols_cache = []

        client._cleanup()

        assert client._ws is None
        assert not client._authenticated
        assert client._login_result is None
        assert client._symbols_cache is None

    @pytest.mark.asyncio
    async def test_connect_already_connected_raises(self):
        config = WSClientConfig(
            url="wss://test.example.com/ws",
            account_number=1234,
        )
        client = XTBWebSocketClient(config)
        client._ws = MagicMock()  # Fake existing connection

        with pytest.raises(XTBConnectionError, match="Already connected"):
            await client.connect()

    @pytest.mark.asyncio
    async def test_send_not_connected_raises(self):
        config = WSClientConfig(
            url="wss://test.example.com/ws",
            account_number=1234,
        )
        client = XTBWebSocketClient(config)

        with pytest.raises(XTBConnectionError, match="Not connected"):
            await client.send("test", {"ping": {}})

    @pytest.mark.asyncio
    async def test_get_balance_not_authenticated_raises(self):
        config = WSClientConfig(
            url="wss://test.example.com/ws",
            account_number=1234,
        )
        client = XTBWebSocketClient(config)

        with pytest.raises(AuthenticationError, match="Must be authenticated"):
            await client.get_balance()
