"""Tests for CAS authentication client and AuthManager."""

import asyncio
import hashlib
import time
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from xtb_api.auth.auth_manager import AuthManager
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


class TestCASClientEventLoopChange:
    """Regression test: _ensure_http must replace client after event loop changes."""

    def test_stale_client_replaced_on_loop_change(self):
        """Simulate get_tgt_sync() (asyncio.run) followed by async usage on a new loop.

        Before the fix, the httpx client created inside asyncio.run() was bound
        to the now-closed loop.  _ensure_http() would reuse it (is_closed==False)
        and the next request would raise RuntimeError('Event loop is closed').
        """
        client = CASClient()

        mock_resp = httpx.Response(
            200,
            json={"loginPhase": "TGT_CREATED", "ticket": "TGT-loop1"},
            request=httpx.Request("POST", "https://example.com"),
        )

        async def _login_on_loop(cas):
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(return_value=mock_resp)
            mock_http.is_closed = False
            with patch("xtb_api.auth.cas_client.httpx.AsyncClient", return_value=mock_http):
                await cas._ensure_http()
            return cas._http, cas._loop

        # Run on loop 1 (simulating asyncio.run inside get_tgt_sync)
        http1, loop1 = asyncio.run(_login_on_loop(client))
        assert http1 is not None
        assert loop1 is not None

        # Now run on loop 2 — client should be replaced, not reused
        async def _check_on_new_loop(cas):
            new_mock = AsyncMock()
            new_mock.is_closed = False
            with patch("xtb_api.auth.cas_client.httpx.AsyncClient", return_value=new_mock):
                await cas._ensure_http()
            return cas._http, cas._loop

        http2, loop2 = asyncio.run(_check_on_new_loop(client))
        assert loop2 is not loop1, "Loop should have changed"
        assert http2 is not http1, "Client should have been replaced for new loop"


class TestAuthManager:
    """Tests for AuthManager lifecycle."""

    def test_is_tgt_fresh(self):
        assert AuthManager._is_tgt_fresh(time.time() + 600) is True
        assert AuthManager._is_tgt_fresh(time.time() + 200) is False  # Within 5min margin
        assert AuthManager._is_tgt_fresh(time.time() - 100) is False

    @pytest.mark.asyncio
    async def test_get_tgt_returns_cached(self):
        auth = AuthManager(email="t@t.com", password="p")
        auth._cached_tgt = "TGT-cached"
        auth._cached_expires_at = time.time() + 3600

        tgt = await auth.get_tgt()
        assert tgt == "TGT-cached"

    @pytest.mark.asyncio
    async def test_get_tgt_calls_login_when_no_cache(self):
        auth = AuthManager(email="t@t.com", password="p")
        auth._login_with_fallback = AsyncMock(
            return_value=CASLoginSuccess(tgt="TGT-fresh", expires_at=time.time() + 3600)
        )

        tgt = await auth.get_tgt()
        assert tgt == "TGT-fresh"
        auth._login_with_fallback.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_service_ticket_retries_on_expired(self):
        auth = AuthManager(email="t@t.com", password="p")
        auth._cached_tgt = "TGT-old"
        auth._cached_expires_at = time.time() + 3600

        # First get_service_ticket fails with TGT expired, second succeeds
        call_count = 0

        async def mock_get_st(tgt, service):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise CASError("CAS_TGT_EXPIRED", "expired")
            from xtb_api.auth.cas_client import CASServiceTicketResult

            return CASServiceTicketResult(service_ticket="ST-new", service=service)

        auth._cas.get_service_ticket = mock_get_st
        auth._login_with_fallback = AsyncMock(
            return_value=CASLoginSuccess(tgt="TGT-refreshed", expires_at=time.time() + 3600)
        )

        st = await auth.get_service_ticket()
        assert st == "ST-new"
        assert call_count == 2

    def test_invalidate_clears_memory_cache(self):
        auth = AuthManager(email="t@t.com", password="p")
        auth._cached_tgt = "TGT-test"
        auth._cached_expires_at = time.time() + 3600

        auth.invalidate()
        assert auth._cached_tgt is None
        assert auth._cached_expires_at == 0.0

    def test_session_file_save_and_load(self, tmp_path):
        session_file = tmp_path / "session.json"
        auth = AuthManager(email="t@t.com", password="p", session_file=str(session_file))

        expires_at = time.time() + 3600
        auth._cache_tgt("TGT-saved", expires_at)

        assert session_file.exists()
        assert (session_file.stat().st_mode & 0o777) == 0o600

        loaded = auth._load_session_file()
        assert loaded is not None
        assert loaded["tgt"] == "TGT-saved"

    def test_session_file_load_expired(self, tmp_path):
        session_file = tmp_path / "session.json"
        auth = AuthManager(email="t@t.com", password="p", session_file=str(session_file))

        auth._cache_tgt("TGT-old", time.time() - 100)

        # Clear memory cache so it reads from file
        auth._cached_tgt = None
        auth._cached_expires_at = 0.0

        loaded = auth._load_session_file()
        assert loaded is None

    def test_session_file_fixes_permissions(self, tmp_path):
        session_file = tmp_path / "session.json"
        auth = AuthManager(email="t@t.com", password="p", session_file=str(session_file))

        # Save normally then make it permissive
        expires_at = time.time() + 3600
        auth._cache_tgt("TGT-test", expires_at)
        session_file.chmod(0o644)

        # Loading should fix permissions
        loaded = auth._load_session_file()
        assert loaded is not None
        assert (session_file.stat().st_mode & 0o777) == 0o600

    @pytest.mark.asyncio
    async def test_aclose_closes_cas_client(self):
        auth = AuthManager(email="t@t.com", password="p")
        auth._cas.aclose = AsyncMock()

        await auth.aclose()
        auth._cas.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_two_factor_without_secret_raises(self):
        auth = AuthManager(email="t@t.com", password="p", totp_secret="")
        challenge = CASLoginTwoFactorRequired(
            login_ticket="MID-123",
            session_id="sess",
            methods=["TOTP"],
            expires_at=time.time() + 300,
        )

        with pytest.raises(CASError) as exc_info:
            await auth._handle_two_factor(challenge)

        assert "2FA_NO_SECRET" in exc_info.value.code


def test_xtb_auth_is_alias_for_auth_manager() -> None:
    """XTBAuth should be a public alias for AuthManager."""
    from xtb_api import XTBAuth
    from xtb_api.auth.auth_manager import AuthManager
    assert XTBAuth is AuthManager
