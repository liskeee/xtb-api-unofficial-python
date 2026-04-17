"""High-level XTB trading client.

Provides a dead-simple, single-client API that handles all auth lifecycle,
transport selection, and token refresh transparently.

⚠️ Warning: This is an unofficial library. Use at your own risk.
Always test thoroughly on demo accounts before using with real money.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, cast

from xtb_api.auth.auth_manager import AuthManager, SessionSource
from xtb_api.auth.cas_client import CASClientConfig
from xtb_api.exceptions import AmbiguousOutcomeError, InstrumentNotFoundError
from xtb_api.grpc.client import GrpcClient
from xtb_api.grpc.proto import SIDE_BUY, SIDE_SELL
from xtb_api.types.instrument import InstrumentSearchResult, Quote
from xtb_api.types.trading import AccountBalance, PendingOrder, Position, TradeOptions, TradeOutcome, TradeResult
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

    @property
    def session_source(self) -> SessionSource:
        """Where the currently-held TGT came from (see :class:`SessionSource`).

        Inspect after :meth:`connect` to verify whether session reuse actually
        happened. ``SESSION_FILE`` / ``MEMORY`` mean no fresh login occurred
        (no XTB "new login" email); ``CAS_LOGIN`` / ``BROWSER_LOGIN`` indicate
        that the cached TGT was missing or expired and a fresh login ran.
        """
        return self._auth.session_source

    @property
    def session_expires_at(self) -> float | None:
        """Unix timestamp at which the current TGT expires (``None`` if unset)."""
        return self._auth.session_expires_at

    async def disconnect(self) -> None:
        """Disconnect from XTB and clean up all resources."""
        await self._ws.disconnect_async()
        if self._grpc:
            await self._grpc.disconnect()
            self._grpc = None
        await self._auth.aclose()

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
        """Execute a BUY market order via gRPC using ``SIDE_BUY`` (value 1).

        ⚠️ WARNING: This executes real trades. Use demo accounts for testing.

        Note: This uses the gRPC protocol side constant (``SIDE_BUY=1``),
        which differs from the WebSocket constant (``Xs6Side.BUY=0``). Do not mix.

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
        """Execute a SELL market order via gRPC using ``SIDE_SELL`` (value 2).

        ⚠️ WARNING: This executes real trades. Use demo accounts for testing.

        Note: This uses the gRPC protocol side constant (``SIDE_SELL=2``),
        which differs from the WebSocket constant (``Xs6Side.SELL=1``). Do not mix.

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
        """Access underlying WebSocket client for advanced use.

        Warning: The WebSocket client's ``buy()``/``sell()`` methods use
        ``Xs6Side`` constants (BUY=0, SELL=1), which differ from the gRPC
        constants (SIDE_BUY=1, SIDE_SELL=2) used by ``XTBClient.buy()``/
        ``sell()``. Do not pass side values between protocols.
        """
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
        side_str = cast("Literal['buy', 'sell']", "buy" if side == SIDE_BUY else "sell")

        # Volume validation: reject anything that rounds to less than 1 share.
        rounded = int(volume + 0.5)
        if rounded < 1:
            return TradeResult(
                status=TradeOutcome.INSUFFICIENT_VOLUME,
                symbol=symbol,
                side=side_str,
                volume=float(volume),
                order_id=None,
                error=f"{volume} rounds to {rounded} (need >= 1)",
                error_code="INSUFFICIENT_VOLUME",
            )

        grpc = self._ensure_grpc()
        try:
            instrument_id = await self._resolve_instrument_id(symbol)
        except InstrumentNotFoundError as exc:
            return TradeResult(
                status=TradeOutcome.REJECTED,
                symbol=symbol,
                side=side_str,
                volume=float(volume),
                order_id=None,
                error=str(exc),
                error_code="INSTRUMENT_NOT_FOUND",
            )

        # Merge flat kwargs into effective SL/TP (options take precedence)
        effective_sl = options.stop_loss if options and options.stop_loss is not None else stop_loss
        effective_tp = options.take_profit if options and options.take_profit is not None else take_profit

        sl_value = sl_scale = tp_value = tp_scale = None
        if effective_sl is not None:
            p = price_from_decimal(effective_sl, _decimal_places(effective_sl))
            sl_value, sl_scale = p.value, p.scale
        if effective_tp is not None:
            p = price_from_decimal(effective_tp, _decimal_places(effective_tp))
            tp_value, tp_scale = p.value, p.scale

        try:
            result = await grpc.execute_order(
                instrument_id,
                volume,
                side,
                stop_loss_value=sl_value,
                stop_loss_scale=sl_scale,
                take_profit_value=tp_value,
                take_profit_scale=tp_scale,
            )
        except AmbiguousOutcomeError as exc:
            return TradeResult(
                status=TradeOutcome.AMBIGUOUS,
                symbol=symbol,
                side=side_str,
                volume=float(volume),
                order_id=None,
                error=str(exc),
                error_code="AMBIGUOUS_NO_RESPONSE",
            )

        # F02/F13: detect RBAC/AUTH_EXPIRED via grpc_status 7 — reliable
        # regardless of the free-text error message.
        if not result.success and getattr(result, "grpc_status", 0) == 7:
            # Idempotency probe: did the first call actually fill despite
            # the RBAC error? Compare live positions against the request.
            existing = await self._find_matching_position(symbol, volume, side_str)
            if existing is not None:
                logger.info(
                    "RBAC returned but matching position %s already exists — skipping retry (idempotent short-circuit)",
                    existing.order_id,
                )
                return TradeResult(
                    status=TradeOutcome.FILLED,
                    symbol=symbol,
                    side=side_str,
                    volume=float(volume),
                    price=existing.open_price,
                    order_id=existing.order_id,
                    error=None,
                    error_code=None,
                )

            logger.info("RBAC error, refreshing JWT and retrying...")
            grpc.invalidate_jwt()
            try:
                result = await grpc.execute_order(
                    instrument_id,
                    volume,
                    side,
                    stop_loss_value=sl_value,
                    stop_loss_scale=sl_scale,
                    take_profit_value=tp_value,
                    take_profit_scale=tp_scale,
                )
            except AmbiguousOutcomeError as exc:
                return TradeResult(
                    status=TradeOutcome.AMBIGUOUS,
                    symbol=symbol,
                    side=side_str,
                    volume=float(volume),
                    order_id=None,
                    error=str(exc),
                    error_code="AMBIGUOUS_NO_RESPONSE",
                )

        return await self._build_trade_result(result, symbol, side_str, volume)

    async def _build_trade_result(
        self,
        grpc_result: Any,
        symbol: str,
        side_str: Literal["buy", "sell"],
        volume: int,
    ) -> TradeResult:
        """Map a GrpcTradeResult to a typed TradeResult."""
        if grpc_result.success:
            fill_price, fill_code = await self._poll_fill_price(symbol)
            return TradeResult(
                status=TradeOutcome.FILLED,
                symbol=symbol,
                side=side_str,
                volume=float(volume),
                price=fill_price,
                order_id=grpc_result.order_id,
                error=None,
                error_code=fill_code,
            )

        # Non-success: categorize by grpc_status / error text.
        status_code = getattr(grpc_result, "grpc_status", 0) or 0
        err_text = grpc_result.error or ""
        if status_code == 7:
            outcome = TradeOutcome.AUTH_EXPIRED
            error_code: str | None = "RBAC_DENIED"
        else:
            outcome = TradeOutcome.REJECTED
            error_code = None

        return TradeResult(
            status=outcome,
            symbol=symbol,
            side=side_str,
            volume=float(volume),
            order_id=grpc_result.order_id,
            error=err_text or None,
            error_code=error_code,
        )

    async def _find_matching_position(
        self, symbol: str, volume: int, side_str: Literal["buy", "sell"]
    ) -> Position | None:
        """Find a live position that plausibly corresponds to a just-sent trade.

        Matching is best-effort: symbol (case-insensitive) + side + volume.
        A match means the first submission landed despite the RBAC error —
        caller must return FILLED instead of retrying.
        """
        try:
            positions = await self._ws.get_positions()
        except Exception as exc:
            logger.warning("Idempotency probe failed (get_positions): %s", exc)
            return None

        target = symbol.upper()
        for p in positions:
            if p.symbol.upper() == target and p.side == side_str and abs(p.volume - float(volume)) < 1e-9:
                return p
        return None

    async def _poll_fill_price(
        self, symbol: str, attempts: int = 3, delay_sec: float = 1.0
    ) -> tuple[float | None, str | None]:
        """Poll positions after a successful trade to determine the fill price.

        Returns ``(price, error_code)``. ``error_code`` is None when the
        price was observed, ``"FILL_PRICE_UNKNOWN"`` when the position did
        not appear within ``attempts`` tries. The trade still succeeded —
        the order ID is the authoritative record.
        """
        target = symbol.upper()
        for i in range(attempts):
            try:
                positions = await self._ws.get_positions()
                for p in positions:
                    if p.symbol.upper() == target:
                        return p.open_price, None
            except Exception as exc:
                logger.warning("Fill-price poll attempt %d/%d failed: %s", i + 1, attempts, exc)
            if i < attempts - 1:
                await asyncio.sleep(delay_sec)
        logger.warning(
            "Could not determine fill price for %s after %d attempts",
            symbol,
            attempts,
        )
        return None, "FILL_PRICE_UNKNOWN"


def _decimal_places(value: float, max_scale: int = 5) -> int:
    """Determine the number of decimal places in a float, up to max_scale."""
    text = f"{value:.{max_scale}f}"
    decimals = text.split(".")[1] if "." in text else ""
    # Strip trailing zeros
    stripped = decimals.rstrip("0")
    return max(len(stripped), 2)  # at least 2 for prices
