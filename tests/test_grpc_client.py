"""Tests for gRPC-web client."""

import base64
import struct
import time
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from xtb_api.exceptions import AuthenticationError
from xtb_api.grpc.client import GrpcClient
from xtb_api.grpc.proto import SIDE_BUY, SIDE_SELL


def _make_grpc_response(payload: bytes, grpc_status: int = 0) -> bytes:
    """Build a gRPC-web response with data frame + trailers."""
    data_frame = struct.pack(">BI", 0, len(payload)) + payload
    trailers = f"grpc-status: {grpc_status}\r\n".encode()
    trailer_frame = struct.pack(">BI", 0x80, len(trailers)) + trailers
    return data_frame + trailer_frame


def _b64_grpc_response(payload: bytes, grpc_status: int = 0) -> str:
    """Build base64-encoded gRPC-web response text."""
    return base64.b64encode(_make_grpc_response(payload, grpc_status)).decode()


class TestGrpcClientInit:
    def test_init_minimal(self):
        client = GrpcClient(account_number="12345678")
        assert client._account_number == "12345678"
        assert client._account_server == "XS-real1"
        assert client._auth is None
        assert client._jwt is None

    def test_init_with_auth(self):
        mock_auth = MagicMock()
        client = GrpcClient(
            account_number="12345678",
            account_server="XS-demo1",
            auth=mock_auth,
        )
        assert client._auth is mock_auth


class TestGrpcClientJwt:
    @pytest.mark.asyncio
    async def test_get_jwt_caches(self):
        client = GrpcClient(account_number="12345678")

        jwt_token = "eyJhbGciOiJIUzI1NiJ9.eyJhY24iOiIxMjM0NTY3OCJ9.signature123"
        jwt_response = b"\x0a\x40" + jwt_token.encode("latin-1")
        response_b64 = _b64_grpc_response(jwt_response)

        mock_resp = httpx.Response(200, text=response_b64, request=httpx.Request("POST", "https://example.com"))
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        mock_http.is_closed = False
        client._http = mock_http

        jwt1 = await client.get_jwt("TGT-test")
        assert jwt1 == jwt_token

        # Second call should use cache, not make HTTP request
        jwt2 = await client.get_jwt("TGT-test")
        assert jwt2 == jwt_token
        assert mock_http.post.call_count == 1  # Only called once

    @pytest.mark.asyncio
    async def test_get_jwt_uses_auth_manager(self):
        mock_auth = AsyncMock()
        mock_auth.get_tgt = AsyncMock(return_value="TGT-from-auth-manager")

        client = GrpcClient(account_number="12345678", auth=mock_auth)

        jwt_token = "eyJhbGciOiJIUzI1NiJ9.eyJhY24iOiIxMjM0NTY3OCJ9.sig"
        jwt_response = b"\x0a\x40" + jwt_token.encode("latin-1")
        response_b64 = _b64_grpc_response(jwt_response)

        mock_resp = httpx.Response(200, text=response_b64, request=httpx.Request("POST", "https://example.com"))
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        mock_http.is_closed = False
        client._http = mock_http

        jwt = await client.get_jwt()  # No explicit TGT
        assert jwt == jwt_token
        mock_auth.get_tgt.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_jwt_no_tgt_no_auth_raises(self):
        client = GrpcClient(account_number="12345678")
        with pytest.raises(AuthenticationError, match="No TGT provided"):
            await client.get_jwt()

    @pytest.mark.asyncio
    async def test_get_jwt_fails_on_empty_response(self):
        client = GrpcClient(account_number="12345678")

        # Response with no JWT
        response_b64 = _b64_grpc_response(b"\x08\x01")
        mock_resp = httpx.Response(200, text=response_b64, request=httpx.Request("POST", "https://example.com"))
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        mock_http.is_closed = False
        client._http = mock_http

        with pytest.raises(AuthenticationError, match="Failed to extract JWT"):
            await client.get_jwt("TGT-test")


