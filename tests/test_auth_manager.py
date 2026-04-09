"""Tests for AuthManager high-level auth flow."""

import json
import time
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from xtb_api.auth.auth_manager import AuthManager
from xtb_api.types.websocket import CASError, CASLoginSuccess, CASLoginTwoFactorRequired

# -- Helpers --


def _make_success(tgt: str = "TGT-test-abc", hours: float = 8) -> CASLoginSuccess:
    return CASLoginSuccess(tgt=tgt, expires_at=time.time() + hours * 3600)


def _make_2fa(methods: list[str] | None = None) -> CASLoginTwoFactorRequired:
    return CASLoginTwoFactorRequired(
        login_ticket="MID-123--abc",
        session_id="MID-123--abc",
        methods=methods or ["TOTP"],
        expires_at=time.time() + 300,
    )


class TestAuthManagerInit:
    def test_basic_init(self):
        mgr = AuthManager(email="a@b.com", password="pw")
        assert mgr._email == "a@b.com"
        assert mgr._totp_secret == ""
        assert mgr._session_file is None

    def test_session_file_expanded(self, tmp_path):
        mgr = AuthManager("a@b.com", "pw", session_file=tmp_path / "session.json")
        assert mgr._session_file == tmp_path / "session.json"

    def test_totp_secret_stored(self):
        mgr = AuthManager("a@b.com", "pw", totp_secret="BASE32SECRET")
        assert mgr._totp_secret == "BASE32SECRET"


class TestGetTgt:
    @pytest.mark.asyncio
    async def test_returns_cached_in_memory(self):
        mgr = AuthManager("a@b.com", "pw")
        mgr._cached_tgt = "TGT-cached"
        mgr._cached_expires_at = time.time() + 3600

        tgt = await mgr.get_tgt()
        assert tgt == "TGT-cached"

    @pytest.mark.asyncio
    async def test_skips_expired_memory_cache(self):
        mgr = AuthManager("a@b.com", "pw")
        mgr._cached_tgt = "TGT-expired"
        mgr._cached_expires_at = time.time() - 100

        with patch.object(mgr, "_login_with_fallback", new_callable=AsyncMock) as mock_login:
            mock_login.return_value = _make_success("TGT-fresh")
            tgt = await mgr.get_tgt()

        assert tgt == "TGT-fresh"

    @pytest.mark.asyncio
    async def test_loads_from_session_file(self, tmp_path):
        session_file = tmp_path / "session.json"
        expires_at = datetime.fromtimestamp(time.time() + 3600, tz=UTC)
        session_file.write_text(
            json.dumps(
                {
                    "tgt": "TGT-from-file",
                    "extracted_at": datetime.now(UTC).isoformat(),
                    "expires_at": expires_at.isoformat(),
                }
            )
        )

        mgr = AuthManager("a@b.com", "pw", session_file=session_file)
        tgt = await mgr.get_tgt()
        assert tgt == "TGT-from-file"

    @pytest.mark.asyncio
    async def test_skips_expired_session_file(self, tmp_path):
        session_file = tmp_path / "session.json"
        expires_at = datetime.fromtimestamp(time.time() - 100, tz=UTC)
        session_file.write_text(
            json.dumps(
                {
                    "tgt": "TGT-old",
                    "extracted_at": datetime.now(UTC).isoformat(),
                    "expires_at": expires_at.isoformat(),
                }
            )
        )

        mgr = AuthManager("a@b.com", "pw", session_file=session_file)
        with patch.object(mgr, "_login_with_fallback", new_callable=AsyncMock) as mock_login:
            mock_login.return_value = _make_success("TGT-new")
            tgt = await mgr.get_tgt()

        assert tgt == "TGT-new"

    @pytest.mark.asyncio
    async def test_rest_login_success(self):
        mgr = AuthManager("a@b.com", "pw")
        with patch.object(mgr._cas, "login", new_callable=AsyncMock) as mock_login:
            mock_login.return_value = _make_success("TGT-rest")
            tgt = await mgr.get_tgt()

        assert tgt == "TGT-rest"
        assert mgr._cached_tgt == "TGT-rest"

    @pytest.mark.asyncio
    async def test_saves_to_session_file(self, tmp_path):
        session_file = tmp_path / "session.json"
        mgr = AuthManager("a@b.com", "pw", session_file=session_file)

        with patch.object(mgr._cas, "login", new_callable=AsyncMock) as mock_login:
            mock_login.return_value = _make_success("TGT-saved")
            await mgr.get_tgt()

        assert session_file.exists()
        data = json.loads(session_file.read_text())
        assert data["tgt"] == "TGT-saved"
        assert "extracted_at" in data
        assert "expires_at" in data


class TestBrowserFallback:
    @pytest.mark.asyncio
    async def test_falls_back_to_browser_on_waf_block(self):
        mgr = AuthManager("a@b.com", "pw")

        with (
            patch.object(mgr._cas, "login", new_callable=AsyncMock) as mock_rest,
            patch.object(mgr._cas, "login_with_browser", new_callable=AsyncMock) as mock_browser,
        ):
            mock_rest.side_effect = CASError("CAS_LOGIN_FAILED", "WAF blocked")
            mock_browser.return_value = _make_success("TGT-browser")

            tgt = await mgr.get_tgt()

        assert tgt == "TGT-browser"
        mock_browser.assert_called_once()

    @pytest.mark.asyncio
    async def test_does_not_fallback_on_unauthorized(self):
        mgr = AuthManager("a@b.com", "pw")

        with patch.object(mgr._cas, "login", new_callable=AsyncMock) as mock_rest:
            mock_rest.side_effect = CASError("CAS_GET_TGT_UNAUTHORIZED", "Bad creds")

            with pytest.raises(CASError) as exc_info:
                await mgr.get_tgt()

        assert exc_info.value.code == "CAS_GET_TGT_UNAUTHORIZED"


