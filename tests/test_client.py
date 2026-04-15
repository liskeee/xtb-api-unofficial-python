"""Tests for high-level XTB client."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from xtb_api.client import XTBClient, _decimal_places
from xtb_api.exceptions import InstrumentNotFoundError
from xtb_api.grpc.proto import SIDE_BUY, SIDE_SELL
from xtb_api.grpc.types import GrpcTradeResult
from xtb_api.types.instrument import InstrumentSearchResult
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


class TestDecimalPlaces:
    """Tests for _decimal_places helper."""

    def test_two_decimals(self):
        assert _decimal_places(2.62) == 2

    def test_three_decimals(self):
        assert _decimal_places(1.085) == 3

    def test_integer_returns_min_two(self):
        assert _decimal_places(150.0) == 2

    def test_five_decimals(self):
        assert _decimal_places(1.12345) == 5


class TestXTBClientConnect:
    """Tests for connect/disconnect lifecycle."""

    @pytest.mark.asyncio
    async def test_connect_calls_auth_and_ws(self):
        client = XTBClient(
            email="test@example.com",
            password="secret",
            account_number=12345678,
        )
        client._auth.get_service_ticket = AsyncMock(return_value="ST-test-ticket")
        client._ws._establish_connection = AsyncMock()
        client._ws.register_client_info = AsyncMock()
        client._ws.login_with_service_ticket = AsyncMock()

        await client.connect()

        client._auth.get_service_ticket.assert_called_once()
        client._ws._establish_connection.assert_called_once()
        client._ws.register_client_info.assert_called_once()
        client._ws.login_with_service_ticket.assert_called_once_with("ST-test-ticket")

    @pytest.mark.asyncio
    async def test_disconnect_cleans_up_all(self):
        client = XTBClient(
            email="test@example.com",
            password="secret",
            account_number=12345678,
        )
        client._ws.disconnect_async = AsyncMock()
        client._auth.aclose = AsyncMock()

        # With no gRPC
        await client.disconnect()
        client._ws.disconnect_async.assert_called_once()
        client._auth.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_cleans_up_grpc(self):
        client = XTBClient(
            email="test@example.com",
            password="secret",
            account_number=12345678,
        )
        grpc = client._ensure_grpc()
        grpc.disconnect = AsyncMock()
        client._ws.disconnect_async = AsyncMock()
        client._auth.aclose = AsyncMock()

        await client.disconnect()
        grpc.disconnect.assert_called_once()
        assert client.grpc_client is None


class TestXTBClientTrade:
    """Tests for trade execution path."""

    def _make_client(self):
        client = XTBClient(
            email="test@example.com",
            password="secret",
            account_number=12345678,
        )
        # Mock search_instrument to return a known instrument
        mock_instrument = MagicMock(spec=InstrumentSearchResult)
        mock_instrument.symbol = "CIG.PL"
        mock_instrument.instrument_id = 9438
        mock_instrument.symbol_key = "9_CIG.PL_6"
        client._ws.search_instrument = AsyncMock(return_value=[mock_instrument])
        client._ws.get_positions = AsyncMock(return_value=[])
        return client

    @pytest.mark.asyncio
    async def test_buy_resolves_symbol_and_calls_grpc(self):
        client = self._make_client()
        grpc = client._ensure_grpc()
        grpc.execute_order = AsyncMock(return_value=GrpcTradeResult(success=True, order_id="uuid-123"))

        result = await client.buy("CIG.PL", volume=19)

        assert result.success is True
        assert result.symbol == "CIG.PL"
        assert result.side == "buy"
        assert result.order_id == "uuid-123"
        grpc.execute_order.assert_called_once()
        call_kwargs = grpc.execute_order.call_args
        assert call_kwargs[0] == (9438, 19, SIDE_BUY)

    @pytest.mark.asyncio
    async def test_sell_passes_side_sell(self):
        client = self._make_client()
        grpc = client._ensure_grpc()
        grpc.execute_order = AsyncMock(return_value=GrpcTradeResult(success=True, order_id="uuid-456"))

        result = await client.sell("CIG.PL", volume=10)

        assert result.success is True
        assert result.side == "sell"
        call_kwargs = grpc.execute_order.call_args
        assert call_kwargs[0] == (9438, 10, SIDE_SELL)

    @pytest.mark.asyncio
    async def test_buy_forwards_stop_loss_take_profit(self):
        client = self._make_client()
        grpc = client._ensure_grpc()
        grpc.execute_order = AsyncMock(return_value=GrpcTradeResult(success=True, order_id="uuid-sl"))

        await client.buy("CIG.PL", volume=19, stop_loss=2.50, take_profit=3.00)

        call_kwargs = grpc.execute_order.call_args[1]
        assert call_kwargs["stop_loss_value"] == 250
        assert call_kwargs["stop_loss_scale"] == 2
        assert call_kwargs["take_profit_value"] == 300
        assert call_kwargs["take_profit_scale"] == 2

    @pytest.mark.asyncio
    async def test_options_take_precedence_over_flat_kwargs(self):
        client = self._make_client()
        grpc = client._ensure_grpc()
        grpc.execute_order = AsyncMock(return_value=GrpcTradeResult(success=True))

        opts = TradeOptions(stop_loss=1.50, take_profit=2.00)
        await client.buy("CIG.PL", volume=1, stop_loss=9.99, take_profit=9.99, options=opts)

        call_kwargs = grpc.execute_order.call_args[1]
        assert call_kwargs["stop_loss_value"] == 150
        assert call_kwargs["take_profit_value"] == 200

    @pytest.mark.asyncio
    async def test_rbac_retry_invalidates_jwt(self):
        client = self._make_client()
        grpc = client._ensure_grpc()

        # First call returns RBAC error, second succeeds
        grpc.execute_order = AsyncMock(
            side_effect=[
                GrpcTradeResult(success=False, error="gRPC RBAC: access denied"),
                GrpcTradeResult(success=True, order_id="uuid-retry"),
            ]
        )
        grpc.invalidate_jwt = MagicMock()

        result = await client.buy("CIG.PL", volume=19)

        assert result.success is True
        assert result.order_id == "uuid-retry"
        grpc.invalidate_jwt.assert_called_once()
        assert grpc.execute_order.call_count == 2

    @pytest.mark.asyncio
    async def test_non_rbac_error_not_retried(self):
        client = self._make_client()
        grpc = client._ensure_grpc()

        grpc.execute_order = AsyncMock(return_value=GrpcTradeResult(success=False, error="Insufficient margin"))

        result = await client.buy("CIG.PL", volume=19)

        assert result.success is False
        assert "Insufficient margin" in result.error
        assert grpc.execute_order.call_count == 1

    @pytest.mark.asyncio
    async def test_symbol_not_found_raises(self):
        client = XTBClient(
            email="test@example.com",
            password="secret",
            account_number=12345678,
        )
        client._ws.search_instrument = AsyncMock(return_value=[])

        with pytest.raises(InstrumentNotFoundError):
            await client.buy("NONEXISTENT", volume=1)


def test_v0_5_public_surface_imports() -> None:
    """Confirm the v0.5 additions are reachable from the top-level package."""
    from xtb_api import InstrumentRegistry, XTBAuth, XTBClient
    assert XTBClient is not None
    assert XTBAuth is not None
    assert InstrumentRegistry is not None