class TestGrpcClientTrading:
    @pytest.mark.asyncio
    async def test_execute_order_success(self):
        client = GrpcClient(account_number="12345678")
        client._jwt = "valid-jwt"
        client._jwt_timestamp = time.monotonic()

        order_uuid = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        payload = f"order_id: {order_uuid}".encode()
        response_b64 = _b64_grpc_response(payload, grpc_status=0)

        mock_resp = httpx.Response(200, text=response_b64, request=httpx.Request("POST", "https://example.com"))
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        mock_http.is_closed = False
        client._http = mock_http

        result = await client.execute_order(9438, 19, SIDE_BUY)
        assert result.success is True
        assert result.order_id == order_uuid

    @pytest.mark.asyncio
    async def test_execute_order_rbac_error(self):
        client = GrpcClient(account_number="12345678")
        client._jwt = "expired-jwt"
        client._jwt_timestamp = time.monotonic()

        # Build a response that only has trailers (no data frame), like a real RBAC error
        trailers = b"grpc-status: 7\r\ngrpc-message: RBAC: access denied\r\n"
        trailer_frame = struct.pack(">BI", 0x80, len(trailers)) + trailers
        response_b64 = base64.b64encode(trailer_frame).decode()

        mock_resp = httpx.Response(200, text=response_b64, request=httpx.Request("POST", "https://example.com"))
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        mock_http.is_closed = False
        client._http = mock_http

        result = await client.execute_order(9438, 19, SIDE_SELL)
        assert result.success is False
        assert "RBAC" in result.error

    @pytest.mark.asyncio
    async def test_buy_sell_shortcuts(self):
        client = GrpcClient(account_number="12345678")
        client._jwt = "valid-jwt"
        client._jwt_timestamp = time.monotonic()

        payload = b"grpc-status: 0\r\n"
        response_b64 = _b64_grpc_response(payload, grpc_status=0)

        mock_resp = httpx.Response(200, text=response_b64, request=httpx.Request("POST", "https://example.com"))
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        mock_http.is_closed = False
        client._http = mock_http

        buy_result = await client.buy(100, 10)
        assert buy_result.success is True

        sell_result = await client.sell(100, 10)
        assert sell_result.success is True

    @pytest.mark.asyncio
    async def test_execute_order_network_error(self):
        client = GrpcClient(account_number="12345678")
        client._jwt = "valid-jwt"
        client._jwt_timestamp = time.monotonic()

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        mock_http.is_closed = False
        client._http = mock_http

        result = await client.execute_order(9438, 19, SIDE_BUY)
        assert result.success is False
        assert "Connection refused" in result.error


class TestParseTradeResponseSafety:
    """Regression: rejected trades must never be reported as success."""

    def test_rejected_trade_grpc_status_16_not_false_positive(self):
        """grpc-status: 16 (unauthenticated) must not match as grpc-status: 0.

        Before the fix, string matching 'grpc-status: 0' could match as a
        substring in base64 error details, and a 6-byte null-prefixed binary
        payload could pass the has_data_frame check — returning success=True
        for actually rejected trades.
        """
        client = GrpcClient(account_number="12345678")

        # Build a response with grpc-status: 16 (UNAUTHENTICATED) in trailer
        # and a small data frame that starts with 0x00 (which old code treated as success)
        data_payload = b"\x00\x00\x00\x00\x00\x00"  # 6 null bytes in data frame
        data_frame = struct.pack(">BI", 0, len(data_payload)) + data_payload
        trailers = b"grpc-status: 16\r\ngrpc-message: token expired\r\n"
        trailer_frame = struct.pack(">BI", 0x80, len(trailers)) + trailers
        response_bytes = data_frame + trailer_frame

        result = client._parse_trade_response(response_bytes)
        assert result.success is False
        assert result.grpc_status == 16

    def test_rejected_trade_with_status_0_substring_in_error_details(self):
        """Error details containing 'grpc-status: 0' as a substring must not match.

        Simulates a response where base64-encoded error details happen to
        contain the bytes 'grpc-status: 0' but the actual trailer status != 0.
        """
        client = GrpcClient(account_number="12345678")

        # Data frame with text that contains 'grpc-status: 0' (e.g. in error detail)
        data_payload = b"error detail grpc-status: 0 in base64 blob"
        data_frame = struct.pack(">BI", 0, len(data_payload)) + data_payload
        # But actual trailer says status 7
        trailers = b"grpc-status: 7\r\ngrpc-message: RBAC: access denied\r\n"
        trailer_frame = struct.pack(">BI", 0x80, len(trailers)) + trailers
        response_bytes = data_frame + trailer_frame

        result = client._parse_trade_response(response_bytes)
        assert result.success is False
        assert result.grpc_status == 7
        assert "RBAC" in result.error

    def test_genuine_success_still_works(self):
        """Ensure real successful trades are still parsed correctly."""
        client = GrpcClient(account_number="12345678")

        order_uuid = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        data_payload = f"order confirmed: {order_uuid}".encode()
        response_bytes = _make_grpc_response(data_payload, grpc_status=0)

        result = client._parse_trade_response(response_bytes)
        assert result.success is True
        assert result.order_id == order_uuid
        assert result.grpc_status == 0


class TestGrpcClientDisconnect:
    @pytest.mark.asyncio
    async def test_disconnect_clears_state(self):
        client = GrpcClient(account_number="12345678")
        client._jwt = "some-jwt"
        client._jwt_timestamp = 12345.0

        mock_http = AsyncMock()
        mock_http.is_closed = False
        mock_http.aclose = AsyncMock()
        client._http = mock_http

        await client.disconnect()
        assert client._jwt is None
        assert client._jwt_timestamp == 0.0
        assert client._http is None
        mock_http.aclose.assert_called_once()


