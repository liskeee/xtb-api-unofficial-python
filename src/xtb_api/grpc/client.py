"""gRPC-web client for XTB xStation5 trading.

Supports two transport modes:
  1. **Native Python** (primary) — direct HTTP POST via httpx, no browser needed.
     Requires only a valid JWT/TGT. Zero external dependencies beyond httpx.
  2. **Chrome CDP** (fallback) — sends fetch() through Chrome DevTools Protocol
     when native transport fails (e.g. if cookies/origin restrictions apply).

Flow:
1. Build CreateAccessTokenRequest protobuf (TGT + Account)
2. Send auth request → get JWT with account scope (acn/acs)
3. Send trade requests with JWT

The native transport sends standard gRPC-web-text POST requests to
ipax.xtb.com with Authorization: Bearer {jwt}.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
import urllib.request
from typing import Any

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]

try:
    import websockets
    import websockets.asyncio.client
except ImportError:
    websockets = None  # type: ignore[assignment]

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
    """gRPC-web client for XTB xStation5 trading via Chrome DevTools Protocol."""

    def __init__(
        self,
        cdp_url: str | None = "http://localhost:18800",
        account_number: str = "51984891",
        account_server: str = "XS-real1",
        cookies: dict[str, str] | None = None,
    ) -> None:
        self._cdp_url = cdp_url
        self._account_number = account_number
        self._account_server = account_server
        self._cookies = cookies
        self._jwt: str | None = None
        self._jwt_timestamp: float = 0.0
        self._worker_ws_url: str | None = None
        self._page_ws_url: str | None = None
        self._cdp_msg_id = 0

    # ── Native Python Transport ────────────────────────────────────

    async def _grpc_call_native(
        self,
        endpoint: str,
        body_b64: str,
        jwt: str | None = None,
        cookies: dict[str, str] | None = None,
    ) -> bytes:
        """Make a gRPC-web call directly via httpx (no Chrome/CDP needed).

        Args:
            endpoint: Full gRPC-web endpoint URL.
            body_b64: Base64-encoded protobuf body.
            jwt: Optional JWT bearer token.
            cookies: Optional cookies dict (if origin requires session cookies).

        Returns:
            Decoded protobuf response bytes.
        """
        if httpx is None:
            raise RuntimeError("httpx is required for native transport: pip install httpx")

        headers = {
            "Content-Type": GRPC_WEB_TEXT_CONTENT_TYPE,
            "Accept": GRPC_WEB_TEXT_CONTENT_TYPE,
            "X-Grpc-Web": "1",
            "x-user-agent": "grpc-web-javascript/0.1",
        }
        if jwt:
            headers["Authorization"] = f"Bearer {jwt}"

        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                endpoint,
                content=body_b64,
                headers=headers,
                cookies=cookies,
            )
            resp.raise_for_status()
            response_text = resp.text

        if not response_text:
            raise RuntimeError("Native gRPC call returned empty response")

        return base64.b64decode(response_text)

    # ── CDP Discovery ────────────────────────────────────────────

    def _discover_targets(self) -> tuple[str | None, str | None]:
        """Find xStation5 page and worker WebSocket URLs via CDP HTTP API.

        Returns (page_ws_url, worker_ws_url).
        """
        resp = urllib.request.urlopen(f"{self._cdp_url}/json/list", timeout=5)
        targets = json.loads(resp.read())

        page_ws = None
        worker_ws = None

        for target in targets:
            url = target.get("url", "")
            target_type = target.get("type", "")
            ws_url = target.get("webSocketDebuggerUrl", "")

            if not ws_url:
                continue

            if target_type == "page" and (
                "xstation5" in url.lower() or "xtb" in url.lower()
            ):
                page_ws = ws_url
                logger.debug("Found xStation5 page: %s", url)

            if target_type == "worker" and (
                "worker" in url.lower() or "socket" in url.lower()
            ):
                worker_ws = ws_url
                logger.debug("Found worker: %s", url)

        # Fallback: use first page if no xStation5 found
        if not page_ws:
            for target in targets:
                if target.get("type") == "page" and target.get(
                    "webSocketDebuggerUrl"
                ):
                    page_ws = target["webSocketDebuggerUrl"]
                    logger.warning(
                        "xStation5 tab not found, using: %s", target.get("url")
                    )
                    break

        return page_ws, worker_ws

    def _next_id(self) -> int:
        self._cdp_msg_id += 1
        return self._cdp_msg_id

    # ── CDP Communication ────────────────────────────────────────

    async def _cdp_send(
        self,
        ws: Any,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float = 15.0,
    ) -> dict[str, Any]:
        """Send a CDP command and wait for the response."""
        msg_id = self._next_id()
        msg: dict[str, Any] = {"id": msg_id, "method": method}
        if params:
            msg["params"] = params

        await ws.send(json.dumps(msg))

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                raw = await asyncio.wait_for(
                    ws.recv(), timeout=deadline - time.monotonic()
                )
            except asyncio.TimeoutError:
                break
            response = json.loads(raw)
            if response.get("id") == msg_id:
                if "error" in response:
                    raise RuntimeError(
                        f"CDP error ({method}): {response['error']}"
                    )
                return response.get("result", {})

        raise TimeoutError(f"CDP timeout waiting for response to {method}")

    async def _evaluate_js(
        self,
        ws: Any,
        expression: str,
        await_promise: bool = True,
        timeout: float = 15.0,
    ) -> Any:
        """Evaluate JavaScript via CDP Runtime.evaluate."""
        params: dict[str, Any] = {
            "expression": expression,
            "returnByValue": True,
        }
        if await_promise:
            params["awaitPromise"] = True

        result = await self._cdp_send(ws, "Runtime.evaluate", params, timeout=timeout)
        if "exceptionDetails" in result:
            exc = result["exceptionDetails"]
            text = exc.get("text", "")
            exception = exc.get("exception", {})
            desc = exception.get("description", exception.get("value", ""))
            raise RuntimeError(f"JS error: {text} — {desc}")

        return result.get("result", {}).get("value")

    # ── gRPC-web via CDP ─────────────────────────────────────────

    async def _grpc_call_via_worker(
        self,
        worker_ws_url: str,
        endpoint: str,
        body_b64: str,
        jwt: str | None = None,
    ) -> bytes:
        """Make a gRPC-web call through the worker's clean fetch."""
        headers_json = json.dumps(
            {
                "Content-Type": GRPC_WEB_TEXT_CONTENT_TYPE,
                "Accept": GRPC_WEB_TEXT_CONTENT_TYPE,
                "X-Grpc-Web": "1",
                "x-user-agent": "grpc-web-javascript/0.1",
                **({"Authorization": f"Bearer {jwt}"} if jwt else {}),
            }
        )

        js = f"""
        (async () => {{
            const resp = await fetch("{endpoint}", {{
                method: "POST",
                headers: {headers_json},
                body: "{body_b64}",
                credentials: "include",
            }});
            const text = await resp.text();
            return text;
        }})()
        """

        try:
            async with websockets.asyncio.client.connect(worker_ws_url) as ws:
                result = await self._evaluate_js(ws, js, await_promise=True, timeout=20.0)
        except websockets.exceptions.ConnectionClosed as e:
            raise RuntimeError(f"Worker connection closed: {e}") from e
        except Exception as e:
            # Also catch ConnectionClosedError which may be a subclass
            if "ConnectionClosed" in type(e).__name__:
                raise RuntimeError(f"Worker connection closed: {e}") from e
            raise

        if not result:
            raise RuntimeError("Worker fetch returned empty response")

        return base64.b64decode(result)

    async def _grpc_call_via_isolated_world(
        self,
        page_ws_url: str,
        endpoint: str,
        body_b64: str,
        jwt: str | None = None,
    ) -> bytes:
        """Make a gRPC-web call via an isolated world on the page.

        Creates a new JS execution context that has pristine builtins
        (fetch is not patched by xStation5 application code).
        """
        headers_json = json.dumps(
            {
                "Content-Type": GRPC_WEB_TEXT_CONTENT_TYPE,
                "Accept": GRPC_WEB_TEXT_CONTENT_TYPE,
                "X-Grpc-Web": "1",
                "x-user-agent": "grpc-web-javascript/0.1",
                **({"Authorization": f"Bearer {jwt}"} if jwt else {}),
            }
        )

        js = f"""
        (async () => {{
            const resp = await fetch("{endpoint}", {{
                method: "POST",
                headers: {headers_json},
                body: "{body_b64}",
                credentials: "include",
            }});
            const text = await resp.text();
            return text;
        }})()
        """

        async with websockets.asyncio.client.connect(page_ws_url) as ws:
            frame_tree = await self._cdp_send(ws, "Page.getFrameTree")
            frame_id = frame_tree["frameTree"]["frame"]["id"]

            world = await self._cdp_send(
                ws,
                "Page.createIsolatedWorld",
                {
                    "frameId": frame_id,
                    "worldName": "grpc_client",
                    "grantUniveralAccess": True,
                },
            )
            context_id = world["executionContextId"]

            params: dict[str, Any] = {
                "expression": js,
                "contextId": context_id,
                "returnByValue": True,
                "awaitPromise": True,
            }
            result = await self._cdp_send(
                ws, "Runtime.evaluate", params, timeout=20.0
            )

            if "exceptionDetails" in result:
                exc = result["exceptionDetails"]
                desc = exc.get("exception", {}).get(
                    "description", exc.get("text", "unknown")
                )
                raise RuntimeError(f"Isolated world JS error: {desc}")

            b64_result = result.get("result", {}).get("value")

        if not b64_result:
            raise RuntimeError("Isolated world fetch returned empty response")

        return base64.b64decode(b64_result)

    async def _grpc_call_via_page(
        self,
        page_ws_url: str,
        endpoint: str,
        body_b64: str,
        jwt: str | None = None,
    ) -> bytes:
        """Last resort: try fetch directly in the page context.

        Attempts to restore native fetch via a hidden iframe first.
        """
        headers_json = json.dumps(
            {
                "Content-Type": GRPC_WEB_TEXT_CONTENT_TYPE,
                "Accept": GRPC_WEB_TEXT_CONTENT_TYPE,
                "X-Grpc-Web": "1",
                "x-user-agent": "grpc-web-javascript/0.1",
                **({"Authorization": f"Bearer {jwt}"} if jwt else {}),
            }
        )

        js = f"""
        (async () => {{
            let cleanFetch = window.fetch;
            try {{
                const iframe = document.createElement('iframe');
                iframe.style.display = 'none';
                document.body.appendChild(iframe);
                cleanFetch = iframe.contentWindow.fetch.bind(iframe.contentWindow);
                document.body.removeChild(iframe);
            }} catch(e) {{}}

            const resp = await cleanFetch("{endpoint}", {{
                method: "POST",
                headers: {headers_json},
                body: "{body_b64}",
                credentials: "include",
            }});
            const text = await resp.text();
            return text;
        }})()
        """

        async with websockets.asyncio.client.connect(page_ws_url) as ws:
            result = await self._evaluate_js(ws, js, await_promise=True, timeout=20.0)

        if not result:
            raise RuntimeError("Page fetch returned empty response")

        return base64.b64decode(result)

    _WORKER_SHUTDOWN_KEYWORDS = ("shutting down", "global scope", "closed", "connection closed")

    async def _grpc_call(
        self,
        endpoint: str,
        body_b64: str,
        jwt: str | None = None,
    ) -> bytes:
        """Make a gRPC-web call, trying approaches in priority order:
        1. Native Python httpx (no Chrome needed)
        2. CDP worker → isolated world → page (fallback)

        Wraps CDP fallback in a retry loop (max 3 attempts) to handle
        the case where the xStation5 Service Worker restarts.
        """
        # ── Approach 0: Native Python transport (primary) ────────
        if httpx is not None:
            try:
                return await self._grpc_call_native(endpoint, body_b64, jwt, cookies=self._cookies)
            except Exception as e:
                logger.warning("Native transport failed: %s — falling back to CDP", e)

        # ── CDP fallback ─────────────────────────────────────────
        if websockets is None:
            raise RuntimeError(
                "Both native (httpx) and CDP (websockets) transports unavailable. "
                "Install httpx or websockets."
            )

        if not self._page_ws_url:
            self._page_ws_url, self._worker_ws_url = self._discover_targets()

        last_error: Exception | None = None
        max_attempts = 3

        for attempt in range(1, max_attempts + 1):
            if attempt > 1:
                await asyncio.sleep(0.5)
                logger.info("_grpc_call retry attempt %d/%d", attempt, max_attempts)

            # Approach 1: Worker (clean fetch)
            if self._worker_ws_url:
                try:
                    return await self._grpc_call_via_worker(
                        self._worker_ws_url, endpoint, body_b64, jwt
                    )
                except Exception as e:
                    err_str = str(e).lower()
                    if any(kw in err_str for kw in self._WORKER_SHUTDOWN_KEYWORDS):
                        logger.warning(
                            "Worker scope shutting down (%s) — rediscovering targets (attempt %d)",
                            e, attempt,
                        )
                        self._worker_ws_url = None
                        try:
                            self._page_ws_url, self._worker_ws_url = self._discover_targets()
                        except Exception as disc_err:
                            logger.warning("Target rediscovery failed: %s", disc_err)

                        # If worker was rediscovered, retry worker immediately
                        if self._worker_ws_url:
                            try:
                                return await self._grpc_call_via_worker(
                                    self._worker_ws_url, endpoint, body_b64, jwt
                                )
                            except Exception as retry_e:
                                logger.warning(
                                    "Worker retry after rediscovery failed: %s — falling through",
                                    retry_e,
                                )
                                last_error = retry_e
                        else:
                            last_error = e
                    else:
                        logger.warning("Worker fetch failed: %s — trying isolated world", e)
                        last_error = e

            # Approach 2: Isolated world on page
            if self._page_ws_url:
                try:
                    return await self._grpc_call_via_isolated_world(
                        self._page_ws_url, endpoint, body_b64, jwt
                    )
                except Exception as e:
                    logger.warning("Isolated world fetch failed: %s — trying page", e)
                    last_error = e

                # Approach 3: Direct page eval
                try:
                    return await self._grpc_call_via_page(
                        self._page_ws_url, endpoint, body_b64, jwt
                    )
                except Exception as e:
                    logger.warning(
                        "Page eval fetch failed (attempt %d/%d): %s",
                        attempt, max_attempts, e,
                    )
                    last_error = e
                    continue  # retry loop

            else:
                last_error = last_error or RuntimeError(
                    "No CDP targets available. Is Chrome running with "
                    f"--remote-debugging-port on {self._cdp_url}?"
                )
                continue  # retry loop

        raise RuntimeError(
            f"All CDP fetch approaches failed after {max_attempts} attempts. "
            f"Last error: {last_error}"
        ) from last_error

    # ── Public API ───────────────────────────────────────────────

    async def connect(self) -> None:
        """Discover xStation5 tab and Worker via CDP.

        Optional when using native transport (httpx). Only needed if
        CDP fallback is desired.
        """
        if not self._cdp_url:
            logger.info("No CDP URL configured — using native transport only")
            return

        page_ws, worker_ws = self._discover_targets()
        self._page_ws_url = page_ws
        self._worker_ws_url = worker_ws

        if not page_ws:
            raise RuntimeError(
                "No Chrome page target found. Is Chrome running with "
                f"--remote-debugging-port on {self._cdp_url}?"
            )

        logger.info(
            "CDP targets — page: %s, worker: %s",
            "found" if page_ws else "none",
            "found" if worker_ws else "none",
        )

    async def get_jwt(self, tgt_or_st: str) -> str:
        """Get JWT with account scope via CreateAccessToken gRPC call.

        Args:
            tgt_or_st: TGT (Ticket Granting Ticket) from CAS authentication.
                       Note: despite accepting both names, CreateAccessToken
                       actually requires the TGT, not a service ticket.

        Returns:
            JWT string with acn/acs fields for trading.
        """
        now = time.monotonic()
        if self._jwt and (now - self._jwt_timestamp) < _JWT_VALIDITY_SEC:
            return self._jwt

        logger.info("Requesting new JWT via CreateAccessToken...")

        proto_msg = build_create_access_token_request(
            tgt=tgt_or_st,
            account_number=self._account_number,
            account_server=self._account_server,
        )
        body_b64 = build_grpc_web_text_body(proto_msg)

        response_bytes = await self._grpc_call(
            GRPC_AUTH_ENDPOINT, body_b64, jwt=None
        )

        jwt = extract_jwt(response_bytes)
        if not jwt:
            raise RuntimeError(
                "Failed to extract JWT from CreateAccessToken response "
                f"({len(response_bytes)} bytes). "
                "Check that TGT is valid and account info is correct."
            )

        self._jwt = jwt
        self._jwt_timestamp = now
        logger.info("JWT obtained (with account scope)")
        return jwt

    async def buy(self, instrument_id: int, volume: int) -> GrpcTradeResult:
        """Execute BUY market order."""
        return await self.execute_order(instrument_id, volume, SIDE_BUY)

    async def sell(self, instrument_id: int, volume: int) -> GrpcTradeResult:
        """Execute SELL market order."""
        return await self.execute_order(instrument_id, volume, SIDE_SELL)

    async def execute_order(
        self, instrument_id: int, volume: int, side: int
    ) -> GrpcTradeResult:
        """Execute market order via gRPC-web NewMarketOrder.

        The actual HTTP request goes through the Chrome Worker which has
        same-origin access to ipax.xtb.com without CORS restrictions.

        Args:
            instrument_id: gRPC instrument ID (e.g., 9438 for CIG.PL)
            volume: Number of shares
            side: SIDE_BUY (1) or SIDE_SELL (2)

        Returns:
            GrpcTradeResult with success status and order details.
        """
        if not self._jwt:
            raise RuntimeError("No JWT — call get_jwt(tgt) first")

        side_name = "BUY" if side == SIDE_BUY else "SELL"
        logger.info(
            "gRPC trade: %s instrument=%d volume=%d", side_name, instrument_id, volume
        )

        proto_msg = build_new_market_order(instrument_id, volume, side)
        body_b64 = build_grpc_web_text_body(proto_msg)

        try:
            response_bytes = await self._grpc_call(
                GRPC_NEW_ORDER_ENDPOINT, body_b64, jwt=self._jwt
            )
        except Exception as e:
            return GrpcTradeResult(success=False, error=str(e))

        logger.debug(
            "gRPC response: %d bytes — %s",
            len(response_bytes),
            response_bytes[:50].hex(),
        )

        return self._parse_trade_response(response_bytes)

    def _parse_trade_response(self, response_bytes: bytes) -> GrpcTradeResult:
        """Parse gRPC-web trade response into GrpcTradeResult."""
        response_text = response_bytes.decode("latin-1", errors="replace")

        # Success: grpc-status 0 or data frame (0x00 prefix)
        if "grpc-status: 0" in response_text or (
            len(response_bytes) > 5 and response_bytes[0] == 0
        ):
            # Extract order UUID if present (regex for UUID pattern)
            import re

            uuid_match = re.search(
                r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                response_text,
            )
            order_id = uuid_match.group(0) if uuid_match else None
            logger.info("Trade executed successfully via gRPC")
            return GrpcTradeResult(success=True, order_id=order_id, grpc_status=0)

        # Error cases
        error_msg = f"gRPC order rejected: {response_text[:200]}"
        if "RBAC" in response_text:
            error_msg = "gRPC RBAC: access denied — JWT may be expired"
        elif "grpc-status:" in response_text:
            for line in response_text.split("\r\n"):
                if line.startswith("grpc-message:"):
                    error_msg = f"gRPC error: {line}"
                    break

        # Try to extract grpc-status code
        grpc_status = 0
        import re

        status_match = re.search(r"grpc-status:\s*(\d+)", response_text)
        if status_match:
            grpc_status = int(status_match.group(1))

        logger.error(error_msg)
        return GrpcTradeResult(
            success=False, grpc_status=grpc_status, error=error_msg
        )

    async def disconnect(self) -> None:
        """Clean up resources."""
        self._jwt = None
        self._jwt_timestamp = 0.0
        self._page_ws_url = None
        self._worker_ws_url = None
