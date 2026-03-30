"""High-level authentication manager that encapsulates the full TGT auth flow.

Handles cached sessions, REST CAS login, browser fallback, and automatic TOTP —
so consumers don't need to implement the auth chain themselves.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from xtb_api.grpc.types import GrpcTradeResult

from xtb_api.auth.cas_client import CASClient, CASClientConfig
from xtb_api.types.websocket import (
    CASError,
    CASLoginSuccess,
    CASLoginTwoFactorRequired,
)

logger = logging.getLogger(__name__)

# TGT validity: 8 hours, but refresh 5 minutes early to avoid races
TGT_LIFETIME_SECONDS = 8 * 3600
TGT_REFRESH_MARGIN_SECONDS = 5 * 60


class AuthManager:
    """Manages the full XTB CAS authentication chain.

    Auth chain (tried in order):
    1. Cached TGT from session file (if configured and still valid)
    2. REST CAS login (fast, no browser)
    3. Playwright browser fallback (if WAF blocks REST)
    4. Automatic TOTP if 2FA required and totp_secret provided

    Example::

        auth = AuthManager(
            email="user@example.com",
            password="secret",
            totp_secret="BASE32SECRET",
            session_file="~/.xtb_session.json",
        )
        tgt = await auth.get_tgt()
        st = await auth.get_service_ticket()
    """

    def __init__(
        self,
        email: str,
        password: str,
        totp_secret: str = "",
        session_file: Path | str | None = None,
        cas_config: CASClientConfig | None = None,
    ) -> None:
        """
        Args:
            email: XTB account email.
            password: XTB account password.
            totp_secret: Base32 TOTP secret for auto-2FA (optional).
                         If omitted and 2FA is required, raises CASError.
            session_file: Path to cache TGT as JSON (optional).
                          If omitted, TGT is only cached in memory.
            cas_config: Custom CAS client configuration (optional).
        """
        self._email = email
        self._password = password
        self._totp_secret = totp_secret
        self._session_file = Path(session_file).expanduser() if session_file else None
        self._cas = CASClient(cas_config)
        self._cached_tgt: str | None = None
        self._cached_expires_at: float = 0.0

    async def get_tgt(self) -> str:
        """Get a valid TGT, using the full auth chain as needed.

        Chain: cached (memory/file) -> REST CAS -> browser fallback -> TOTP.

        Returns:
            Valid TGT string.

        Raises:
            CASError: If authentication fails at all stages.
        """
        # 1. Check in-memory cache
        if self._cached_tgt and self._is_tgt_fresh(self._cached_expires_at):
            return self._cached_tgt

        # 2. Check session file
        if self._session_file:
            cached = self._load_session_file()
            if cached:
                self._cached_tgt = cached["tgt"]
                self._cached_expires_at = cached["expires_at"]
                return self._cached_tgt

        # 3. REST CAS login
        result = await self._login_with_fallback()

        # 4. Handle 2FA if needed
        if isinstance(result, CASLoginTwoFactorRequired):
            result = await self._handle_two_factor(result)

        # 5. Cache and return
        self._cache_tgt(result.tgt, result.expires_at)
        return result.tgt

    def get_tgt_sync(self) -> str:
        """Synchronous wrapper for :meth:`get_tgt`.

        Uses a dedicated thread with its own event loop to avoid conflicts
        with any running loop in the caller's thread.
        """
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(lambda: asyncio.run(self.get_tgt())).result()

    async def get_service_ticket(self, service: str = "xapi5") -> str:
        """Get a service ticket, obtaining a TGT first if needed.

        Args:
            service: CAS service name. Use ``'xapi5'`` for WebSocket,
                     ``'abigail'`` for REST API.

        Returns:
            Service ticket string (``ST-...``).

        Raises:
            CASError: If TGT acquisition or service ticket request fails.
        """
        tgt = await self.get_tgt()
        try:
            st_result = await self._cas.get_service_ticket(tgt, service)
            return st_result.service_ticket
        except CASError as e:
            if e.code == "CAS_TGT_EXPIRED":
                # TGT was cached but expired server-side — clear and retry
                self._invalidate_cache()
                tgt = await self.get_tgt()
                st_result = await self._cas.get_service_ticket(tgt, service)
                return st_result.service_ticket
            raise

    async def create_authenticated_client(
        self,
        ws_url: str = "wss://api5reala.x-station.eu/v1/xstation",
        account_number: int = 0,
        service: str = "xapi5",
    ) -> "XTBWebSocketClient":
        """Create a fully connected and authenticated WebSocket client.

        Handles the full flow: TGT -> service ticket -> WS connect -> login.

        Args:
            ws_url: WebSocket URL for xStation.
            account_number: XTB account number.
            service: CAS service name.

        Returns:
            Connected and authenticated XTBWebSocketClient.
        """
        from xtb_api.types.websocket import WSClientConfig
        from xtb_api.ws.ws_client import XTBWebSocketClient

        service_ticket = await self.get_service_ticket(service)

        config = WSClientConfig(url=ws_url, account_number=account_number)
        client = XTBWebSocketClient(config)
        await client.connect()
        await client.register_client_info()
        await client.login_with_service_ticket(service_ticket)

        return client

    async def execute_trade(
        self,
        instrument_id: int,
        volume: int,
        side: str,
        cdp_url: str = "http://localhost:18800",
        account_number: str = "",
        account_server: str = "XS-real1",
    ) -> GrpcTradeResult:
        """Execute a trade via gRPC-web. Handles auth (TGT->ST->JWT) internally.

        Args:
            instrument_id: gRPC instrument ID (e.g., 9438 for CIG.PL).
            volume: Number of shares.
            side: ``'buy'`` or ``'sell'``.
            cdp_url: Chrome DevTools Protocol URL.
            account_number: XTB account number.
            account_server: XTB account server.

        Returns:
            GrpcTradeResult with success status and order details.
        """
        from xtb_api.grpc import GrpcClient

        client = GrpcClient(
            cdp_url=cdp_url,
            account_number=account_number,
            account_server=account_server,
        )
        await client.connect()

        # Get JWT via service ticket
        service_ticket = await self.get_service_ticket("xapi5")
        await client.get_jwt(service_ticket)

        # Execute
        if side.lower() == "buy":
            result = await client.buy(instrument_id, volume)
        else:
            result = await client.sell(instrument_id, volume)

        # Retry once with fresh JWT if failed
        if not result.success:
            self._invalidate_cache()
            service_ticket = await self.get_service_ticket("xapi5")
            await client.get_jwt(service_ticket)
            if side.lower() == "buy":
                result = await client.buy(instrument_id, volume)
            else:
                result = await client.sell(instrument_id, volume)

        await client.disconnect()
        return result

    async def search_instruments(
        self,
        query: str,
        ws_url: str = "wss://api5reala.x-station.eu/v1/xstation",
        account_number: int = 0,
    ) -> list:
        """Search instruments via WebSocket client.

        Args:
            query: Search string (e.g., ``'CIG'``, ``'BITCOIN'``).
            ws_url: WebSocket URL for xStation.
            account_number: XTB account number.

        Returns:
            List of matching instruments.
        """
        client = await self.create_authenticated_client(ws_url, account_number)
        try:
            return await client.search_instrument(query)
        finally:
            try:
                await client.disconnect_async()
            except Exception:
                pass

    def invalidate(self) -> None:
        """Clear cached TGT from memory and session file."""
        self._invalidate_cache()

    # -- Internal helpers --

    async def _login_with_fallback(self) -> CASLoginSuccess | CASLoginTwoFactorRequired:
        """Try REST CAS login, fall back to browser if WAF blocks."""
        try:
            return await self._cas.login(self._email, self._password)
        except CASError as e:
            # Invalid credentials — don't retry with browser
            if "UNAUTHORIZED" in e.code:
                raise
            logger.info("REST CAS login failed (%s), trying browser fallback", e.code)
            return await self._cas.login_with_browser(self._email, self._password)
        except Exception as e:
            # WAF often returns HTML instead of JSON → aiohttp ContentTypeError
            logger.info("REST CAS login failed (%s), trying browser fallback", e)
            return await self._cas.login_with_browser(self._email, self._password)

    async def _handle_two_factor(
        self, challenge: CASLoginTwoFactorRequired
    ) -> CASLoginSuccess:
        """Handle 2FA challenge using TOTP auto-generation or browser OTP."""
        code = self._generate_totp()

        # If browser session is active, prefer browser OTP (WAF blocks REST 2FA too)
        if hasattr(self._cas, "_browser_auth") and self._cas._browser_auth:
            logger.info("Submitting TOTP via browser OTP...")
            result = await self._cas.submit_browser_otp(code)
        else:
            # Try REST 2FA submission
            two_factor_type = "TOTP" if "TOTP" in challenge.methods else challenge.two_factor_auth_type
            try:
                result = await self._cas.login_with_two_factor(
                    challenge.login_ticket, code, two_factor_type
                )
            except Exception:
                raise

        if isinstance(result, CASLoginTwoFactorRequired):
            raise CASError(
                "AUTH_MANAGER_2FA_LOOP",
                "Server requested 2FA again after submitting code",
            )

        return result

    def _generate_totp(self) -> str:
        """Generate a TOTP code from the stored secret."""
        if not self._totp_secret:
            raise CASError(
                "AUTH_MANAGER_2FA_NO_SECRET",
                "2FA is required but no totp_secret was provided. "
                "Pass totp_secret to AuthManager or disable 2FA on your account.",
            )
        try:
            import pyotp
        except ImportError:
            raise CASError(
                "AUTH_MANAGER_PYOTP_MISSING",
                "2FA requires the pyotp package. Install with: pip install 'pyotp>=2.9.0'",
            )
        totp = pyotp.TOTP(self._totp_secret)
        return totp.now()

    def _cache_tgt(self, tgt: str, expires_at: float) -> None:
        """Cache TGT in memory and optionally to session file."""
        self._cached_tgt = tgt
        self._cached_expires_at = expires_at

        if self._session_file:
            self._save_session_file(tgt, expires_at)

    def _invalidate_cache(self) -> None:
        """Clear TGT from memory and session file."""
        self._cached_tgt = None
        self._cached_expires_at = 0.0

        if self._session_file and self._session_file.exists():
            self._session_file.unlink(missing_ok=True)

    def _load_session_file(self) -> dict | None:
        """Load and validate cached TGT from session file.

        Returns:
            Dict with 'tgt' and 'expires_at' if valid, None otherwise.
        """
        if not self._session_file or not self._session_file.exists():
            return None

        try:
            data = json.loads(self._session_file.read_text())
            tgt = data.get("tgt", "")
            expires_at_str = data.get("expires_at", "")

            if not tgt or not expires_at_str:
                return None

            expires_at = datetime.fromisoformat(expires_at_str).timestamp()

            if not self._is_tgt_fresh(expires_at):
                return None

            return {"tgt": tgt, "expires_at": expires_at}
        except (json.JSONDecodeError, KeyError, ValueError, OSError):
            return None

    def _save_session_file(self, tgt: str, expires_at: float) -> None:
        """Save TGT to session file as JSON."""
        if not self._session_file:
            return

        extracted_at = datetime.now(timezone.utc)
        expires_at_dt = datetime.fromtimestamp(expires_at, tz=timezone.utc)

        data = {
            "tgt": tgt,
            "extracted_at": extracted_at.isoformat(),
            "expires_at": expires_at_dt.isoformat(),
        }

        self._session_file.parent.mkdir(parents=True, exist_ok=True)
        self._session_file.write_text(json.dumps(data, indent=2))

    @staticmethod
    def _is_tgt_fresh(expires_at: float) -> bool:
        """Check if TGT is still valid with a safety margin."""
        return time.time() < (expires_at - TGT_REFRESH_MARGIN_SECONDS)