class TestParseTradeResponsePreservesFullError:
    """F22: server error text must not be clipped to 200 chars."""

    def test_long_server_error_preserved(self) -> None:
        from xtb_api.grpc.client import GrpcClient

        client = GrpcClient(account_number="12345678")

        # Rejected trade with a long textual detail in the data frame.
        long_detail = "x" * 500
        data_payload = f"error detail: {long_detail}".encode()
        data_frame = struct.pack(">BI", 0, len(data_payload)) + data_payload
        trailers = b"grpc-status: 9\r\n"  # FAILED_PRECONDITION
        trailer_frame = struct.pack(">BI", 0x80, len(trailers)) + trailers
        response_bytes = data_frame + trailer_frame

        result = client._parse_trade_response(response_bytes)

        assert result.success is False
        assert result.error is not None
        # Full long_detail must appear in the error text — not truncated.
        assert long_detail in result.error
        assert len(result.error) > 200


class TestExecuteOrderExceptionNarrowing:
    """F19: only network/protocol errors become GrpcTradeResult; bugs must bubble."""

    @pytest.mark.asyncio
    async def test_unexpected_exception_propagates(self) -> None:
        """A ValueError (i.e. our own bug) must not be swallowed into result.error."""
        from xtb_api.grpc.client import GrpcClient

        client = GrpcClient(account_number="12345678")
        client._jwt = "valid-jwt"
        client._jwt_timestamp = time.monotonic()

        mock_http = AsyncMock()
        # Simulate an unexpected bug deep in the stack.
        mock_http.post = AsyncMock(side_effect=ValueError("boom — our bug"))
        mock_http.is_closed = False
        client._http = mock_http

        with pytest.raises(ValueError, match="boom"):
            await client.execute_order(9438, 19, SIDE_BUY)

    @pytest.mark.asyncio
    async def test_httpx_network_error_still_caught(self) -> None:
        """httpx transport errors are still converted to a failed GrpcTradeResult."""
        from xtb_api.grpc.client import GrpcClient

        client = GrpcClient(account_number="12345678")
        client._jwt = "valid-jwt"
        client._jwt_timestamp = time.monotonic()

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(side_effect=httpx.ConnectError("conn refused"))
        mock_http.is_closed = False
        client._http = mock_http

        result = await client.execute_order(9438, 19, SIDE_BUY)
        assert result.success is False
        assert "conn refused" in (result.error or "")

    @pytest.mark.asyncio
    async def test_httpx_http_status_error_caught(self) -> None:
        """httpx HTTP errors (5xx) also convert to failed result, not raise."""
        from xtb_api.grpc.client import GrpcClient

        client = GrpcClient(account_number="12345678")
        client._jwt = "valid-jwt"
        client._jwt_timestamp = time.monotonic()

        failing_resp = httpx.Response(
            500,
            text="server error",
            request=httpx.Request("POST", "https://example.com"),
        )
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=failing_resp)
        mock_http.is_closed = False
        client._http = mock_http

        result = await client.execute_order(9438, 19, SIDE_BUY)
        assert result.success is False
        assert result.error is not None


class TestGrpcEmptyResponseSemantics:
    """F01/F14: empty trade response must raise AmbiguousOutcomeError, not ProtocolError."""

    @pytest.mark.asyncio
    async def test_empty_trade_response_raises_ambiguous_outcome(self) -> None:
        from xtb_api.exceptions import AmbiguousOutcomeError
        from xtb_api.grpc.client import GrpcClient

        client = GrpcClient(account_number="12345678")
        client._jwt = "valid-jwt"
        client._jwt_timestamp = time.monotonic()

        # Empty body: HTTP 200 with resp.text == ""
        empty_resp = httpx.Response(200, text="", request=httpx.Request("POST", "https://example.com"))
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=empty_resp)
        mock_http.is_closed = False
        client._http = mock_http

        with pytest.raises(AmbiguousOutcomeError):
            await client.execute_order(9438, 19, SIDE_BUY)

    @pytest.mark.asyncio
    async def test_empty_auth_response_raises_authentication_error(self) -> None:
        """Empty response on the auth endpoint is NOT a trade-side ambiguity."""
        from xtb_api.exceptions import AmbiguousOutcomeError, AuthenticationError
        from xtb_api.grpc.client import GrpcClient

        client = GrpcClient(account_number="12345678")

        empty_resp = httpx.Response(200, text="", request=httpx.Request("POST", "https://example.com"))
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=empty_resp)
        mock_http.is_closed = False
        client._http = mock_http

        with pytest.raises(AuthenticationError):
            await client.get_jwt("TGT-test")

        # And specifically NOT AmbiguousOutcomeError — auth is never ambiguous.
        mock_http.post = AsyncMock(return_value=empty_resp)
        client._http = mock_http
        with pytest.raises(Exception) as exc_info:
            await client.get_jwt("TGT-test")
        assert not isinstance(exc_info.value, AmbiguousOutcomeError)
