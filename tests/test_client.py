"""Tests for high-level XTB client."""

import pytest

from xtb_api.client import XTBClient, XTBClientConfig
from xtb_api.types.trading import TradeOptions
from xtb_api.types.websocket import WSAuthOptions, WSClientConfig, WSCredentials


class TestXTBClientConfig:
    """Tests for XTB client configuration."""

    def test_websocket_config(self):
        config = XTBClientConfig(
            mode="websocket",
            websocket=WSClientConfig(
                url="wss://api5demoa.x-station.eu/v1/xstation",
                account_number=12345678,
            ),
        )
        assert config.mode == "websocket"
        assert config.websocket is not None


class TestXTBClientInit:
    """Tests for XTB client initialization."""

    def test_websocket_mode(self):
        client = XTBClient(
            XTBClientConfig(
                mode="websocket",
                websocket=WSClientConfig(
                    url="wss://api5demoa.x-station.eu/v1/xstation",
                    account_number=12345678,
                ),
            )
        )
        assert client.ws is not None

    def test_websocket_factory(self):
        client = XTBClient.websocket(
            url="wss://api5demoa.x-station.eu/v1/xstation",
            account_number=12345678,
        )
        assert client.ws is not None

    def test_websocket_mode_requires_config(self):
        with pytest.raises(ValueError, match="websocket config required"):
            XTBClient(XTBClientConfig(mode="websocket"))

    def test_websocket_with_auth(self):
        client = XTBClient.websocket(
            url="wss://api5demoa.x-station.eu/v1/xstation",
            account_number=12345678,
            auth=WSAuthOptions(
                credentials=WSCredentials(email="test@test.com", password="pass")
            ),
        )
        assert client.ws is not None
        assert client.ws._cas_client is not None


class TestXTBClientUtils:
    """Tests for utility functions used by client."""

    def test_imports(self):
        from xtb_api import (
            CASClient,
            SocketStatus,
            SubscriptionEid,
            Xs6Side,
            XTBClient,
        )
        # Just verify all public exports are accessible
        assert XTBClient is not None
        assert CASClient is not None
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
