"""Tests for `xtb_api.config` pure resolver functions."""

from __future__ import annotations

import pytest

from xtb_api.config import resolve_account_type


class TestResolveAccountType:
    """Happy paths + precedence + normalization + error cases."""

    def test_default_is_real_when_no_kwarg_and_no_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
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
