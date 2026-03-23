"""Tests for CAS authentication client."""

import hashlib
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from xtb_api.auth.cas_client import CASClient, CASClientConfig, CASServiceTicketResult
from xtb_api.types.websocket import CASError, CASLoginSuccess, CASLoginTwoFactorRequired


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
        offset = CASClient._get_timezone_offset()
        assert len(offset) == 5
        assert offset[0] in ("+", "-")
        assert offset[1:].isdigit()

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
            session_id="sess-123", methods=["TOTP"], expires_at=time.time() + 300
        )
        assert client.get_tgt_from_result(result) is None

    @pytest.mark.asyncio
    async def test_login_v2_success(self):
        client = CASClient()

        mock_response = AsyncMock()
        mock_response.ok = True
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            "loginPhase": "TGT_CREATED",
            "ticket": "TGT-12345-abcdef",
        })

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=AsyncContextManager(mock_response))

        with patch("aiohttp.ClientSession", return_value=AsyncContextManager(mock_session)):
            result = await client._login_v2("test@example.com", "password123")

        assert isinstance(result, CASLoginSuccess)
        assert result.tgt == "TGT-12345-abcdef"
        assert result.expires_at > time.time()

    @pytest.mark.asyncio
    async def test_login_v2_requires_2fa(self):
        client = CASClient()

        mock_response = AsyncMock()
        mock_response.ok = True
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            "loginPhase": "TWO_FACTOR_REQUIRED",
            "sessionId": "sess-abc-123",
            "methods": ["TOTP", "SMS"],
        })

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=AsyncContextManager(mock_response))

        with patch("aiohttp.ClientSession", return_value=AsyncContextManager(mock_session)):
            result = await client._login_v2("test@example.com", "password123")

        assert isinstance(result, CASLoginTwoFactorRequired)
        assert result.session_id == "sess-abc-123"
        assert "TOTP" in result.methods
        assert "SMS" in result.methods

    @pytest.mark.asyncio
    async def test_login_v2_unauthorized(self):
        client = CASClient()

        mock_response = AsyncMock()
        mock_response.ok = False
        mock_response.status = 401
        mock_response.text = AsyncMock(return_value="Unauthorized")

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=AsyncContextManager(mock_response))

        with patch("aiohttp.ClientSession", return_value=AsyncContextManager(mock_session)):
            with pytest.raises(CASError) as exc_info:
                await client._login_v2("wrong@example.com", "wrongpassword")

        assert exc_info.value.code == "CAS_GET_TGT_UNAUTHORIZED"

    @pytest.mark.asyncio
    async def test_get_service_ticket_success(self):
        client = CASClient()

        mock_response = AsyncMock()
        mock_response.ok = True
        mock_response.status = 200
        mock_response.text = AsyncMock(return_value="ST-12345-abcdef")

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=AsyncContextManager(mock_response))

        with patch("aiohttp.ClientSession", return_value=AsyncContextManager(mock_session)):
            result = await client.get_service_ticket("TGT-xxx", "xapi5")

        assert result.service_ticket == "ST-12345-abcdef"
        assert result.service == "xapi5"

    @pytest.mark.asyncio
    async def test_get_service_ticket_expired_tgt(self):
        client = CASClient()

        mock_response = AsyncMock()
        mock_response.ok = False
        mock_response.status = 401
        mock_response.text = AsyncMock(return_value="Unauthorized")

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=AsyncContextManager(mock_response))

        with patch("aiohttp.ClientSession", return_value=AsyncContextManager(mock_session)):
            with pytest.raises(CASError) as exc_info:
                await client.get_service_ticket("TGT-expired", "xapi5")

        assert exc_info.value.code == "CAS_TGT_EXPIRED"

    @pytest.mark.asyncio
    async def test_get_service_ticket_invalid_response(self):
        client = CASClient()

        mock_response = AsyncMock()
        mock_response.ok = True
        mock_response.status = 200
        mock_response.text = AsyncMock(return_value="INVALID-TICKET")

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=AsyncContextManager(mock_response))

        with patch("aiohttp.ClientSession", return_value=AsyncContextManager(mock_session)):
            with pytest.raises(CASError) as exc_info:
                await client.get_service_ticket("TGT-xxx", "xapi5")

        assert exc_info.value.code == "CAS_INVALID_SERVICE_TICKET"


class AsyncContextManager:
    """Helper for mocking async context managers."""

    def __init__(self, return_value):
        self._return_value = return_value

    async def __aenter__(self):
        return self._return_value

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return False
