"""gRPC-web client for XTB xStation5 trading.

Uses native HTTP POST via httpx for gRPC-web calls to ipax.xtb.com.
Requires a valid TGT (obtained via AuthManager) to create JWT tokens.

Flow:
1. Build CreateAccessTokenRequest protobuf (TGT + Account)
2. Send auth request → get JWT with account scope (acn/acs)
3. Send trade requests with JWT
"""

from __future__ import annotations

import base64
import contextlib
import logging
import re
import time
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from xtb_api.auth.auth_manager import AuthManager

from xtb_api.exceptions import (
    AuthenticationError,
    ProtocolError,
)
from xtb_api.grpc.proto import (
    GRPC_AUTH_ENDPOINT,
    GRPC_NEW_ORDER_ENDPOINT,
    GRPC_WEB_TEXT_CONTENT_TYPE,
    SIDE_BUY,
    SIDE_SELL,
    build_create_access_token_request,
    build_grpc_web_text_body,
    build_new_market_order,
    extract_jwt,
)
from xtb_api.grpc.types import GrpcTradeResult

logger = logging.getLogger(__name__)

# JWT cache lifetime
_JWT_VALIDITY_SEC = 300  # 5 minutes


class GrpcClient:
    """gRPC-web client for XTB xStation5 trading.

    When an AuthManager is provided, JWT tokens are automatically
    refreshed from the shared TGT — no manual token management needed.
    """

    def __init__(
        self,
        account_number: str,
        account_server: str = "XS-real1",
        auth: AuthManager | None = None,
    ) -> None:
        self._account_number = account_number
        self._account_server = account_server
        self._auth = auth
        self._jwt: str | None = None
        self._jwt_timestamp: float = 0.0
        self._http: httpx.AsyncClient | None = None

    def invalidate_jwt(self) -> None:
        """Clear the cached JWT so the next call fetches a fresh one."""
        self._jwt = None
        self._jwt_timestamp = 0.0

    async def _ensure_http(self) -> httpx.AsyncClient:
        """Get or create the long-lived httpx client."""
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=20.0)
        return self._http

    async def _grpc_call(
        self,
        endpoint: str,
        body_b64: str,
        jwt: str | None = None,
    ) -> bytes:
        """Make a gRPC-web call via httpx.

        Args:
            endpoint: Full gRPC-web endpoint URL.
            body_b64: Base64-encoded protobuf body.
            jwt: Optional JWT bearer token.

        Returns:
            Decoded protobuf response bytes.
        """
        headers = {
            "Content-Type": GRPC_WEB_TEXT_CONTENT_TYPE,
            "Accept": GRPC_WEB_TEXT_CONTENT_TYPE,
            "X-Grpc-Web": "1",
            "x-user-agent": "grpc-web-javascript/0.1",
        }
        if jwt:
            headers["Authorization"] = f"Bearer {jwt}"

        client = await self._ensure_http()
        resp = await client.post(endpoint, content=body_b64, headers=headers)
        resp.raise_for_status()

        if not resp.text:
            raise ProtocolError("gRPC call returned empty response")

        return base64.b64decode(resp.text)

    async def get_jwt(self, tgt: str | None = None) -> str:
        """Get JWT with account scope via CreateAccessToken gRPC call.

        If an AuthManager is configured, the TGT is obtained automatically.
        Otherwise, a TGT must be passed explicitly.

        Args:
            tgt: TGT string. If None, uses AuthManager to get one.

        Returns:
            JWT string with acn/acs fields for trading.
        """
        now = time.monotonic()
        if self._jwt and (now - self._jwt_timestamp) < _JWT_VALIDITY_SEC:
            return self._jwt

        if tgt is None:
            if self._auth is None:
                raise AuthenticationError("No TGT provided and no AuthManager configured")
            tgt = await self._auth.get_tgt()

        logger.info("Requesting new JWT via CreateAccessToken...")

        proto_msg = build_create_access_token_request(
            tgt=tgt,
            account_number=self._account_number,
            account_server=self._account_server,
        )
        body_b64 = build_grpc_web_text_body(proto_msg)

        response_bytes = await self._grpc_call(GRPC_AUTH_ENDPOINT, body_b64, jwt=None)

        jwt = extract_jwt(response_bytes)
        if not jwt:
            raise AuthenticationError(
                "Failed to extract JWT from CreateAccessToken response "
                f"({len(response_bytes)} bytes). "
                "Check that TGT is valid and account info is correct."
            )

        self._jwt = jwt
        self._jwt_timestamp = now
        logger.info("JWT obtained (with account scope)")
        return jwt

    async def _ensure_jwt(self) -> str:
        """Ensure a valid JWT is available, refreshing if needed."""
        now = time.monotonic()
        if self._jwt and (now - self._jwt_timestamp) < _JWT_VALIDITY_SEC:
            return self._jwt
        return await self.get_jwt()

    async def buy(
        self,
        instrument_id: int,
        volume: int,
        *,
        stop_loss_value: int | None = None,
        stop_loss_scale: int | None = None,
        take_profit_value: int | None = None,
        take_profit_scale: int | None = None,
    ) -> GrpcTradeResult:
        """Execute BUY market order."""
        return await self.execute_order(
            instrument_id,
            volume,
            SIDE_BUY,
            stop_loss_value=stop_loss_value,
            stop_loss_scale=stop_loss_scale,
            take_profit_value=take_profit_value,
            take_profit_scale=take_profit_scale,
        )

    async def sell(
        self,
        instrument_id: int,
        volume: int,
        *,
        stop_loss_value: int | None = None,
        stop_loss_scale: int | None = None,
        take_profit_value: int | None = None,
        take_profit_scale: int | None = None,
    ) -> GrpcTradeResult:
        """Execute SELL market order."""
        return await self.execute_order(
            instrument_id,
            volume,
            SIDE_SELL,
            stop_loss_value=stop_loss_value,
            stop_loss_scale=stop_loss_scale,
            take_profit_value=take_profit_value,
            take_profit_scale=take_profit_scale,
        )

    async def execute_order(
        self,
        instrument_id: int,
        volume: int,
        side: int,
        *,
        stop_loss_value: int | None = None,
        stop_loss_scale: int | None = None,
        take_profit_value: int | None = None,
        take_profit_scale: int | None = None,
    ) -> GrpcTradeResult:
        """Execute market order via gRPC-web NewMarketOrder.

        Args:
            instrument_id: gRPC instrument ID (e.g., 9438 for CIG.PL)
            volume: Number of shares
            side: SIDE_BUY (1) or SIDE_SELL (2)
            stop_loss_value: SL price as integer (e.g., 10850 for 1.0850 with scale=4)
            stop_loss_scale: SL price scale (decimal places)
            take_profit_value: TP price as integer
            take_profit_scale: TP price scale (decimal places)

        Returns:
            GrpcTradeResult with success status and order details.
        """
        jwt = await self._ensure_jwt()

        side_name = "BUY" if side == SIDE_BUY else "SELL"
        logger.info("gRPC trade: %s instrument=%d volume=%d", side_name, instrument_id, volume)

        proto_msg = build_new_market_order(
            instrument_id,
            volume,
            side,
            stop_loss_value=stop_loss_value,
            stop_loss_scale=stop_loss_scale,
            take_profit_value=take_profit_value,
            take_profit_scale=take_profit_scale,
        )
        body_b64 = build_grpc_web_text_body(proto_msg)

        try:
            response_bytes = await self._grpc_call(GRPC_NEW_ORDER_ENDPOINT, body_b64, jwt=jwt)
        except Exception as e:
            return GrpcTradeResult(success=False, error=str(e))

        logger.debug(
            "gRPC response: %d bytes — %s",
            len(response_bytes),
            response_bytes[:50].hex(),
        )

        return self._parse_trade_response(response_bytes)

    def _parse_trade_response(self, response_bytes: bytes) -> GrpcTradeResult:
        """Parse gRPC-web trade response into GrpcTradeResult.

        Uses proper gRPC frame parsing instead of string matching to avoid
        false-positive success on rejected trades (e.g. 'grpc-status: 16'
        containing '0' as a substring in error details).
        """
        # Parse gRPC frames: flag 0x00 = data, flag 0x80 = trailers
        grpc_status: int | None = None
        grpc_message: str | None = None
        data_payload: bytes = b""

        pos = 0
        while pos + 5 <= len(response_bytes):
            flag = response_bytes[pos]
            import struct

            length = struct.unpack(">I", response_bytes[pos + 1 : pos + 5])[0]
            pos += 5
            if pos + length > len(response_bytes):
                break
            frame_data = response_bytes[pos : pos + length]
            pos += length

            if flag & 0x80:
                # Trailer frame — parse as HTTP/2 headers (key: value\r\n)
                trailer_text = frame_data.decode("latin-1", errors="replace")
                for line in trailer_text.split("\r\n"):
                    if line.startswith("grpc-status:"):
                        with contextlib.suppress(ValueError):
                            grpc_status = int(line.split(":", 1)[1].strip())
                    elif line.startswith("grpc-message:"):
                        grpc_message = line.split(":", 1)[1].strip()
            else:
                # Data frame
                data_payload = frame_data

        # Success requires explicit grpc-status 0 from trailer
        if grpc_status == 0:
            response_text = data_payload.decode("latin-1", errors="replace")
            uuid_match = re.search(
                r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                response_text,
            )
            order_id = uuid_match.group(0) if uuid_match else None
            logger.info("Trade executed successfully via gRPC")
            return GrpcTradeResult(success=True, order_id=order_id, grpc_status=0)

        # Error cases
        status = grpc_status if grpc_status is not None else 0
        response_text = response_bytes.decode("latin-1", errors="replace")
        if grpc_message and "RBAC" in grpc_message or "RBAC" in response_text:
            error_msg = "gRPC RBAC: access denied — JWT may be expired"
        elif grpc_message:
            error_msg = f"gRPC error: grpc-message: {grpc_message}"
        else:
            error_msg = f"gRPC order rejected: {response_text}"

        logger.error(error_msg)
        return GrpcTradeResult(success=False, grpc_status=status, error=error_msg)

    async def disconnect(self) -> None:
        """Clean up resources."""
        self._jwt = None
        self._jwt_timestamp = 0.0
        if self._http and not self._http.is_closed:
            await self._http.aclose()
            self._http = None
