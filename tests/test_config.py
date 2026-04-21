"""Tests for `xtb_api.config` pure resolver functions."""

from __future__ import annotations

import pytest

from xtb_api.config import (
    PRESETS,
    resolve_account_server,
    resolve_account_type,
    resolve_ws_url,
)


class TestResolveAccountType:
    """Happy paths + precedence + normalization + error cases."""

    def test_default_is_real_when_no_kwarg_and_no_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With neither kwarg nor env var set, default to 'real'."""
        monkeypatch.delenv("XTB_ACCOUNT_TYPE", raising=False)
        assert resolve_account_type(None) == "real"

    def test_explicit_kwarg_demo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Explicit kwarg 'demo' resolves to 'demo'."""
        monkeypatch.delenv("XTB_ACCOUNT_TYPE", raising=False)
        assert resolve_account_type("demo") == "demo"

    def test_env_var_demo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """XTB_ACCOUNT_TYPE=demo env var resolves to 'demo' when no kwarg."""
        monkeypatch.setenv("XTB_ACCOUNT_TYPE", "demo")
        assert resolve_account_type(None) == "demo"

    def test_kwarg_beats_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Explicit kwarg wins over env var."""
        monkeypatch.setenv("XTB_ACCOUNT_TYPE", "demo")
        assert resolve_account_type("real") == "real"

    def test_env_var_caps_and_whitespace_normalized(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """'DEMO ' (upper + trailing space) resolves to 'demo'."""
        monkeypatch.setenv("XTB_ACCOUNT_TYPE", "DEMO ")
        assert resolve_account_type(None) == "demo"

    def test_empty_env_var_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Empty string env var is treated the same as unset."""
        monkeypatch.setenv("XTB_ACCOUNT_TYPE", "")
        assert resolve_account_type(None) == "real"

    def test_unknown_env_value_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A typo in XTB_ACCOUNT_TYPE raises ValueError naming the value."""
        monkeypatch.setenv("XTB_ACCOUNT_TYPE", "demp")
        with pytest.raises(ValueError, match="demp"):
            resolve_account_type(None)

    def test_unknown_kwarg_value_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A typo in the kwarg raises the same ValueError."""
        monkeypatch.delenv("XTB_ACCOUNT_TYPE", raising=False)
        with pytest.raises(ValueError, match="bogus"):
            resolve_account_type("bogus")  # type: ignore[arg-type]


class TestResolveWsUrl:
    """ws_url resolves via kwarg → XTB_WS_URL env → preset."""

    def test_preset_used_when_nothing_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With no kwarg and no env, fall back to the preset for the given type."""
        monkeypatch.delenv("XTB_WS_URL", raising=False)
        assert resolve_ws_url(None, "demo") == PRESETS["demo"]["ws_url"]

    def test_real_preset_used_when_nothing_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Same fallback for the real account type."""
        monkeypatch.delenv("XTB_WS_URL", raising=False)
        assert resolve_ws_url(None, "real") == PRESETS["real"]["ws_url"]

    def test_env_beats_preset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """XTB_WS_URL overrides the preset when no kwarg."""
        monkeypatch.setenv("XTB_WS_URL", "wss://staging.example.com/ws")
        assert resolve_ws_url(None, "demo") == "wss://staging.example.com/ws"

    def test_kwarg_beats_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Explicit kwarg wins over XTB_WS_URL."""
        monkeypatch.setenv("XTB_WS_URL", "wss://staging.example.com/ws")
        assert resolve_ws_url("wss://custom/", "demo") == "wss://custom/"

    def test_empty_env_falls_back_to_preset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Empty XTB_WS_URL env is treated as unset."""
        monkeypatch.setenv("XTB_WS_URL", "")
        assert resolve_ws_url(None, "demo") == PRESETS["demo"]["ws_url"]


class TestResolveAccountServer:
    """account_server resolves via kwarg → XTB_ACCOUNT_SERVER env → preset."""

    def test_preset_used_when_nothing_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With no kwarg and no env, fall back to the preset."""
        monkeypatch.delenv("XTB_ACCOUNT_SERVER", raising=False)
        assert resolve_account_server(None, "demo") == PRESETS["demo"]["account_server"]

    def test_real_preset_used_when_nothing_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Same fallback for the real account type."""
        monkeypatch.delenv("XTB_ACCOUNT_SERVER", raising=False)
        assert resolve_account_server(None, "real") == PRESETS["real"]["account_server"]

    def test_env_beats_preset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """XTB_ACCOUNT_SERVER overrides the preset when no kwarg."""
        monkeypatch.setenv("XTB_ACCOUNT_SERVER", "XS-real2")
        assert resolve_account_server(None, "demo") == "XS-real2"

    def test_kwarg_beats_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Explicit kwarg wins over XTB_ACCOUNT_SERVER."""
        monkeypatch.setenv("XTB_ACCOUNT_SERVER", "XS-real2")
        assert resolve_account_server("XS-custom", "demo") == "XS-custom"

    def test_empty_env_falls_back_to_preset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Empty XTB_ACCOUNT_SERVER env is treated as unset."""
        monkeypatch.setenv("XTB_ACCOUNT_SERVER", "")
        assert resolve_account_server(None, "demo") == PRESETS["demo"]["account_server"]


class TestXTBClientIntegration:
    """End-to-end: XTBClient(account_type=...) wires resolved values through."""

    def test_kwarg_demo_sets_account_server_and_ws_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("XTB_ACCOUNT_TYPE", raising=False)
        monkeypatch.delenv("XTB_WS_URL", raising=False)
        monkeypatch.delenv("XTB_ACCOUNT_SERVER", raising=False)

        from xtb_api import XTBClient

        client = XTBClient(
            email="a@b.c",
            password="pw",
            account_number=12345678,
            account_type="demo",
        )

        assert client._account_server == "XS-demo1"
        assert client._ws._config.url == PRESETS["demo"]["ws_url"]

    def test_env_demo_sets_account_server_and_ws_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XTB_ACCOUNT_TYPE", "demo")
        monkeypatch.delenv("XTB_WS_URL", raising=False)
        monkeypatch.delenv("XTB_ACCOUNT_SERVER", raising=False)

        from xtb_api import XTBClient

        client = XTBClient(
            email="a@b.c",
            password="pw",
            account_number=12345678,
        )

        assert client._account_server == "XS-demo1"
        assert client._ws._config.url == PRESETS["demo"]["ws_url"]

    def test_default_is_real(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("XTB_ACCOUNT_TYPE", raising=False)
        monkeypatch.delenv("XTB_WS_URL", raising=False)
        monkeypatch.delenv("XTB_ACCOUNT_SERVER", raising=False)

        from xtb_api import XTBClient

        client = XTBClient(
            email="a@b.c",
            password="pw",
            account_number=12345678,
        )

        assert client._account_server == "XS-real1"
        assert client._ws._config.url == PRESETS["real"]["ws_url"]
