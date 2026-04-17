"""AmbiguousOutcomeError hierarchy."""

from __future__ import annotations

from xtb_api.exceptions import (
    AmbiguousOutcomeError,
    TradeError,
    XTBError,
)


class TestAmbiguousOutcomeError:
    def test_inherits_from_trade_error(self) -> None:
        assert issubclass(AmbiguousOutcomeError, TradeError)

    def test_inherits_from_xtb_error(self) -> None:
        assert issubclass(AmbiguousOutcomeError, XTBError)

    def test_caught_by_trade_error(self) -> None:
        try:
            raise AmbiguousOutcomeError("empty gRPC response")
        except TradeError as exc:
            assert "empty gRPC response" in str(exc)
        else:
            raise AssertionError("AmbiguousOutcomeError should be a TradeError")

    def test_message_preserved_verbatim(self) -> None:
        msg = "gRPC call returned empty response"
        err = AmbiguousOutcomeError(msg)
        assert str(err) == msg
