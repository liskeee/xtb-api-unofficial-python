"""Tests for CAS cookie persistence (commit 7c5d978).

Covers save/load lifecycle, permissions, auto-derivation from session_file,
corrupt file handling, and cookie merge behavior.
"""

import json
import os
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from xtb_api.auth.auth_manager import AuthManager
from xtb_api.auth.cas_client import CASClient, CASClientConfig


class TestCookiesSavedAfterLogin:
    """Cookies should be saved to disk after a successful login."""

    @pytest.mark.asyncio
    async def test_cookies_saved_after_successful_login(self, tmp_path):
        cookies_file = tmp_path / "cookies.json"
        config = CASClientConfig(cookies_file=str(cookies_file))
        client = CASClient(config)

        mock_resp = httpx.Response(
            200,
            json={"loginPhase": "TGT_CREATED", "ticket": "TGT-test"},
            request=httpx.Request("POST", "https://example.com"),
            headers={"Set-Cookie": "CASTGC=TGT-test; Path=/; HttpOnly"},
        )

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        mock_http.is_closed = False
        # Simulate a cookie jar with a cookie after the response
        cookie_jar = httpx.Cookies()
        cookie_jar.set("CASTGC", "TGT-test")
        cookie_jar.set("device_fp", "abc123")
        mock_http.cookies = cookie_jar

        with patch("xtb_api.auth.cas_client.httpx.AsyncClient", return_value=mock_http):
            await client._login_v2("user@test.com", "pass")

        assert cookies_file.exists()
        # Check permissions are 0600
        file_mode = cookies_file.stat().st_mode & 0o777
        assert file_mode == 0o600, f"Expected 0600, got {oct(file_mode)}"

        data = json.loads(cookies_file.read_text())
        assert data["CASTGC"] == "TGT-test"
        assert data["device_fp"] == "abc123"


class TestCookiesLoadedOnInit:
    """Pre-existing cookies should be loaded into new httpx clients."""

    @pytest.mark.asyncio
    async def test_cookies_loaded_on_client_init(self, tmp_path):
        cookies_file = tmp_path / "cookies.json"
        # Pre-create a cookies file
        cookies_data = {"CASTGC": "TGT-persisted", "device_fp": "xyz789"}
        fd = os.open(str(cookies_file), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, json.dumps(cookies_data).encode())
        finally:
            os.close(fd)

        config = CASClientConfig(cookies_file=str(cookies_file))
        client = CASClient(config)

        # Capture what cookies are passed to AsyncClient
        created_cookies = {}

        class MockAsyncClient(httpx.AsyncClient):
            def __init__(self, **kwargs):
                nonlocal created_cookies
                created_cookies = kwargs.get("cookies", {})
                super().__init__(**kwargs)

        with patch("xtb_api.auth.cas_client.httpx.AsyncClient", MockAsyncClient):
            await client._ensure_http()

        assert created_cookies.get("CASTGC") == "TGT-persisted"
        assert created_cookies.get("device_fp") == "xyz789"

        # Cleanup
        if client._http and not client._http.is_closed:
            await client._http.aclose()


class TestCookiesAutoDerived:
    """AuthManager should auto-derive cookies_file from session_file."""

    def test_cookies_auto_derived_from_session_file(self, tmp_path):
        session_file = tmp_path / "xtb_session.json"
        auth = AuthManager(email="a@b.com", password="pw", session_file=str(session_file))

        expected_cookies = tmp_path / "xtb_session_cookies.json"
        assert auth._cas._cookies_path == expected_cookies


class TestCorruptCookiesFile:
    """Malformed cookies file should not crash — return empty dict."""

    def test_corrupt_cookies_file_graceful(self, tmp_path):
        cookies_file = tmp_path / "cookies.json"
        cookies_file.write_text("not valid json{{{")

        config = CASClientConfig(cookies_file=str(cookies_file))
        client = CASClient(config)

        loaded = client._load_cookies()
        assert loaded == {}

    def test_empty_cookies_file_graceful(self, tmp_path):
        cookies_file = tmp_path / "cookies.json"
        cookies_file.write_text("")

        config = CASClientConfig(cookies_file=str(cookies_file))
        client = CASClient(config)

        loaded = client._load_cookies()
        assert loaded == {}

    def test_non_dict_json_graceful(self, tmp_path):
        cookies_file = tmp_path / "cookies.json"
        cookies_file.write_text('["not", "a", "dict"]')

        config = CASClientConfig(cookies_file=str(cookies_file))
        client = CASClient(config)

        loaded = client._load_cookies()
        assert loaded == {}


