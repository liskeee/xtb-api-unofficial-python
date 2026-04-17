"""TradeOutcome enum."""

from __future__ import annotations

from xtb_api.types.trading import TradeOutcome


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
