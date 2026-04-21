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

    def test_kwarg_beats_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Explicit kwarg wins over env var."""
        monkeypatch.setenv("XTB_ACCOUNT_TYPE", "demo")
        assert resolve_account_type("real") == "real"

    def test_env_var_caps_and_whitespace_normalized(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """'DEMO ' (upper + trailing space) resolves to 'demo'."""
        monkeypatch.setenv("XTB_ACCOUNT_TYPE", "DEMO ")
        assert resolve_account_type(None) == "demo"

    def test_empty_env_var_falls_back_to_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Empty string env var is treated the same as unset."""
        monkeypatch.setenv("XTB_ACCOUNT_TYPE", "")
        assert resolve_account_type(None) == "real"

    def test_unknown_env_value_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A typo in XTB_ACCOUNT_TYPE raises ValueError naming the value."""
        monkeypatch.setenv("XTB_ACCOUNT_TYPE", "demp")
        with pytest.raises(ValueError, match="demp"):
            resolve_account_type(None)

    def test_unknown_kwarg_value_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A typo in the kwarg raises the same ValueError."""
        monkeypatch.delenv("XTB_ACCOUNT_TYPE", raising=False)
        with pytest.raises(ValueError, match="bogus"):
            resolve_account_type("bogus")  # type: ignore[arg-type]