class TestCookieMerge:
    """Subsequent logins should merge cookies, not overwrite."""

    @pytest.mark.asyncio
    async def test_cookie_merge_on_subsequent_login(self, tmp_path):
        cookies_file = tmp_path / "cookies.json"
        # Pre-create cookies with an existing key
        existing = {"old_cookie": "keep_me", "CASTGC": "old-tgt"}
        fd = os.open(str(cookies_file), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, json.dumps(existing).encode())
        finally:
            os.close(fd)

        config = CASClientConfig(cookies_file=str(cookies_file))
        client = CASClient(config)

        # Simulate a login that sets a new CASTGC
        mock_resp = httpx.Response(
            200,
            json={"loginPhase": "TGT_CREATED", "ticket": "TGT-new"},
            request=httpx.Request("POST", "https://example.com"),
        )

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        mock_http.is_closed = False
        cookie_jar = httpx.Cookies()
        cookie_jar.set("CASTGC", "TGT-new")
        mock_http.cookies = cookie_jar

        with patch("xtb_api.auth.cas_client.httpx.AsyncClient", return_value=mock_http):
            await client._login_v2("user@test.com", "pass")

        data = json.loads(cookies_file.read_text())
        assert data["CASTGC"] == "TGT-new", "New cookie should override old"
        assert data["old_cookie"] == "keep_me", "Existing cookies should be preserved"


class TestCookiesFilePermissions:
    """Cookie file must always be written with 0600 permissions."""

    def test_cookies_file_permissions_0600(self, tmp_path):
        cookies_file = tmp_path / "cookies.json"
        config = CASClientConfig(cookies_file=str(cookies_file))
        client = CASClient(config)

        # Simulate saving by calling _save_cookies directly
        mock_http = AsyncMock()
        cookie_jar = httpx.Cookies()
        cookie_jar.set("test", "value")
        mock_http.cookies = cookie_jar

        client._save_cookies(mock_http)

        assert cookies_file.exists()
        file_mode = cookies_file.stat().st_mode & 0o777
        assert file_mode == 0o600


class TestCookiesLoadedWhenSessionExpired:
    """Cookies should be loaded even when session/TGT is expired.

    Unlike the TGT which has an 8-hour lifetime, HTTP cookies like
    CASTGC and device fingerprint may still be valid and help avoid
    "new device" emails from XTB.
    """

    @pytest.mark.asyncio
    async def test_cookies_loaded_even_when_session_expired(self, tmp_path):
        cookies_file = tmp_path / "cookies.json"
        cookies_data = {"CASTGC": "TGT-expired-but-cookie-valid", "device_fp": "known_device"}
        fd = os.open(str(cookies_file), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, json.dumps(cookies_data).encode())
        finally:
            os.close(fd)

        config = CASClientConfig(cookies_file=str(cookies_file))
        client = CASClient(config)

        # _load_cookies is independent of TGT validity — it always loads
        loaded = client._load_cookies()
        assert loaded["CASTGC"] == "TGT-expired-but-cookie-valid"
        assert loaded["device_fp"] == "known_device"

        # And _ensure_http should pass them to the new client
        created_cookies = {}

        class MockAsyncClient(httpx.AsyncClient):
            def __init__(self, **kwargs):
                nonlocal created_cookies
                created_cookies = kwargs.get("cookies", {})
                super().__init__(**kwargs)

        with patch("xtb_api.auth.cas_client.httpx.AsyncClient", MockAsyncClient):
            await client._ensure_http()

        assert created_cookies.get("device_fp") == "known_device"

        if client._http and not client._http.is_closed:
            await client._http.aclose()
