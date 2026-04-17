"""TradeOutcome enum."""

from __future__ import annotations

import pytest

from xtb_api.types.trading import TradeOutcome, TradeResult


class TestTradeOutcomeEnum:
    def test_has_all_documented_members(self) -> None:
        members = {m.name for m in TradeOutcome}
        assert members == {
            "FILLED",
            "REJECTED",
            "AMBIGUOUS",
            "INSUFFICIENT_VOLUME",
            "AUTH_EXPIRED",
            "RATE_LIMITED",
            "TIMEOUT",
        }

    def test_values_are_strings_matching_names(self) -> None:
        # StrEnum semantics: members compare equal to their string names.
        assert TradeOutcome.FILLED == "FILLED"
        assert TradeOutcome.AMBIGUOUS == "AMBIGUOUS"

    def test_enum_is_hashable_and_stable(self) -> None:
        # Enum members are stable identities for `match` statements.
        assert TradeOutcome.FILLED is TradeOutcome("FILLED")


class TestTradeResult:
    def test_success_derived_from_status_filled(self) -> None:
        r = TradeResult(
            status=TradeOutcome.FILLED,
            symbol="CIG.PL",
            side="buy",
            volume=5.0,
            price=23.17,
            order_id="O1",
        )
        assert r.success is True

    def test_success_false_for_non_filled(self) -> None:
        assert TradeResult(status=TradeOutcome.REJECTED, symbol="X", side="buy").success is False

    def test_error_code_optional(self) -> None:
        r = TradeResult(
            status=TradeOutcome.REJECTED,
            symbol="X",
            side="sell",
            volume=1.0,
            error_code="NO_FUNDS",
        )
        assert r.error_code == "NO_FUNDS"

    def test_rejects_raw_success_kwarg(self) -> None:
        # success is a @property, not a pydantic field — constructor must
        # not accept a raw `success` kwarg.
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            TradeResult(
                success=True,  # type: ignore[call-arg]
                status=TradeOutcome.FILLED,
                symbol="X",
                side="buy",
                volume=1.0,
            )
