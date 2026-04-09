"""High-level XTB trading client.

Provides a dead-simple, single-client API that handles all auth lifecycle,
transport selection, and token refresh transparently.

⚠️ Warning: This is an unofficial library. Use at your own risk.
Always test thoroughly on demo accounts before using with real money.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from xtb_api.auth.auth_manager import AuthManager
from xtb_api.auth.cas_client import CASClientConfig
from xtb_api.exceptions import InstrumentNotFoundError
from xtb_api.grpc.client import GrpcClient
from xtb_api.grpc.proto import SIDE_BUY, SIDE_SELL
from xtb_api.types.instrument import InstrumentSearchResult, Quote
from xtb_api.types.trading import AccountBalance, PendingOrder, Position, TradeOptions, TradeResult
from xtb_api.types.websocket import WSClientConfig
from xtb_api.utils import price_from_decimal
from xtb_api.ws.ws_client import XTBWebSocketClient

logger = logging.getLogger(__name__)


class XTBClient:
    """High-level XTB trading client.

    Handles all authentication, token refresh, and transport selection
    automatically. Users never need to understand the auth lifecycle.

    Read operations (balance, positions, quotes, instruments) go through
    WebSocket. Trading (buy/sell) goes through gRPC-web (lazy-initialized
    on first trade call).

    Example::

        client = XTBClient(
            email="user@example.com",
            password="secret",
            account_number=51984891,
            totp_secret="BASE32SECRET",      # optional, auto-handles 2FA
            session_file="~/.xtb_session",   # optional, persists auth
        )
        await client.connect()

        balance = await client.get_balance()
        positions = await client.get_positions()
        result = await client.buy("EURUSD", volume=1, stop_loss=1.0850)

        await client.disconnect()
    """

    def __init__(
        self,
        email: str,
        password: str,
        account_number: int,
        *,
        totp_secret: str = "",
        session_file: Path | str | None = None,
        ws_url: str = "wss://api5reala.x-station.eu/v1/xstation",
        endpoint: str = "meta1",
        account_server: str = "XS-real1",
        auto_reconnect: bool = True,
        cas_config: CASClientConfig | None = None,
    ) -> None:
        """
        Args:
            email: XTB account email.
            password: XTB account password.
            account_number: XTB account number.
            totp_secret: Base32 TOTP secret for automatic 2FA (optional).
            session_file: Path to cache TGT on disk (optional).
            ws_url: WebSocket endpoint URL.
            endpoint: Server endpoint name (e.g., 'meta1').
            account_server: gRPC account server name.
            auto_reconnect: Auto-reconnect WebSocket on disconnect.
            cas_config: Custom CAS client configuration (optional).
        """
        self._account_number = account_number
        self._account_server = account_server

        # Auth manager — shared by WS and gRPC
        self._auth = AuthManager(
            email=email,
            password=password,
            totp_secret=totp_secret,
            session_file=session_file,
            cas_config=cas_config,
        )

        # WebSocket client — always created
        ws_config = WSClientConfig(
            url=ws_url,
            account_number=account_number,
            endpoint=endpoint,
            auto_reconnect=auto_reconnect,
        )
        self._ws = XTBWebSocketClient(ws_config, auth_manager=self._auth)

        # gRPC client — lazy-initialized on first trade
        self._grpc: GrpcClient | None = None

    async def connect(self) -> None:
        """Connect to XTB, authenticate, and start receiving data.

        Handles the full auth flow: TGT → Service Ticket → WebSocket login.
        """
        service_ticket = await self._auth.get_service_ticket()
        await self._ws._establish_connection()
        await self._ws.register_client_info()
        await self._ws.login_with_service_ticket(service_ticket)

    async def disconnect(self) -> None:
        """Disconnect from XTB and clean up all resources."""
        await self._ws.disconnect_async()
        if self._grpc:
            await self._grpc.disconnect()
            self._grpc = None

    # ── Read Operations (WebSocket) ──────────────────────────────

    async def get_balance(self) -> AccountBalance:
        """Get account balance and equity information."""
        return await self._ws.get_balance()

    async def get_positions(self) -> list[Position]:
        """Get all open trading positions."""
        return await self._ws.get_positions()

    async def get_orders(self) -> list[PendingOrder]:
        """Get all pending (limit/stop) orders."""
        return await self._ws.get_orders()

    async def get_quote(self, symbol: str) -> Quote | None:
        """Get current quote (bid/ask prices) for a symbol.

        Args:
            symbol: Symbol name (e.g., 'EURUSD', 'CIG.PL')
        """
        return await self._ws.get_quote(symbol)

    async def search_instrument(self, query: str) -> list[InstrumentSearchResult]:
        """Search for financial instruments by name.

        First call downloads all instruments and caches them.
        Subsequent searches are instant.
        """
        return await self._ws.search_instrument(query)

    # ── Trading (gRPC, lazy-initialized) ─────────────────────────

    async def buy(
        self,
        symbol: str,
        volume: int,
        *,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        options: TradeOptions | None = None,
    ) -> TradeResult:
        """Execute a BUY market order.

        ⚠️ WARNING: This executes real trades. Use demo accounts for testing.

        Args:
            symbol: Symbol name (e.g., 'EURUSD', 'CIG.PL')
            volume: Number of shares/lots
            stop_loss: Stop loss price (flat kwarg for simple use)
            take_profit: Take profit price (flat kwarg for simple use)
            options: Advanced trade options (overrides stop_loss/take_profit)
        """
        return await self._execute_trade(symbol, volume, SIDE_BUY, stop_loss, take_profit, options)

    async def sell(
        self,
        symbol: str,
        volume: int,
        *,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        options: TradeOptions | None = None,
    ) -> TradeResult:
        """Execute a SELL market order.

        ⚠️ WARNING: This executes real trades. Use demo accounts for testing.

        Args:
            symbol: Symbol name (e.g., 'EURUSD', 'CIG.PL')
            volume: Number of shares/lots
            stop_loss: Stop loss price (flat kwarg for simple use)
            take_profit: Take profit price (flat kwarg for simple use)
            options: Advanced trade options (overrides stop_loss/take_profit)
        """
        return await self._execute_trade(symbol, volume, SIDE_SELL, stop_loss, take_profit, options)

    # ── Real-time Events ─────────────────────────────────────────

    def on(self, event: str, callback: Callable[..., Any]) -> None:
        """Register event handler.

        Events:
        - 'tick' — Real-time tick data
        - 'position' — Position update
        - 'symbol' — Symbol data update
        - 'connected' — WebSocket connected
        - 'disconnected' — Connection closed
        - 'error' — Error occurred
        """
        self._ws.on(event, callback)

    def off(self, event: str, callback: Callable[..., Any]) -> None:
        """Remove event handler."""
        self._ws.off(event, callback)

    async def subscribe_ticks(self, symbol: str) -> None:
        """Subscribe to real-time tick data for a symbol.

        Args:
            symbol: Symbol name (e.g., 'EURUSD'). Resolves to symbol key automatically.
        """
        symbol_key = await self._resolve_symbol_key(symbol)
        await self._ws.subscribe_ticks(symbol_key)

    async def unsubscribe_ticks(self, symbol: str) -> None:
        """Unsubscribe from tick data for a symbol."""
        symbol_key = await self._resolve_symbol_key(symbol)
        await self._ws.unsubscribe_ticks(symbol_key)

    # ── Properties ───────────────────────────────────────────────

    @property
    def is_connected(self) -> bool:
        """Whether WebSocket is connected."""
        return self._ws.is_connected

    @property
    def is_authenticated(self) -> bool:
        """Whether authenticated with XTB servers."""
        return self._ws.is_authenticated

    @property
    def account_number(self) -> int:
        """Account number."""
        return self._account_number

    @property
    def ws(self) -> XTBWebSocketClient:
        """Access underlying WebSocket client for advanced use."""
        return self._ws

    @property
    def grpc_client(self) -> GrpcClient | None:
        """Access underlying gRPC client (None until first trade)."""
        return self._grpc

    @property
    def auth(self) -> AuthManager:
        """Access the auth manager."""
        return self._auth

    # ── Internal ─────────────────────────────────────────────────

    def _ensure_grpc(self) -> GrpcClient:
        """Lazy-initialize gRPC client on first trade."""
        if self._grpc is None:
            self._grpc = GrpcClient(
                account_number=str(self._account_number),
                account_server=self._account_server,
                auth=self._auth,
            )
        return self._grpc

    async def _resolve_symbol_key(self, symbol: str) -> str:
        """Resolve a symbol name to its internal symbol key.

        Uses the instrument cache (downloading it if needed).
        If the symbol already looks like a key (contains '_'), returns as-is.
        """
        if "_" in symbol:
            return symbol

        results = await self._ws.search_instrument(symbol)
        for r in results:
            if r.symbol.upper() == symbol.upper():
                return r.symbol_key
        if results:
            return results[0].symbol_key
        raise InstrumentNotFoundError(f"Symbol not found: {symbol}")

    async def _resolve_instrument_id(self, symbol: str) -> int:
        """Resolve a symbol name to its gRPC instrument ID."""
        results = await self._ws.search_instrument(symbol)
        for r in results:
            if r.symbol.upper() == symbol.upper():
                return r.instrument_id
        if results:
            return results[0].instrument_id
        raise InstrumentNotFoundError(f"Symbol not found: {symbol}")

    async def _execute_trade(
        self,
        symbol: str,
        volume: int,
        side: int,
        stop_loss: float | None,
        take_profit: float | None,
        options: TradeOptions | None,
    ) -> TradeResult:
        """Execute a trade via gRPC, resolving the symbol first."""
        grpc = self._ensure_grpc()

        instrument_id = await self._resolve_instrument_id(symbol)

        # Merge flat kwargs into TradeOptions
        effective_sl = (options.stop_loss if options else None) or stop_loss
        effective_tp = (options.take_profit if options else None) or take_profit

        # Convert SL/TP floats to protobuf price (value, scale)
        sl_value = sl_scale = tp_value = tp_scale = None
        if effective_sl is not None:
            p = price_from_decimal(effective_sl, 5)
            sl_value, sl_scale = p.value, p.scale
        if effective_tp is not None:
            p = price_from_decimal(effective_tp, 5)
            tp_value, tp_scale = p.value, p.scale

        result = await grpc.execute_order(
            instrument_id,
            volume,
            side,
            stop_loss_value=sl_value,
            stop_loss_scale=sl_scale,
            take_profit_value=tp_value,
            take_profit_scale=tp_scale,
        )

        # Retry ONLY on auth error (RBAC/expired JWT), not on trade rejection
        if not result.success and result.error and "RBAC" in result.error:
            logger.info("RBAC error, refreshing JWT and retrying...")
            grpc._jwt = None
            grpc._jwt_timestamp = 0.0
            result = await grpc.execute_order(
                instrument_id,
                volume,
                side,
                stop_loss_value=sl_value,
                stop_loss_scale=sl_scale,
                take_profit_value=tp_value,
                take_profit_scale=tp_scale,
            )

        side_str = "buy" if side == SIDE_BUY else "sell"
        return TradeResult(
            success=result.success,
            symbol=symbol,
            side=side_str,
            volume=float(volume),
            order_id=result.order_id,
            error=result.error,
        )
