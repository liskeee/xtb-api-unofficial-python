"""Tests for CAS authentication client."""

import hashlib
import time
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from xtb_api.auth.cas_client import CASClient, CASClientConfig
from xtb_api.types.websocket import CASError, CASLoginSuccess, CASLoginTwoFactorRequired


def _mock_response(
    status_code: int = 200,
    json_data: dict | None = None,
    text: str = "",
    headers: dict | None = None,
) -> httpx.Response:
    """Create a mock httpx.Response."""
    resp = httpx.Response(
        status_code=status_code,
        headers=headers or {},
        text=text,
        json=json_data,
    )
    return resp


class TestCASClientConfig:
    """Tests for CAS client configuration."""

    def test_default_config(self):
        config = CASClientConfig()
        assert config.base_url == "https://xstation.xtb.com/signon/"
        assert config.user_agent == "xStation5/2.94.1 (Linux x86_64)"

    def test_custom_config(self):
        config = CASClientConfig(
            base_url="https://custom.example.com/signon/",
            user_agent="Custom/1.0",
        )
        assert config.base_url == "https://custom.example.com/signon/"
        assert config.user_agent == "Custom/1.0"


class TestCASClient:
    """Tests for CAS authentication client."""

    def test_init_default(self):
        client = CASClient()
        assert client._config.base_url == "https://xstation.xtb.com/signon/"
        assert client._config.timezone_offset is not None

    def test_init_custom_config(self):
        config = CASClientConfig(timezone_offset="+0200")
        client = CASClient(config)
        assert client._config.timezone_offset == "+0200"

    def test_generate_fingerprint(self):
        fp = CASClient._generate_fingerprint("xStation5/2.94.1 (Linux x86_64)")
        expected = hashlib.sha256(b"xStation5/2.94.1 (Linux x86_64)").hexdigest().upper()
        assert fp == expected
        assert len(fp) == 64

    def test_get_timezone_offset_format(self):
        """Timezone offset should be minutes as a string (e.g. '60', '-300')."""
        offset = CASClient._get_timezone_offset()
        int_val = int(offset)
        assert -720 <= int_val <= 840

    def test_is_tgt_valid_success(self):
        client = CASClient()
        result = CASLoginSuccess(tgt="TGT-123", expires_at=time.time() + 3600)
        assert client.is_tgt_valid(result) is True

    def test_is_tgt_valid_expired(self):
        client = CASClient()
        result = CASLoginSuccess(tgt="TGT-123", expires_at=time.time() - 3600)
        assert client.is_tgt_valid(result) is False

    def test_get_tgt_from_result_success(self):
        client = CASClient()
        result = CASLoginSuccess(tgt="TGT-123-abc", expires_at=time.time() + 3600)
        assert client.get_tgt_from_result(result) == "TGT-123-abc"

    def test_get_tgt_from_result_2fa(self):
        client = CASClient()
        result = CASLoginTwoFactorRequired(
            login_ticket="MID-123--abc",
            session_id="sess-123",
            methods=["TOTP"],
            expires_at=time.time() + 300,
        )
        assert client.get_tgt_from_result(result) is None

    @pytest.mark.asyncio
    async def test_login_v2_success(self):
        client = CASClient()

        mock_resp = httpx.Response(
            200,
            json={"loginPhase": "TGT_CREATED", "ticket": "TGT-12345-abcdef"},
            request=httpx.Request("POST", "https://example.com"),
        )

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.is_closed = False

        with patch("xtb_api.auth.cas_client.httpx.AsyncClient", return_value=mock_client):
            result = await client._login_v2("test@example.com", "password123")

        assert isinstance(result, CASLoginSuccess)
        assert result.tgt == "TGT-12345-abcdef"
        assert result.expires_at > time.time()

    @pytest.mark.asyncio
    async def test_login_v2_requires_2fa(self):
        client = CASClient()

        mock_resp = httpx.Response(
            200,
            json={
                "loginPhase": "TWO_FACTOR_REQUIRED",
                "loginTicket": "MID-103490--WTXBAs-zX7JSOBuAF0tVCsDJ6cHIvZQ",
                "sessionId": "sess-abc-123",
                "methods": ["TOTP", "SMS"],
            },
            request=httpx.Request("POST", "https://example.com"),
        )

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.is_closed = False

        with patch("xtb_api.auth.cas_client.httpx.AsyncClient", return_value=mock_client):
            result = await client._login_v2("test@example.com", "password123")

        assert isinstance(result, CASLoginTwoFactorRequired)
        assert result.login_ticket == "MID-103490--WTXBAs-zX7JSOBuAF0tVCsDJ6cHIvZQ"
        assert result.session_id == "sess-abc-123"
        assert "TOTP" in result.methods
        assert "SMS" in result.methods

    @pytest.mark.asyncio
    async def test_login_v2_requires_2fa_no_session_id(self):
        """When server only returns loginTicket (no sessionId), it should still work."""
        client = CASClient()

        mock_resp = httpx.Response(
            200,
            json={
                "loginPhase": "TWO_FACTOR_REQUIRED",
                "loginTicket": "MID-103490--WTXBAs-abc123",
            },
            request=httpx.Request("POST", "https://example.com"),
        )

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.is_closed = False

        with patch("xtb_api.auth.cas_client.httpx.AsyncClient", return_value=mock_client):
            result = await client._login_v2("test@example.com", "password123")

        assert isinstance(result, CASLoginTwoFactorRequired)
        assert result.login_ticket == "MID-103490--WTXBAs-abc123"
        assert result.session_id == "MID-103490--WTXBAs-abc123"  # fallback

    @pytest.mark.asyncio
    async def test_login_v2_unauthorized(self):
        client = CASClient()

        mock_resp = httpx.Response(
            401,
            text="Unauthorized",
            request=httpx.Request("POST", "https://example.com"),
        )

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.is_closed = False

        with (
            patch("xtb_api.auth.cas_client.httpx.AsyncClient", return_value=mock_client),
            pytest.raises(CASError) as exc_info,
        ):
            await client._login_v2("wrong@example.com", "wrongpassword")

        assert exc_info.value.code == "CAS_GET_TGT_UNAUTHORIZED"

    @pytest.mark.asyncio
    async def test_get_service_ticket_success(self):
        client = CASClient()

        mock_resp = httpx.Response(
            200,
            text="ST-12345-abcdef",
            request=httpx.Request("POST", "https://example.com"),
        )

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.is_closed = False

        with patch("xtb_api.auth.cas_client.httpx.AsyncClient", return_value=mock_client):
            result = await client.get_service_ticket("TGT-xxx", "xapi5")

        assert result.service_ticket == "ST-12345-abcdef"
        assert result.service == "xapi5"

    @pytest.mark.asyncio
    async def test_get_service_ticket_expired_tgt(self):
        client = CASClient()

        mock_resp = httpx.Response(
            401,
            text="Unauthorized",
            request=httpx.Request("POST", "https://example.com"),
        )

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.is_closed = False

        with (
            patch("xtb_api.auth.cas_client.httpx.AsyncClient", return_value=mock_client),
            pytest.raises(CASError) as exc_info,
        ):
            await client.get_service_ticket("TGT-expired", "xapi5")

        assert exc_info.value.code == "CAS_TGT_EXPIRED"

    @pytest.mark.asyncio
    async def test_get_service_ticket_invalid_response(self):
        client = CASClient()

        mock_resp = httpx.Response(
            200,
            text="INVALID-TICKET",
            request=httpx.Request("POST", "https://example.com"),
        )

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.is_closed = False

        with (
            patch("xtb_api.auth.cas_client.httpx.AsyncClient", return_value=mock_client),
            pytest.raises(CASError) as exc_info,
        ):
            await client.get_service_ticket("TGT-xxx", "xapi5")

        assert exc_info.value.code == "CAS_INVALID_SERVICE_TICKET"

    @pytest.mark.asyncio
    async def test_login_with_two_factor_success(self):
        """2FA submission should POST to v2/tickets with loginTicket payload."""
        client = CASClient()

        mock_resp = httpx.Response(
            200,
            json={
                "loginPhase": "TGT_CREATED",
                "ticket": "TGT-1272906-WIAQgUAiVFSMHGI0jGxYhwU1RU10MGFf9pNprXtwwU",
            },
            headers={"Set-Cookie": ""},
            request=httpx.Request("POST", "https://example.com"),
        )

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.is_closed = False

        with patch("xtb_api.auth.cas_client.httpx.AsyncClient", return_value=mock_client):
            result = await client.login_with_two_factor(
                "MID-103490--WTXBAs-zX7JSOBuAF0tVCsDJ6cHIvZQ",
                "654321",
            )

        assert isinstance(result, CASLoginSuccess)
        assert result.tgt == "TGT-1272906-WIAQgUAiVFSMHGI0jGxYhwU1RU10MGFf9pNprXtwwU"

        # Verify the correct URL and payload were used
        call_args = mock_client.post.call_args
        assert "v2/tickets" in str(call_args)
        payload = call_args[1]["json"]
        assert payload["loginTicket"] == "MID-103490--WTXBAs-zX7JSOBuAF0tVCsDJ6cHIvZQ"
        assert payload["token"] == "654321"
        assert payload["twoFactorAuthType"] == "SMS"
        assert "fingerprint" in payload

    @pytest.mark.asyncio
    async def test_login_with_two_factor_tgt_from_cookie(self):
        """Should extract TGT from Set-Cookie header if not in JSON body."""
        client = CASClient()

        mock_resp = httpx.Response(
            200,
            json={"loginPhase": "TGT_CREATED"},
            headers={"Set-Cookie": "CASTGT=TGT-999-fromcookie; Path=/; HttpOnly"},
            request=httpx.Request("POST", "https://example.com"),
        )

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.is_closed = False

        with patch("xtb_api.auth.cas_client.httpx.AsyncClient", return_value=mock_client):
            result = await client.login_with_two_factor("MID-123--abc", "123456")

        assert isinstance(result, CASLoginSuccess)
        assert result.tgt == "TGT-999-fromcookie"

    @pytest.mark.asyncio
    async def test_login_with_two_factor_backward_compat(self):
        """session_id kwarg should work as alias for login_ticket."""
        client = CASClient()

        mock_resp = httpx.Response(
            200,
            json={"loginPhase": "TGT_CREATED", "ticket": "TGT-compat-test"},
            headers={"Set-Cookie": ""},
            request=httpx.Request("POST", "https://example.com"),
        )

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.is_closed = False

        with patch("xtb_api.auth.cas_client.httpx.AsyncClient", return_value=mock_client):
            result = await client.login_with_two_factor("", "654321", session_id="old-session-id")

        assert isinstance(result, CASLoginSuccess)
        payload = mock_client.post.call_args[1]["json"]
        assert payload["loginTicket"] == "old-session-id"
