"""Tests for high-level XTB client."""


from xtb_api.client import XTBClient
from xtb_api.types.trading import TradeOptions


class TestXTBClientInit:
    """Tests for XTB client initialization."""

    def test_creates_with_required_args(self):
        client = XTBClient(
            email="test@example.com",
            password="secret",
            account_number=12345678,
        )
        assert client.account_number == 12345678
        assert client.ws is not None
        assert client.grpc_client is None  # Lazy, not yet initialized
        assert client.auth is not None
        assert not client.is_connected
        assert not client.is_authenticated

    def test_creates_with_custom_options(self):
        client = XTBClient(
            email="test@example.com",
            password="secret",
            account_number=87654321,
            ws_url="wss://api5demoa.x-station.eu/v1/xstation",
            endpoint="meta2",
            account_server="XS-demo1",
            auto_reconnect=False,
            totp_secret="ABCDEFGH",
            session_file="/tmp/test_session.json",
        )
        assert client.account_number == 87654321
        assert client.ws is not None

    def test_lazy_grpc_not_initialized(self):
        client = XTBClient(
            email="test@example.com",
            password="secret",
            account_number=12345678,
        )
        assert client.grpc_client is None

    def test_lazy_grpc_created_on_ensure(self):
        client = XTBClient(
            email="test@example.com",
            password="secret",
            account_number=12345678,
        )
        grpc = client._ensure_grpc()
        assert grpc is not None
        assert client.grpc_client is grpc
        # Second call returns same instance
        assert client._ensure_grpc() is grpc


class TestXTBClientEvents:
    """Tests for event proxy."""

    def test_on_and_off(self):
        client = XTBClient(
            email="test@example.com",
            password="secret",
            account_number=12345678,
        )

        received = []

        def handler(data):
            received.append(data)
        client.on("tick", handler)
        client.ws._emit("tick", {"symbol": "EURUSD"})
        assert received == [{"symbol": "EURUSD"}]

        client.off("tick", handler)
        client.ws._emit("tick", {"symbol": "GBPUSD"})
        assert len(received) == 1  # Not called again


class TestXTBClientUtils:
    """Tests for utility functions used by client."""

    def test_top_level_imports(self):
        from xtb_api import (
            SocketStatus,
            SubscriptionEid,
            Xs6Side,
            XTBClient,
        )
        assert XTBClient is not None
        assert Xs6Side.BUY == 0
        assert SocketStatus.CONNECTED == "CONNECTED"
        assert SubscriptionEid.TICKS == 2

    def test_price_from_decimal(self):
        from xtb_api.utils import price_from_decimal

        price = price_from_decimal(2.62, 2)
        assert price.value == 262
        assert price.scale == 2

    def test_price_to_decimal(self):
        from xtb_api.types.trading import IPrice
        from xtb_api.utils import price_to_decimal

        price = IPrice(value=262, scale=2)
        result = price_to_decimal(price)
        assert abs(result - 2.62) < 0.001

    def test_volume_from(self):
        from xtb_api.utils import volume_from

        vol = volume_from(19)
        assert vol.value == 19
        assert vol.scale == 0

    def test_build_account_id(self):
        from xtb_api.utils import build_account_id

        assert build_account_id(12345678) == "meta1_12345678"
        assert build_account_id(12345678, "meta2") == "meta2_12345678"

    def test_parse_symbol_key(self):
        from xtb_api.utils import parse_symbol_key

        result = parse_symbol_key("9_CIG.PL_6")
        assert result is not None
        assert result.asset_class_id == 9
        assert result.symbol_name == "CIG.PL"
        assert result.group_id == 6

    def test_parse_symbol_key_invalid(self):
        from xtb_api.utils import parse_symbol_key

        result = parse_symbol_key("invalid")
        assert result is None

    def test_parse_symbol_key_with_underscores(self):
        from xtb_api.utils import parse_symbol_key

        result = parse_symbol_key("1_EUR_USD_2")
        assert result is not None
        assert result.asset_class_id == 1
        assert result.symbol_name == "EUR_USD"
        assert result.group_id == 2


class TestTradeOptions:
    """Tests for trade option models."""

    def test_trade_options_default(self):
        opts = TradeOptions()
        assert opts.stop_loss is None
        assert opts.take_profit is None
        assert opts.trailing_stop is None
        assert opts.amount is None

    def test_trade_options_full(self):
        opts = TradeOptions(
            stop_loss=2.50,
            take_profit=3.00,
            trailing_stop=10.0,
            amount=1000.0,
        )
        assert opts.stop_loss == 2.50
        assert opts.take_profit == 3.00
        assert opts.trailing_stop == 10.0
        assert opts.amount == 1000.0
