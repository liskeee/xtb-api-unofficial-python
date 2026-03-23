"""CAS (Central Authentication Service) client for XTB xStation5 WebSocket authentication.

Handles the complete auth flow: login → TGT → Service Ticket → WebSocket login.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import aiohttp

from xtb_api.types.websocket import (
    CASError,
    CASLoginResult,
    CASLoginSuccess,
    CASLoginTwoFactorRequired,
)


@dataclass
class CASServiceTicketResult:
    """Result from service ticket request."""
    service_ticket: str
    service: str


@dataclass
class CASClientConfig:
    """CAS client configuration."""
    base_url: str = "https://xstation.xtb.com/signon/"
    timezone_offset: str | None = None
    user_agent: str = "xStation5/2.94.1 (Linux x86_64)"


class CASClient:
    """CAS authentication client for XTB xStation5.

    Flow:
    1. login(email, password) → TGT (Ticket Granting Ticket)
    2. get_service_ticket(tgt, 'xapi5') → ST (Service Ticket)
    3. Use ST with WebSocket loginWithServiceTicket

    Critical: Use service='xapi5' for WebSocket, NOT 'abigail' (that's for REST API)
    """

    def __init__(self, config: CASClientConfig | None = None) -> None:
        self._config = config or CASClientConfig()
        if self._config.timezone_offset is None:
            self._config.timezone_offset = self._get_timezone_offset()

    async def login(self, email: str, password: str) -> CASLoginResult:
        """Login with email/password using CAS v2 with v1 fallback.

        Tries CAS v2 first (supports 2FA), falls back to CAS v1 if v2 unavailable.

        Args:
            email: XTB account email
            password: XTB account password

        Returns:
            Either success with TGT or 2FA challenge requiring OTP code

        Raises:
            CASError: If credentials invalid, account blocked, or service unavailable
        """
        try:
            return await self._login_v2(email, password)
        except CASError as e:
            if "UNAUTHORIZED" not in e.code:
                try:
                    return await self._login_v1(email, password)
                except CASError:
                    raise e
            raise

    async def _login_v2(self, email: str, password: str) -> CASLoginResult:
        """Login using CAS v2 (supports 2FA)."""
        url = f"{self._config.base_url}v2/tickets"
        fingerprint = self._generate_fingerprint(self._config.user_agent)

        payload = {
            "username": email,
            "password": password,
            "fingerprint": fingerprint,
            "rememberMe": False,
        }

        headers = {
            "Content-Type": "application/json",
            "Time-Zone": self._config.timezone_offset or "+0000",
            "User-Agent": self._config.user_agent,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status == 401:
                    raise CASError("CAS_GET_TGT_UNAUTHORIZED", "Invalid credentials")

                if not resp.ok:
                    error_text = await resp.text()
                    raise CASError(
                        "CAS_LOGIN_FAILED",
                        f"CAS v2 login failed: {resp.status} {error_text}",
                    )

                result = await resp.json()

        # Handle success (no 2FA)
        if result.get("loginPhase") == "TGT_CREATED" and result.get("ticket"):
            return CASLoginSuccess(
                tgt=result["ticket"],
                expires_at=time.time() + 8 * 3600,  # 8 hours
            )

        # Handle 2FA required
        if result.get("loginPhase") == "TWO_FACTOR_REQUIRED" and result.get("sessionId"):
            return CASLoginTwoFactorRequired(
                session_id=result["sessionId"],
                methods=result.get("methods", ["TOTP"]),
                expires_at=time.time() + 5 * 60,  # 5 minutes
            )

        # Handle specific error codes
        code = result.get("code")
        if code:
            match code:
                case "CAS_GET_TGT_UNAUTHORIZED":
                    raise CASError(code, "Invalid email or password")
                case "CAS_GET_TGT_TOO_MANY_OTP_ERROR":
                    wait = result.get("data", {}).get("otpThrottleTimeRemaining", 60)
                    raise CASError(code, f"Too many OTP attempts. Wait {wait}s")
                case "CAS_GET_TGT_OTP_LIMIT_REACHED_ERROR":
                    raise CASError(code, "OTP attempt limit reached. Try again later")
                case "CAS_GET_TGT_OTP_ACCESS_BLOCKED_ERROR":
                    raise CASError(code, "Account temporarily blocked due to too many failed OTP attempts")
                case _:
                    raise CASError(code, result.get("message", "CAS login failed"))

        raise CASError("CAS_UNEXPECTED_RESPONSE", f"Unexpected login response: {result}")

    async def _login_v1(self, email: str, password: str) -> CASLoginResult:
        """Login using CAS v1 (fallback, no 2FA support)."""
        url = f"{self._config.base_url}v1/tickets"

        form_data = aiohttp.FormData()
        form_data.add_field("username", email)
        form_data.add_field("password", password)

        headers = {
            "User-Agent": self._config.user_agent,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, data=form_data, headers=headers, allow_redirects=False
            ) as resp:
                if resp.status == 201:
                    location = resp.headers.get("location", "")
                    if not location:
                        raise CASError(
                            "CAS_V1_NO_LOCATION",
                            "CAS v1 login succeeded but no Location header found",
                        )

                    import re
                    match = re.search(r"/tickets/([^/]+)$", location)
                    if not match:
                        raise CASError(
                            "CAS_V1_INVALID_LOCATION",
                            f"CAS v1 Location header format invalid: {location}",
                        )

                    return CASLoginSuccess(
                        tgt=match.group(1),
                        expires_at=time.time() + 8 * 3600,
                    )

                if resp.status == 401:
                    raise CASError("CAS_GET_TGT_UNAUTHORIZED", "Invalid credentials")

                error_text = await resp.text()
                raise CASError(
                    "CAS_V1_LOGIN_FAILED",
                    f"CAS v1 login failed: {resp.status} {error_text}",
                )

    async def login_with_two_factor(self, session_id: str, code: str) -> CASLoginResult:
        """Submit two-factor authentication code to complete login.

        Args:
            session_id: Session ID from initial login response
            code: OTP code (6 digits from TOTP/SMS/EMAIL)

        Returns:
            TGT if successful, or new 2FA challenge

        Raises:
            CASError: If code is invalid, rate limited, or account blocked
        """
        url = f"{self._config.base_url}v2/tickets/two-factor"

        payload = {
            "sessionId": session_id,
            "code": code,
        }

        headers = {
            "Content-Type": "application/json",
            "Time-Zone": self._config.timezone_offset or "+0000",
            "User-Agent": self._config.user_agent,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if not resp.ok:
                    error_text = await resp.text()
                    raise CASError(
                        "CAS_2FA_REQUEST_FAILED",
                        f"2FA request failed: {resp.status} {error_text}",
                    )

                result = await resp.json()

        if result.get("loginPhase") == "TGT_CREATED" and result.get("ticket"):
            return CASLoginSuccess(
                tgt=result["ticket"],
                expires_at=time.time() + 8 * 3600,
            )

        code_field = result.get("code")
        if code_field:
            raise CASError(code_field, result.get("message", "Two-factor authentication failed"))

        raise CASError(
            "CAS_2FA_UNEXPECTED_RESPONSE",
            f"Unexpected 2FA response: {result}",
        )

    async def get_service_ticket(
        self, tgt: str, service: str = "xapi5"
    ) -> CASServiceTicketResult:
        """Get Service Ticket using TGT via CAS v1 endpoint.

        Args:
            tgt: Ticket Granting Ticket from login()
            service: Service name. Use 'xapi5' for WebSocket, 'abigail' for REST API.

        Returns:
            Service ticket for the specified service
        """
        return await self._get_service_ticket_v1(tgt, service)

    async def _get_service_ticket_v1(
        self, tgt: str, service: str
    ) -> CASServiceTicketResult:
        """Get Service Ticket via CAS v1 endpoint."""
        url = f"{self._config.base_url}v1/tickets/{tgt}"

        form_data = aiohttp.FormData()
        form_data.add_field("service", service)

        headers = {
            "User-Agent": self._config.user_agent,
            "Cookie": f"CASTGC={tgt}",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=form_data, headers=headers) as resp:
                if resp.status == 401:
                    raise CASError("CAS_TGT_EXPIRED", "TGT has expired or is invalid")

                if not resp.ok:
                    error_text = await resp.text()
                    raise CASError(
                        "CAS_SERVICE_TICKET_FAILED",
                        f"CAS v1 service ticket request failed: {resp.status} {error_text}",
                    )

                service_ticket = (await resp.text()).strip()
                if not service_ticket or not service_ticket.startswith("ST-"):
                    raise CASError(
                        "CAS_INVALID_SERVICE_TICKET",
                        f"Invalid service ticket received: {service_ticket}",
                    )

                return CASServiceTicketResult(
                    service_ticket=service_ticket, service=service
                )

    async def get_service_ticket_v2(
        self, tgt: str, service: str = "xapi5"
    ) -> CASServiceTicketResult:
        """Get Service Ticket via CAS v2 endpoint (alternative method)."""
        url = f"{self._config.base_url}v2/serviceTicket"

        payload = {"tgt": tgt, "service": service}

        headers = {
            "Content-Type": "application/json",
            "Time-Zone": self._config.timezone_offset or "+0000",
            "User-Agent": self._config.user_agent,
            "Cookie": f"CASTGC={tgt}",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status == 401:
                    raise CASError("CAS_TGT_EXPIRED", "TGT has expired or is invalid")

                if not resp.ok:
                    error_text = await resp.text()
                    raise CASError(
                        "CAS_SERVICE_TICKET_FAILED",
                        f"CAS v2 service ticket request failed: {resp.status} {error_text}",
                    )

                result = await resp.json()
                service_ticket = result.get("serviceTicket") or result.get("ticket")

                if not service_ticket or not service_ticket.startswith("ST-"):
                    raise CASError(
                        "CAS_INVALID_SERVICE_TICKET",
                        f"Invalid service ticket received: {service_ticket}",
                    )

                return CASServiceTicketResult(
                    service_ticket=service_ticket, service=service
                )

    async def refresh_service_ticket(
        self, tgt: str, service: str = "xapi5"
    ) -> str:
        """Refresh service ticket using existing TGT.

        Service tickets are single-use and expire after 2-5 minutes.
        """
        try:
            result = await self.get_service_ticket(tgt, service)
            return result.service_ticket
        except CASError as e:
            if e.code == "CAS_TGT_EXPIRED":
                raise CASError("CAS_TGT_EXPIRED", "TGT has expired, please login again")
            raise

    def is_tgt_valid(self, login_result: CASLoginResult) -> bool:
        """Check if TGT is still valid (local expiration check only)."""
        if isinstance(login_result, CASLoginSuccess):
            return time.time() < login_result.expires_at
        return time.time() < login_result.expires_at

    def get_tgt_from_result(self, login_result: CASLoginResult) -> str | None:
        """Extract TGT from successful login result."""
        if isinstance(login_result, CASLoginSuccess):
            return login_result.tgt
        return None

    @staticmethod
    def _get_timezone_offset() -> str:
        """Get current timezone offset in ±HHMM format."""
        now = datetime.now(timezone.utc).astimezone()
        offset_seconds = now.utcoffset().total_seconds() if now.utcoffset() else 0
        sign = "+" if offset_seconds >= 0 else "-"
        abs_offset = abs(int(offset_seconds))
        hours = abs_offset // 3600
        minutes = (abs_offset % 3600) // 60
        return f"{sign}{hours:02d}{minutes:02d}"

    @staticmethod
    def _generate_fingerprint(user_agent: str) -> str:
        """Generate SHA-256 fingerprint from user agent."""
        return hashlib.sha256(user_agent.encode()).hexdigest().upper()
