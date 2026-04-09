"""Tests for the exception hierarchy."""

from xtb_api.exceptions import (
    AuthenticationError,
    CASError,
    InstrumentNotFoundError,
    ProtocolError,
    RateLimitError,
    ReconnectionError,
    TradeError,
    XTBConnectionError,
    XTBError,
    XTBTimeoutError,
)


class TestExceptionHierarchy:
    """Verify exception inheritance chain."""

    def test_all_inherit_from_xtb_error(self) -> None:
        for exc_cls in (
            XTBConnectionError,
            AuthenticationError,
            CASError,
            ReconnectionError,
            TradeError,
            InstrumentNotFoundError,
            RateLimitError,
            XTBTimeoutError,
            ProtocolError,
        ):
            assert issubclass(exc_cls, XTBError)

    def test_connection_hierarchy(self) -> None:
        assert issubclass(AuthenticationError, XTBConnectionError)
        assert issubclass(CASError, AuthenticationError)
        assert issubclass(ReconnectionError, XTBConnectionError)

    def test_trade_hierarchy(self) -> None:
        assert issubclass(InstrumentNotFoundError, TradeError)
        assert issubclass(TradeError, XTBError)

    def test_cas_error_has_code(self) -> None:
        err = CASError("CAS_GET_TGT_UNAUTHORIZED", "Invalid credentials")
        assert err.code == "CAS_GET_TGT_UNAUTHORIZED"
        assert str(err) == "Invalid credentials"

    def test_cas_error_caught_by_authentication_error(self) -> None:
        err = CASError("CAS_TGT_EXPIRED", "TGT expired")
        caught = False
        try:
            raise err
        except AuthenticationError:
            caught = True
        assert caught

    def test_cas_error_caught_by_xtb_error(self) -> None:
        err = CASError("TEST", "test")
        caught = False
        try:
            raise err
        except XTBError:
            caught = True
        assert caught

    def test_backward_compat_import_from_websocket(self) -> None:
        """CASError is still importable from types.websocket."""
        from xtb_api.types.websocket import CASError as WebsocketCASError

        assert WebsocketCASError is CASError

    def test_backward_compat_import_from_top_level(self) -> None:
        """CASError is importable from xtb_api."""
        from xtb_api import CASError as TopLevelCASError

        assert TopLevelCASError is CASError