class TestTwoFactor:
    @pytest.mark.asyncio
    async def test_auto_totp(self):
        mgr = AuthManager("a@b.com", "pw", totp_secret="JBSWY3DPEHPK3PXP")

        mock_pyotp_totp = MagicMock()
        mock_pyotp_totp.now.return_value = "123456"
        mock_pyotp_module = MagicMock()
        mock_pyotp_module.TOTP.return_value = mock_pyotp_totp

        with (
            patch.object(mgr._cas, "login", new_callable=AsyncMock) as mock_login,
            patch.object(mgr._cas, "login_with_two_factor", new_callable=AsyncMock) as mock_2fa,
            patch.dict("sys.modules", {"pyotp": mock_pyotp_module}),
        ):
            mock_login.return_value = _make_2fa()
            mock_2fa.return_value = _make_success("TGT-2fa")

            tgt = await mgr.get_tgt()

        assert tgt == "TGT-2fa"
        mock_2fa.assert_called_once()
        call_args = mock_2fa.call_args
        assert call_args[0][1] == "123456"

    @pytest.mark.asyncio
    async def test_raises_when_no_totp_secret(self):
        mgr = AuthManager("a@b.com", "pw")  # no totp_secret

        with patch.object(mgr._cas, "login", new_callable=AsyncMock) as mock_login:
            mock_login.return_value = _make_2fa()

            with pytest.raises(CASError) as exc_info:
                await mgr.get_tgt()

        assert exc_info.value.code == "AUTH_MANAGER_2FA_NO_SECRET"

    @pytest.mark.asyncio
    async def test_raises_when_pyotp_missing(self):
        mgr = AuthManager("a@b.com", "pw", totp_secret="SECRET")

        with (
            patch.object(mgr._cas, "login", new_callable=AsyncMock) as mock_login,
            patch.dict("sys.modules", {"pyotp": None}),
        ):
            mock_login.return_value = _make_2fa()

            with pytest.raises(CASError) as exc_info:
                await mgr.get_tgt()

        assert exc_info.value.code == "AUTH_MANAGER_PYOTP_MISSING"


class TestGetServiceTicket:
    @pytest.mark.asyncio
    async def test_gets_service_ticket(self):
        mgr = AuthManager("a@b.com", "pw")
        mgr._cached_tgt = "TGT-valid"
        mgr._cached_expires_at = time.time() + 3600

        mock_st = MagicMock()
        mock_st.service_ticket = "ST-12345"
        with patch.object(mgr._cas, "get_service_ticket", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_st
            st = await mgr.get_service_ticket()

        assert st == "ST-12345"

    @pytest.mark.asyncio
    async def test_retries_on_expired_tgt(self):
        mgr = AuthManager("a@b.com", "pw")
        mgr._cached_tgt = "TGT-stale"
        mgr._cached_expires_at = time.time() + 3600

        mock_st = MagicMock()
        mock_st.service_ticket = "ST-fresh"

        call_count = 0

        async def mock_get_st(tgt, service):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise CASError("CAS_TGT_EXPIRED", "expired")
            return mock_st

        with (
            patch.object(mgr._cas, "get_service_ticket", side_effect=mock_get_st),
            patch.object(mgr._cas, "login", new_callable=AsyncMock) as mock_login,
        ):
            mock_login.return_value = _make_success("TGT-renewed")
            st = await mgr.get_service_ticket()

        assert st == "ST-fresh"
        assert call_count == 2


class TestSyncWrapper:
    def test_get_tgt_sync(self):
        mgr = AuthManager("a@b.com", "pw")
        mgr._cached_tgt = "TGT-sync"
        mgr._cached_expires_at = time.time() + 3600

        tgt = mgr.get_tgt_sync()
        assert tgt == "TGT-sync"


class TestInvalidate:
    def test_clears_memory_cache(self):
        mgr = AuthManager("a@b.com", "pw")
        mgr._cached_tgt = "TGT-x"
        mgr._cached_expires_at = time.time() + 3600

        mgr.invalidate()
        assert mgr._cached_tgt is None
        assert mgr._cached_expires_at == 0.0

    def test_deletes_session_file(self, tmp_path):
        session_file = tmp_path / "session.json"
        session_file.write_text('{"tgt": "x"}')

        mgr = AuthManager("a@b.com", "pw", session_file=session_file)
        mgr.invalidate()
        assert not session_file.exists()


class TestSessionFileSafety:
    @pytest.mark.asyncio
    async def test_handles_corrupt_session_file(self, tmp_path):
        session_file = tmp_path / "session.json"
        session_file.write_text("not json{{{")

        mgr = AuthManager("a@b.com", "pw", session_file=session_file)
        with patch.object(mgr._cas, "login", new_callable=AsyncMock) as mock_login:
            mock_login.return_value = _make_success("TGT-fallback")
            tgt = await mgr.get_tgt()

        assert tgt == "TGT-fallback"

    @pytest.mark.asyncio
    async def test_creates_parent_dirs(self, tmp_path):
        session_file = tmp_path / "nested" / "deep" / "session.json"
        mgr = AuthManager("a@b.com", "pw", session_file=session_file)

        with patch.object(mgr._cas, "login", new_callable=AsyncMock) as mock_login:
            mock_login.return_value = _make_success("TGT-nested")
            await mgr.get_tgt()

        assert session_file.exists()
