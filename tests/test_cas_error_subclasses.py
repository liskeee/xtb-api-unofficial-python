"""CASError subclasses — invalid creds, account blocked, rate limited, 2FA required."""

from __future__ import annotations

import pytest

from xtb_api.exceptions import (
    AccountBlockedError,
    AuthenticationError,
    CASError,
    InvalidCredentialsError,
    RateLimitedError,
    TwoFactorRequiredError,
    XTBError,
)


class TestCASErrorSubclasses:
    @pytest.mark.parametrize(
        "cls",
        [
            InvalidCredentialsError,
            AccountBlockedError,
            RateLimitedError,
            TwoFactorRequiredError,
        ],
    )
    def test_is_cas_error(self, cls: type[CASError]) -> None:
        assert issubclass(cls, CASError)
        assert issubclass(cls, AuthenticationError)
        assert issubclass(cls, XTBError)

    def test_code_attribute_is_preserved(self) -> None:
        err = InvalidCredentialsError(
            "CAS_GET_TGT_UNAUTHORIZED", "Invalid credentials"
        )
        assert err.code == "CAS_GET_TGT_UNAUTHORIZED"
        assert str(err) == "Invalid credentials"

    def test_catch_parent_still_works(self) -> None:
        # Consumer that catches `except CASError:` must still catch all four.
        for cls in (
            InvalidCredentialsError,
            AccountBlockedError,
            RateLimitedError,
            TwoFactorRequiredError,
        ):
            err = cls("X", "msg")
            try:
                raise err
            except CASError:
                pass
            else:
                raise AssertionError(f"{cls.__name__} not caught by CASError")
