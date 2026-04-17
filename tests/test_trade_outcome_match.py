"""Consumer-shape smoke test: TradeOutcome + error_code replace the string-match pattern.

This mirrors the shape of the xtb-investor-pro broker adapter after the
v1.0 migration — it is intentionally close to example code in the spec's
§12 migration guide.
"""

from __future__ import annotations

from xtb_api import AmbiguousOutcomeError, TradeOutcome, TradeResult


def _classify(result: TradeResult) -> str:
    """Example downstream classification using only typed fields."""
    match result.status:
        case TradeOutcome.FILLED:
            return f"filled:{result.order_id}"
        case TradeOutcome.INSUFFICIENT_VOLUME:
            return "skipped:volume-too-small"
        case TradeOutcome.AMBIGUOUS:
            return "ambiguous:reconcile-next-cycle"
        case TradeOutcome.AUTH_EXPIRED:
            return "auth-expired:will-retry"
        case TradeOutcome.REJECTED:
            return f"rejected:{result.error_code or 'generic'}"
        case TradeOutcome.RATE_LIMITED:
            return "rate-limited"
        case TradeOutcome.TIMEOUT:
            return "timeout"


def test_classify_covers_all_outcomes() -> None:
    for outcome in TradeOutcome:
        r = TradeResult(status=outcome, symbol="X", side="buy", volume=1.0)
        label = _classify(r)
        assert label is not None


def test_ambiguous_outcome_error_is_catchable() -> None:
    """The exception form of AMBIGUOUS is still importable and typed."""
    err = AmbiguousOutcomeError("empty response")
    assert isinstance(err, AmbiguousOutcomeError)
    assert "empty response" in str(err)


def test_success_property_matches_filled_status() -> None:
    filled = TradeResult(status=TradeOutcome.FILLED, symbol="X", side="buy", volume=1.0)
    assert filled.success is True
    rejected = TradeResult(status=TradeOutcome.REJECTED, symbol="X", side="buy", volume=1.0)
    assert rejected.success is False
