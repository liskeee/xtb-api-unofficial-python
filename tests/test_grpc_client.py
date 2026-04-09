"""Tests for gRPC-web client."""

import base64
import struct
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from xtb_api.exceptions import AuthenticationError, ProtocolError
from xtb_api.grpc.client import GrpcClient, _JWT_VALIDITY_SEC
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
