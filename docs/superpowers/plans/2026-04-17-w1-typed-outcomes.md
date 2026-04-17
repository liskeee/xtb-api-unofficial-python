# W1 — Typed Outcomes & Idempotent Trade Retry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `TradeResult.success: bool` + free-text `error` with a typed
`TradeOutcome` enum and optional `error_code`; introduce typed exceptions
(`AmbiguousOutcomeError`, CAS subclasses, `ProtocolError` on JSON decode);
make the JWT-refresh retry idempotent so an empty gRPC response can no longer
duplicate a filled order.

**Architecture:** Additive-then-tightening changes layered on the existing
`xtb_api` surface. New types live in `types/trading.py` and `exceptions.py`.
`grpc/client.py` stops string-matching `"RBAC"` (uses `grpc_status == 7`),
stops truncating server messages, narrows its `except Exception`, and raises
`AmbiguousOutcomeError` for empty trade responses. `client._execute_trade`
maps gRPC results to `TradeOutcome`, calls `get_positions()` before any
RBAC retry to detect already-filled orders, and distinguishes
"fill-price unknown" via `error_code="FILL_PRICE_UNKNOWN"`. `TradeResult.success`
becomes a `@property` derived from `status is TradeOutcome.FILLED`.

**Tech Stack:** Python 3.12, pydantic v2, pytest + pytest-asyncio, httpx
(mocked via `AsyncMock`). Spec reference:
`docs/superpowers/specs/2026-04-17-audit-and-roadmap-design.md` §7 and §12.

**Findings closed:** F01, F02 (P0); F13, F14, F15, F16 (P1); F18, F19, F21,
F22, F40 (P2).

---

## File structure

Files created or modified by this plan:

- **Modify** `src/xtb_api/types/trading.py` — add `TradeOutcome` enum,
  extend `TradeResult` with `status`/`error_code`, convert `success` to
  `@property`.
- **Modify** `src/xtb_api/exceptions.py` — add `AmbiguousOutcomeError`,
  `InvalidCredentialsError`, `AccountBlockedError`, `RateLimitedError`,
  `TwoFactorRequiredError`.
- **Modify** `src/xtb_api/__init__.py` — export the new symbols.
- **Modify** `src/xtb_api/grpc/client.py` — remove 200-char truncation, narrow
  `except Exception`, stop raising `ProtocolError` on empty trade response
  (let callers synthesize `AmbiguousOutcomeError`).
- **Modify** `src/xtb_api/client.py` — map gRPC results to `TradeOutcome`,
  add idempotency probe, detect RBAC via `grpc_status`, signal unknown
  fill price via `error_code`.
- **Modify** `src/xtb_api/ws/ws_client.py:773-774` — emit `ProtocolError`
  instead of `RuntimeError` on JSON decode failure.
- **Modify** `src/xtb_api/auth/cas_client.py` — dispatch raised CAS errors
  to the new subclasses keyed on `code`.
- **Create** `tests/test_trade_outcome.py` — enum + `TradeResult` tests.
- **Create** `tests/test_ambiguous_outcome_error.py` — `AmbiguousOutcomeError`
  hierarchy test.
- **Create** `tests/test_cas_error_subclasses.py` — CASError subclass tests.
- **Create** `tests/test_client_trade_outcome_mapping.py` — end-to-end
  `_execute_trade` → TradeOutcome mapping tests.
- **Create** `tests/test_client_idempotent_retry.py` — JWT-refresh retry
  idempotency tests.
- **Modify** `tests/test_exceptions.py` — assert new subclasses inherit
  correctly.
- **Modify** `tests/test_grpc_client.py` — truncation-removed test, narrowed
  exception test, empty-response semantics test.
- **Modify** `tests/test_ws_client.py` — JSON-decode emits ProtocolError.
- **Modify** `tests/test_client_fill_price.py` — assert `error_code` signals
  unknown fill price.

---

## Task 1: `TradeOutcome` enum

**Files:**
- Create: `tests/test_trade_outcome.py`
- Modify: `src/xtb_api/types/trading.py` (append after existing imports)

- [ ] **Step 1: Write the failing test**

Create `tests/test_trade_outcome.py`:

```python
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
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest tests/test_trade_outcome.py -v`
Expected: **FAIL** — `ImportError: cannot import name 'TradeOutcome'`.

- [ ] **Step 3: Implement**

Edit `src/xtb_api/types/trading.py` — add this at the top of the file
(after the existing `from __future__ import annotations` line, before
`from typing import Literal`):

```python
from enum import StrEnum
```

Then append at the end of the file (after the `TradeResult` class — leaving
`TradeResult` untouched in this task):

```python
class TradeOutcome(StrEnum):
    """Typed outcome of a trade request.

    Values:
    - ``FILLED`` — broker confirmed the order, position is open.
    - ``REJECTED`` — broker refused (bad symbol, market closed, etc.).
    - ``AMBIGUOUS`` — network or protocol failure after the send; the trade
      may or may not have been placed. Caller must reconcile via
      ``get_positions()``.
    - ``INSUFFICIENT_VOLUME`` — local pre-check: volume rounds to < 1.
    - ``AUTH_EXPIRED`` — JWT/TGT rejected (RBAC). Should be retried by the
      library; only surfaced if retry also fails.
    - ``RATE_LIMITED`` — broker throttled the request.
    - ``TIMEOUT`` — request exceeded its deadline.
    """

    FILLED = "FILLED"
    REJECTED = "REJECTED"
    AMBIGUOUS = "AMBIGUOUS"
    INSUFFICIENT_VOLUME = "INSUFFICIENT_VOLUME"
    AUTH_EXPIRED = "AUTH_EXPIRED"
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT = "TIMEOUT"
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_trade_outcome.py -v`
Expected: **PASS** (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/xtb_api/types/trading.py tests/test_trade_outcome.py
git commit -m "feat(types): add TradeOutcome enum"
```

---

## Task 2: `TradeResult` gains `status` + `error_code`, `success` becomes a property

**Files:**
- Modify: `src/xtb_api/types/trading.py` (replace the `TradeResult` class)
- Modify: `tests/test_trade_outcome.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_trade_outcome.py`:

```python
from xtb_api.types.trading import TradeResult


class TestTradeResult:
    def test_success_is_derived_from_status(self) -> None:
        r = TradeResult(
            status=TradeOutcome.FILLED,
            symbol="CIG.PL",
            side="buy",
            volume=5.0,
            price=23.17,
            order_id="O1",
        )
        assert r.success is True
        assert r.status is TradeOutcome.FILLED
        assert r.error_code is None

    def test_success_false_for_non_filled_status(self) -> None:
        for status in (
            TradeOutcome.REJECTED,
            TradeOutcome.AMBIGUOUS,
            TradeOutcome.INSUFFICIENT_VOLUME,
            TradeOutcome.AUTH_EXPIRED,
            TradeOutcome.RATE_LIMITED,
            TradeOutcome.TIMEOUT,
        ):
            r = TradeResult(
                status=status,
                symbol="X",
                side="buy",
                volume=1.0,
                error="some error",
            )
            assert r.success is False

    def test_error_code_is_optional_string(self) -> None:
        r = TradeResult(
            status=TradeOutcome.REJECTED,
            symbol="X",
            side="sell",
            volume=1.0,
            error_code="NO_FUNDS",
        )
        assert r.error_code == "NO_FUNDS"

    def test_no_success_field_assignment(self) -> None:
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
```

Add the pytest import at the top of the file if not present:
`import pytest`.

- [ ] **Step 2: Run to verify fail**

Run: `pytest tests/test_trade_outcome.py -v`
Expected: **FAIL** — `TradeResult` missing `status`/`error_code` fields.

- [ ] **Step 3: Implement**

In `src/xtb_api/types/trading.py`, replace the existing `TradeResult` class
(currently lines 130-139) with:

```python
class TradeResult(BaseModel):
    """Trade execution result.

    ``status`` is the authoritative field. ``success`` is a convenience
    property equivalent to ``status is TradeOutcome.FILLED`` and is kept
    for one-line checks.

    Fields:
        status: TradeOutcome — the typed result category.
        order_id: broker-assigned order id, if known.
        symbol: the symbol traded.
        side: "buy" or "sell".
        volume: requested volume (post-rounding for the < 1 check).
        price: fill price, if observable via a position poll.
        error: free-text error message from the broker (if any).
        error_code: stable short code for the outcome flavor. Examples:
            "INSUFFICIENT_VOLUME", "RBAC_DENIED", "AMBIGUOUS_NO_RESPONSE",
            "FILL_PRICE_UNKNOWN", "NETWORK_ERROR". May also carry the raw
            broker code when one is surfaced.
    """

    model_config = {"extra": "forbid"}

    status: TradeOutcome
    symbol: str
    side: Literal["buy", "sell"]
    volume: float | None = None
    price: float | None = None
    order_id: str | None = None
    error: str | None = None
    error_code: str | None = None

    @property
    def success(self) -> bool:
        """True iff ``status is TradeOutcome.FILLED``."""
        return self.status is TradeOutcome.FILLED
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_trade_outcome.py -v`
Expected: **PASS** (7 tests in this file).

- [ ] **Step 5: Commit**

```bash
git add src/xtb_api/types/trading.py tests/test_trade_outcome.py
git commit -m "feat(types)!: add TradeResult.status + error_code, success now derived

BREAKING: TradeResult.success is a @property, not a pydantic field.
Consumers must construct TradeResult with status=TradeOutcome.* instead
of success=bool."
```

---

## Task 3: `AmbiguousOutcomeError` exception

**Files:**
- Create: `tests/test_ambiguous_outcome_error.py`
- Modify: `src/xtb_api/exceptions.py` (append after `InstrumentNotFoundError`)

- [ ] **Step 1: Write the failing test**

Create `tests/test_ambiguous_outcome_error.py`:

```python
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
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest tests/test_ambiguous_outcome_error.py -v`
Expected: **FAIL** — `ImportError: cannot import name 'AmbiguousOutcomeError'`.

- [ ] **Step 3: Implement**

Edit `src/xtb_api/exceptions.py`. After the `InstrumentNotFoundError` class
(currently lines 43-44), add:

```python
class AmbiguousOutcomeError(TradeError):
    """The send succeeded but the broker's response did not confirm the trade.

    The order may or may not have been placed. Consumers must reconcile
    via ``get_positions()`` to determine whether the trade is live.

    Typical cause: an empty gRPC-web response body after a successful HTTP
    POST. Previously surfaced as a ``ProtocolError`` whose message had to
    be string-matched.
    """
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_ambiguous_outcome_error.py -v`
Expected: **PASS** (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/xtb_api/exceptions.py tests/test_ambiguous_outcome_error.py
git commit -m "feat(exceptions): add AmbiguousOutcomeError(TradeError)"
```

---

## Task 4: `CASError` subclasses

**Files:**
- Create: `tests/test_cas_error_subclasses.py`
- Modify: `src/xtb_api/exceptions.py` (append after the existing `CASError` class)

- [ ] **Step 1: Write the failing test**

Create `tests/test_cas_error_subclasses.py`:

```python
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
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest tests/test_cas_error_subclasses.py -v`
Expected: **FAIL** — subclasses missing from `xtb_api.exceptions`.

- [ ] **Step 3: Implement**

In `src/xtb_api/exceptions.py`, after the `CASError` class (currently
ending at line 32), add:

```python
class InvalidCredentialsError(CASError):
    """CAS rejected the email/password (HTTP 401 or CAS_GET_TGT_UNAUTHORIZED)."""


class AccountBlockedError(CASError):
    """Account temporarily blocked (too many failed OTP attempts, etc.)."""


class RateLimitedError(CASError):
    """CAS returned a throttling error (too many OTP attempts / login attempts).

    Distinct from the transport-level ``RateLimitError`` — this one is an
    authentication-flow throttle.
    """


class TwoFactorRequiredError(CASError):
    """CAS login reached the 2FA challenge and no OTP was available.

    Raised when a login requires 2FA but the ``totp_secret`` is empty and
    no browser fallback is configured.
    """
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_cas_error_subclasses.py -v`
Expected: **PASS** (6 tests).

- [ ] **Step 5: Commit**

```bash
git add src/xtb_api/exceptions.py tests/test_cas_error_subclasses.py
git commit -m "feat(exceptions): add InvalidCredentialsError, AccountBlockedError, RateLimitedError, TwoFactorRequiredError"
```

---

## Task 5: Export new public symbols

**Files:**
- Modify: `src/xtb_api/__init__.py`
- Modify: `tests/test_exceptions.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_exceptions.py`:

```python
class TestPublicExports:
    def test_trade_outcome_reexported_from_top_level(self) -> None:
        from xtb_api import TradeOutcome

        assert TradeOutcome.FILLED == "FILLED"

    def test_ambiguous_outcome_error_reexported(self) -> None:
        from xtb_api import AmbiguousOutcomeError

        from xtb_api.exceptions import TradeError

        assert issubclass(AmbiguousOutcomeError, TradeError)

    def test_cas_subclasses_reexported(self) -> None:
        from xtb_api import (
            AccountBlockedError,
            CASError,
            InvalidCredentialsError,
            RateLimitedError as CASRateLimitedError,
            TwoFactorRequiredError,
        )

        for cls in (
            InvalidCredentialsError,
            AccountBlockedError,
            CASRateLimitedError,
            TwoFactorRequiredError,
        ):
            assert issubclass(cls, CASError)
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest tests/test_exceptions.py::TestPublicExports -v`
Expected: **FAIL** — `ImportError: cannot import name 'TradeOutcome' from 'xtb_api'`.

- [ ] **Step 3: Implement**

Edit `src/xtb_api/__init__.py`. Replace the exceptions import block
(currently lines 8-19) with:

```python
from xtb_api.exceptions import (
    AccountBlockedError,
    AmbiguousOutcomeError,
    AuthenticationError,
    CASError,
    InstrumentNotFoundError,
    InvalidCredentialsError,
    ProtocolError,
    RateLimitedError,
    RateLimitError,
    ReconnectionError,
    TradeError,
    TwoFactorRequiredError,
    XTBConnectionError,
    XTBError,
    XTBTimeoutError,
)
```

Replace the trading types import block (currently lines 28-34) with:

```python
from xtb_api.types.trading import (
    AccountBalance,
    PendingOrder,
    Position,
    TradeOptions,
    TradeOutcome,
    TradeResult,
)
```

Update the `__all__` list (currently lines 41-70) — replace it with:

```python
__all__ = [
    # Client
    "XTBClient",
    "XTBAuth",
    "InstrumentRegistry",
    # Exceptions
    "XTBError",
    "XTBConnectionError",
    "AuthenticationError",
    "CASError",
    "InvalidCredentialsError",
    "AccountBlockedError",
    "RateLimitedError",
    "TwoFactorRequiredError",
    "ReconnectionError",
    "TradeError",
    "AmbiguousOutcomeError",
    "InstrumentNotFoundError",
    "RateLimitError",
    "XTBTimeoutError",
    "ProtocolError",
    # Data models
    "Position",
    "PendingOrder",
    "AccountBalance",
    "TradeResult",
    "TradeOutcome",
    "TradeOptions",
    "Quote",
    "InstrumentSearchResult",
    # Enums
    "Xs6Side",
    "SocketStatus",
    "XTBEnvironment",
    "SubscriptionEid",
]
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_exceptions.py -v`
Expected: **PASS** (all tests, including new `TestPublicExports`).

- [ ] **Step 5: Commit**

```bash
git add src/xtb_api/__init__.py tests/test_exceptions.py
git commit -m "feat(public): export TradeOutcome, AmbiguousOutcomeError, CAS subclasses"
```

---

## Task 6: JSON decode emits `ProtocolError` (F21)

**Files:**
- Modify: `src/xtb_api/ws/ws_client.py:773-774`
- Modify: `tests/test_ws_client.py` (append new test class)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ws_client.py`:

```python
class TestWsJsonDecodeEmitsProtocolError:
    """F21: JSON decode failures must surface ProtocolError, not RuntimeError."""

    def test_handle_message_emits_protocol_error_on_bad_json(self) -> None:
        from xtb_api.exceptions import ProtocolError
        from xtb_api.types.websocket import WSClientConfig
        from xtb_api.ws.ws_client import XTBWebSocketClient

        cfg = WSClientConfig(
            url="wss://test.example/x",
            account_number=1,
            endpoint="meta1",
            auto_reconnect=False,
        )
        ws = XTBWebSocketClient(cfg, auth_manager=None)

        captured: list[object] = []
        ws.on("error", lambda err: captured.append(err))

        ws._handle_message("this is not json {")

        assert len(captured) == 1
        assert isinstance(captured[0], ProtocolError)
        assert "Failed to parse message" in str(captured[0])
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest tests/test_ws_client.py::TestWsJsonDecodeEmitsProtocolError -v`
Expected: **FAIL** — captured error is a `RuntimeError`, not `ProtocolError`.

- [ ] **Step 3: Implement**

Edit `src/xtb_api/ws/ws_client.py`. Find the imports block at the top and
ensure `ProtocolError` is imported from `xtb_api.exceptions`. Check current
imports with:

```bash
grep -n "from xtb_api.exceptions" src/xtb_api/ws/ws_client.py
```

If `ProtocolError` is not already imported, add it to the existing
`from xtb_api.exceptions import ...` line. If no such line exists, add:

```python
from xtb_api.exceptions import ProtocolError
```

near the other `xtb_api.*` imports at the top of the file.

Then replace lines 773-774 (inside `_handle_message`):

```python
        except json.JSONDecodeError as e:
            self._emit("error", RuntimeError(f"Failed to parse message: {e}"))
            return
```

with:

```python
        except json.JSONDecodeError as e:
            self._emit("error", ProtocolError(f"Failed to parse message: {e}"))
            return
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_ws_client.py::TestWsJsonDecodeEmitsProtocolError -v`
Expected: **PASS** (1 test).
Run full WS suite: `pytest tests/test_ws_client.py -v`
Expected: **PASS** (no regressions).

- [ ] **Step 5: Commit**

```bash
git add src/xtb_api/ws/ws_client.py tests/test_ws_client.py
git commit -m "fix(ws): emit ProtocolError instead of RuntimeError on JSON decode failure (F21)"
```

---

## Task 7: gRPC stops truncating server error messages (F22)

**Files:**
- Modify: `src/xtb_api/grpc/client.py:318`
- Modify: `tests/test_grpc_client.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_grpc_client.py` (inside `TestParseTradeResponseSafety`
or a new class):

```python
class TestParseTradeResponsePreservesFullError:
    """F22: server error text must not be clipped to 200 chars."""

    def test_long_server_error_preserved(self) -> None:
        from xtb_api.grpc.client import GrpcClient

        client = GrpcClient(account_number="12345678")

        # Rejected trade with a long textual detail in the data frame.
        long_detail = "x" * 500
        data_payload = f"error detail: {long_detail}".encode()
        data_frame = struct.pack(">BI", 0, len(data_payload)) + data_payload
        trailers = b"grpc-status: 9\r\n"  # FAILED_PRECONDITION
        trailer_frame = struct.pack(">BI", 0x80, len(trailers)) + trailers
        response_bytes = data_frame + trailer_frame

        result = client._parse_trade_response(response_bytes)

        assert result.success is False
        assert result.error is not None
        # Full long_detail must appear in the error text — not truncated.
        assert long_detail in result.error
        assert len(result.error) > 200
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest tests/test_grpc_client.py::TestParseTradeResponsePreservesFullError -v`
Expected: **FAIL** — `len(result.error)` is ≤ ~230 (200 char clip + prefix).

- [ ] **Step 3: Implement**

Edit `src/xtb_api/grpc/client.py`. Replace line 318:

```python
            error_msg = f"gRPC order rejected: {response_text[:200]}"
```

with:

```python
            error_msg = f"gRPC order rejected: {response_text}"
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_grpc_client.py -v`
Expected: **PASS** (all tests in the file).

- [ ] **Step 5: Commit**

```bash
git add src/xtb_api/grpc/client.py tests/test_grpc_client.py
git commit -m "fix(grpc): preserve full server error text (was clipped to 200 chars) (F22)"
```

---

## Task 8: Narrow gRPC `except Exception` and preserve traceback (F19)

**Files:**
- Modify: `src/xtb_api/grpc/client.py:249-252`
- Modify: `tests/test_grpc_client.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_grpc_client.py`:

```python
class TestExecuteOrderExceptionNarrowing:
    """F19: only network/protocol errors become GrpcTradeResult; bugs must bubble."""

    @pytest.mark.asyncio
    async def test_unexpected_exception_propagates(self) -> None:
        """A ValueError (i.e. our own bug) must not be swallowed into result.error."""
        from xtb_api.grpc.client import GrpcClient

        client = GrpcClient(account_number="12345678")
        client._jwt = "valid-jwt"
        client._jwt_timestamp = time.monotonic()

        mock_http = AsyncMock()
        # Simulate an unexpected bug deep in the stack.
        mock_http.post = AsyncMock(side_effect=ValueError("boom — our bug"))
        mock_http.is_closed = False
        client._http = mock_http

        with pytest.raises(ValueError, match="boom"):
            await client.execute_order(9438, 19, SIDE_BUY)

    @pytest.mark.asyncio
    async def test_httpx_network_error_still_caught(self) -> None:
        """httpx transport errors are still converted to a failed GrpcTradeResult."""
        from xtb_api.grpc.client import GrpcClient

        client = GrpcClient(account_number="12345678")
        client._jwt = "valid-jwt"
        client._jwt_timestamp = time.monotonic()

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(side_effect=httpx.ConnectError("conn refused"))
        mock_http.is_closed = False
        client._http = mock_http

        result = await client.execute_order(9438, 19, SIDE_BUY)
        assert result.success is False
        assert "conn refused" in (result.error or "")

    @pytest.mark.asyncio
    async def test_httpx_http_status_error_caught(self) -> None:
        """httpx HTTP errors (5xx) also convert to failed result, not raise."""
        from xtb_api.grpc.client import GrpcClient

        client = GrpcClient(account_number="12345678")
        client._jwt = "valid-jwt"
        client._jwt_timestamp = time.monotonic()

        failing_resp = httpx.Response(
            500,
            text="server error",
            request=httpx.Request("POST", "https://example.com"),
        )
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=failing_resp)
        mock_http.is_closed = False
        client._http = mock_http

        result = await client.execute_order(9438, 19, SIDE_BUY)
        assert result.success is False
        assert result.error is not None
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest tests/test_grpc_client.py::TestExecuteOrderExceptionNarrowing -v`
Expected: **FAIL** on `test_unexpected_exception_propagates` — the broad
`except Exception` currently swallows the `ValueError` into
`GrpcTradeResult`.

- [ ] **Step 3: Implement**

Edit `src/xtb_api/grpc/client.py`. Replace the `try/except` block at lines
249-252:

```python
        try:
            response_bytes = await self._grpc_call(GRPC_NEW_ORDER_ENDPOINT, body_b64, jwt=jwt)
        except Exception as e:
            return GrpcTradeResult(success=False, error=str(e))
```

with:

```python
        try:
            response_bytes = await self._grpc_call(GRPC_NEW_ORDER_ENDPOINT, body_b64, jwt=jwt)
        except httpx.HTTPError as e:
            # Network / HTTP errors are surfaced as failed trades. Unexpected
            # errors (e.g. ValueError from a logic bug, AssertionError) are
            # propagated so they stop execution and hit logging with a full
            # traceback.
            logger.warning("gRPC trade network error: %s", e, exc_info=True)
            return GrpcTradeResult(success=False, error=str(e))
```

Note: `httpx.HTTPError` is the base class covering `ConnectError`,
`ReadTimeout`, `HTTPStatusError`, etc.

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_grpc_client.py -v`
Expected: **PASS** (all tests — both new and existing).

- [ ] **Step 5: Commit**

```bash
git add src/xtb_api/grpc/client.py tests/test_grpc_client.py
git commit -m "fix(grpc): narrow except Exception to httpx.HTTPError in execute_order (F19)"
```

---

## Task 9: gRPC empty trade response → `AmbiguousOutcomeError` (F01, F14)

**Files:**
- Modify: `src/xtb_api/grpc/client.py:108-112` and `src/xtb_api/grpc/client.py:249-252`
- Modify: `tests/test_grpc_client.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_grpc_client.py`:

```python
class TestGrpcEmptyResponseSemantics:
    """F01/F14: empty trade response must raise AmbiguousOutcomeError, not ProtocolError."""

    @pytest.mark.asyncio
    async def test_empty_trade_response_raises_ambiguous_outcome(self) -> None:
        from xtb_api.exceptions import AmbiguousOutcomeError
        from xtb_api.grpc.client import GrpcClient

        client = GrpcClient(account_number="12345678")
        client._jwt = "valid-jwt"
        client._jwt_timestamp = time.monotonic()

        # Empty body: HTTP 200 with resp.text == ""
        empty_resp = httpx.Response(
            200, text="", request=httpx.Request("POST", "https://example.com")
        )
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=empty_resp)
        mock_http.is_closed = False
        client._http = mock_http

        with pytest.raises(AmbiguousOutcomeError):
            await client.execute_order(9438, 19, SIDE_BUY)

    @pytest.mark.asyncio
    async def test_empty_auth_response_raises_authentication_error(self) -> None:
        """Empty response on the auth endpoint is NOT a trade-side ambiguity."""
        from xtb_api.exceptions import AmbiguousOutcomeError, AuthenticationError
        from xtb_api.grpc.client import GrpcClient

        client = GrpcClient(account_number="12345678")

        empty_resp = httpx.Response(
            200, text="", request=httpx.Request("POST", "https://example.com")
        )
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=empty_resp)
        mock_http.is_closed = False
        client._http = mock_http

        with pytest.raises(AuthenticationError):
            await client.get_jwt("TGT-test")

        # And specifically NOT AmbiguousOutcomeError — auth is never ambiguous.
        mock_http.post = AsyncMock(return_value=empty_resp)
        client._http = mock_http
        with pytest.raises(Exception) as exc_info:
            await client.get_jwt("TGT-test")
        assert not isinstance(exc_info.value, AmbiguousOutcomeError)
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest tests/test_grpc_client.py::TestGrpcEmptyResponseSemantics -v`
Expected: **FAIL** — empty response currently raises `ProtocolError`.

- [ ] **Step 3: Implement**

Edit `src/xtb_api/grpc/client.py`:

**Change 1** — remove the blanket empty-response check in `_grpc_call`.
Replace lines 109-110:

```python
        if not resp.text:
            raise ProtocolError("gRPC call returned empty response")
```

with (nothing — delete those two lines). `_grpc_call` will now return
`b""` when the response body is empty; callers decide what that means.

**Change 2** — in `execute_order`, detect an empty response after the
`httpx.HTTPError` catch and raise `AmbiguousOutcomeError`. Replace the
block from lines 249-259 (after the fix from Task 8) — find the section:

```python
        try:
            response_bytes = await self._grpc_call(GRPC_NEW_ORDER_ENDPOINT, body_b64, jwt=jwt)
        except httpx.HTTPError as e:
            logger.warning("gRPC trade network error: %s", e, exc_info=True)
            return GrpcTradeResult(success=False, error=str(e))

        logger.debug(
            "gRPC response: %d bytes — %s",
            len(response_bytes),
            response_bytes[:50].hex(),
        )
```

and add immediately after the `except` block, before the `logger.debug`
line:

```python
        if not response_bytes:
            # HTTP POST succeeded but the gRPC body is empty. The order may
            # or may not have been placed; the caller must reconcile.
            raise AmbiguousOutcomeError(
                "gRPC trade endpoint returned an empty response; outcome ambiguous"
            )
```

**Change 3** — update `get_jwt` to raise `AuthenticationError` when
`_grpc_call` returned empty bytes. Replace lines 144-152:

```python
        response_bytes = await self._grpc_call(GRPC_AUTH_ENDPOINT, body_b64, jwt=None)

        jwt = extract_jwt(response_bytes)
        if not jwt:
            raise AuthenticationError(
                "Failed to extract JWT from CreateAccessToken response "
                f"({len(response_bytes)} bytes). "
                "Check that TGT is valid and account info is correct."
            )
```

with:

```python
        response_bytes = await self._grpc_call(GRPC_AUTH_ENDPOINT, body_b64, jwt=None)

        if not response_bytes:
            raise AuthenticationError(
                "CreateAccessToken returned an empty response — TGT may be invalid"
            )

        jwt = extract_jwt(response_bytes)
        if not jwt:
            raise AuthenticationError(
                "Failed to extract JWT from CreateAccessToken response "
                f"({len(response_bytes)} bytes). "
                "Check that TGT is valid and account info is correct."
            )
```

**Change 4** — update the imports at the top of `src/xtb_api/grpc/client.py`
(lines 26-29):

```python
from xtb_api.exceptions import (
    AuthenticationError,
    ProtocolError,
)
```

to:

```python
from xtb_api.exceptions import (
    AmbiguousOutcomeError,
    AuthenticationError,
    ProtocolError,
)
```

(Keep `ProtocolError` — it may still be referenced elsewhere; `ruff` will
flag if not. If ruff reports unused, remove it in this change.)

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_grpc_client.py -v`
Expected: **PASS** (all tests, including the two new ones).

Run the type-checker and linter if configured:

```bash
ruff check src/xtb_api/grpc/client.py
```

Remove any unused imports ruff flags.

- [ ] **Step 5: Commit**

```bash
git add src/xtb_api/grpc/client.py tests/test_grpc_client.py
git commit -m "feat(grpc)!: empty trade response raises AmbiguousOutcomeError (F01, F14)

BREAKING: Empty trade responses previously raised ProtocolError with the
message 'gRPC call returned empty response'. Consumers string-matching
that message must switch to `except AmbiguousOutcomeError`. Empty auth
responses continue to raise AuthenticationError."
```

---

## Task 10: Dispatch CAS errors to subclasses by code (F18)

**Files:**
- Modify: `src/xtb_api/auth/cas_client.py`
- Modify: `tests/test_cas_error_subclasses.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cas_error_subclasses.py`:

```python
import pytest

from xtb_api.auth.cas_client import _cas_error_for_code


class TestCasErrorDispatch:
    """Mapping from server-supplied CAS code to the typed subclass."""

    @pytest.mark.parametrize(
        "code,expected_cls",
        [
            ("CAS_GET_TGT_UNAUTHORIZED", InvalidCredentialsError),
            ("CAS_GET_TGT_TOO_MANY_OTP_ERROR", RateLimitedError),
            ("CAS_GET_TGT_OTP_LIMIT_REACHED_ERROR", RateLimitedError),
            ("CAS_GET_TGT_OTP_ACCESS_BLOCKED_ERROR", AccountBlockedError),
            ("CAS_2FA_MISSING_TICKET", TwoFactorRequiredError),
            ("CAS_UNEXPECTED_RESPONSE", CASError),  # no mapping → plain CASError
            ("CAS_TGT_EXPIRED", CASError),  # expired ≠ bad creds
        ],
    )
    def test_dispatch(self, code: str, expected_cls: type[CASError]) -> None:
        err = _cas_error_for_code(code, "test message")
        assert type(err) is expected_cls
        assert err.code == code
        assert str(err) == "test message"
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest tests/test_cas_error_subclasses.py::TestCasErrorDispatch -v`
Expected: **FAIL** — `cannot import name '_cas_error_for_code'`.

- [ ] **Step 3: Implement**

Edit `src/xtb_api/auth/cas_client.py`. Update the existing import from
`xtb_api.exceptions` (currently line 25 `CASError,`) to:

```python
from xtb_api.exceptions import (
    AccountBlockedError,
    CASError,
    InvalidCredentialsError,
    RateLimitedError,
    TwoFactorRequiredError,
)
```

(Preserve other imports from `xtb_api.exceptions` that already exist —
inspect the current import block first.)

Then add, near the top of the module (after imports, before the first
class definition):

```python
_CAS_CODE_TO_CLASS: dict[str, type[CASError]] = {
    "CAS_GET_TGT_UNAUTHORIZED": InvalidCredentialsError,
    "CAS_GET_TGT_TOO_MANY_OTP_ERROR": RateLimitedError,
    "CAS_GET_TGT_OTP_LIMIT_REACHED_ERROR": RateLimitedError,
    "CAS_GET_TGT_OTP_ACCESS_BLOCKED_ERROR": AccountBlockedError,
    "CAS_2FA_MISSING_TICKET": TwoFactorRequiredError,
}


def _cas_error_for_code(code: str, message: str) -> CASError:
    """Return the most specific CAS exception subclass for a given code.

    Unknown codes fall back to plain ``CASError``.
    """
    cls = _CAS_CODE_TO_CLASS.get(code, CASError)
    return cls(code, message)
```

Now replace every `raise CASError(code, ...)` call in this file that
matches a mapped code with `raise _cas_error_for_code(code, ...)`.
Specifically:

- Line ~155: `raise CASError("CAS_GET_TGT_UNAUTHORIZED", "Invalid credentials")`
  → `raise _cas_error_for_code("CAS_GET_TGT_UNAUTHORIZED", "Invalid credentials")`
- Line ~189: `raise CASError(code, "Invalid email or password")`
  → `raise _cas_error_for_code(code, "Invalid email or password")`
- Line ~192, ~194, ~196: same pattern (use `_cas_error_for_code`).
- Line ~237: `raise CASError("CAS_GET_TGT_UNAUTHORIZED", ...)` → dispatch form.
- Line ~275: `raise CASError("CAS_2FA_MISSING_TICKET", ...)` → dispatch form.

Leave untouched the raises whose codes are not in the mapping (e.g.
`CAS_LOGIN_FAILED`, `CAS_V1_*`, `CAS_TGT_EXPIRED`,
`CAS_UNEXPECTED_RESPONSE`, `CAS_2FA_UNEXPECTED_RESPONSE`). They stay as
plain `CASError` — consumers can still catch the parent class.

Verify changes:

```bash
grep -n "_cas_error_for_code\|raise CASError" src/xtb_api/auth/cas_client.py
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_cas_error_subclasses.py -v`
Expected: **PASS** (all tests).
Run: `pytest tests/test_auth.py tests/test_auth_manager.py -v`
Expected: **PASS** (no regressions — existing tests catch `CASError`
which covers the new subclasses).

- [ ] **Step 5: Commit**

```bash
git add src/xtb_api/auth/cas_client.py tests/test_cas_error_subclasses.py
git commit -m "feat(auth): dispatch CAS error codes to typed subclasses (F18)"
```

---

## Task 11: `XTBClient._execute_trade` maps gRPC results to `TradeOutcome` (F16)

**Files:**
- Modify: `src/xtb_api/client.py` (replace `_execute_trade` body and its direct callers' return-shape paths)
- Modify: `tests/test_client_volume_validation.py` (update assertions — `success` is now a property)
- Create: `tests/test_client_trade_outcome_mapping.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_client_trade_outcome_mapping.py`:

```python
"""XTBClient trade methods return TradeResult with a typed TradeOutcome (F16)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from xtb_api.client import XTBClient
from xtb_api.exceptions import AmbiguousOutcomeError
from xtb_api.types.trading import TradeOutcome, TradeResult


def _make_client(monkeypatch: pytest.MonkeyPatch) -> XTBClient:
    c = XTBClient(email="x@y.z", password="p", account_number=1, session_file=None)
    c._auth = MagicMock()
    c._ws = MagicMock()
    c._ws.get_positions = AsyncMock(return_value=[])
    fake_grpc = MagicMock()
    fake_grpc.execute_order = AsyncMock()
    fake_grpc.invalidate_jwt = MagicMock()
    monkeypatch.setattr(c, "_ensure_grpc", lambda: fake_grpc)
    monkeypatch.setattr(c, "_resolve_instrument_id", AsyncMock(return_value=42))
    c._fake_grpc = fake_grpc  # type: ignore[attr-defined]
    return c


@pytest.mark.asyncio
async def test_filled_trade_returns_outcome_filled(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client(monkeypatch)
    client._fake_grpc.execute_order = AsyncMock(  # type: ignore[attr-defined]
        return_value=MagicMock(success=True, order_id="O1", error=None, grpc_status=0)
    )

    result = await client.buy("CIG.PL", volume=1)

    assert isinstance(result, TradeResult)
    assert result.status is TradeOutcome.FILLED
    assert result.order_id == "O1"
    assert result.error_code is None


@pytest.mark.asyncio
async def test_ambiguous_grpc_response_returns_outcome_ambiguous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _make_client(monkeypatch)
    client._fake_grpc.execute_order = AsyncMock(  # type: ignore[attr-defined]
        side_effect=AmbiguousOutcomeError("empty response")
    )

    result = await client.buy("CIG.PL", volume=1)

    assert result.status is TradeOutcome.AMBIGUOUS
    assert result.order_id is None
    assert result.error_code == "AMBIGUOUS_NO_RESPONSE"
    assert result.error is not None


@pytest.mark.asyncio
async def test_insufficient_volume_returns_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client(monkeypatch)

    result = await client.buy("CIG.PL", volume=0)

    assert result.status is TradeOutcome.INSUFFICIENT_VOLUME
    assert result.error_code == "INSUFFICIENT_VOLUME"
    client._fake_grpc.execute_order.assert_not_awaited()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_generic_rejection_returns_outcome_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _make_client(monkeypatch)
    client._fake_grpc.execute_order = AsyncMock(  # type: ignore[attr-defined]
        return_value=MagicMock(
            success=False,
            order_id=None,
            error="gRPC order rejected: NO_FUNDS",
            grpc_status=9,
        )
    )

    result = await client.buy("CIG.PL", volume=1)

    assert result.status is TradeOutcome.REJECTED
    assert "NO_FUNDS" in (result.error or "")
```

Also update `tests/test_client_volume_validation.py`:

The existing tests assert `"insufficient_volume" in result.error`. The
new `_execute_trade` puts the typed signal in `result.error_code`, not
in the free-text `error`. Convert the string-match assertions to typed
checks. Add the import at the top of the file:

```python
from xtb_api.types.trading import TradeOutcome
```

Then replace the error-text assertions with `error_code` assertions in
each of the four negative-volume tests (`test_buy_rejects_zero_volume`,
`test_sell_rejects_zero_volume`, `test_buy_rejects_negative_volume`,
`test_buy_rejects_fractional_below_half`). The original line reads
(varying slightly per test):

```python
    assert "insufficient_volume" in result.error
```

or:

```python
    assert "insufficient_volume" in (result.error or "")
```

Replace each with:

```python
    assert result.status is TradeOutcome.INSUFFICIENT_VOLUME
    assert result.error_code == "INSUFFICIENT_VOLUME"
```

The `result.success is False` assertions still work because `success`
is derived from `status` — leave those in place.

- [ ] **Step 2: Run to verify fail**

Run: `pytest tests/test_client_trade_outcome_mapping.py -v`
Expected: **FAIL** — `TradeResult` currently has no `status` field being
set by `_execute_trade`.

- [ ] **Step 3: Implement**

Edit `src/xtb_api/client.py`. Update the imports (lines 20-27) to include
`TradeOutcome` and `AmbiguousOutcomeError`:

```python
from xtb_api.exceptions import AmbiguousOutcomeError, InstrumentNotFoundError
...
from xtb_api.types.trading import (
    AccountBalance,
    PendingOrder,
    Position,
    TradeOptions,
    TradeOutcome,
    TradeResult,
)
```

Replace `_execute_trade` (currently lines 321-412) with:

```python
    async def _execute_trade(
        self,
        symbol: str,
        volume: int,
        side: int,
        stop_loss: float | None,
        take_profit: float | None,
        options: TradeOptions | None,
    ) -> TradeResult:
        """Execute a trade via gRPC, resolving the symbol first."""
        side_str = cast("Literal['buy', 'sell']", "buy" if side == SIDE_BUY else "sell")

        # Volume validation: reject anything that rounds to less than 1 share.
        rounded = int(volume + 0.5)
        if rounded < 1:
            return TradeResult(
                status=TradeOutcome.INSUFFICIENT_VOLUME,
                symbol=symbol,
                side=side_str,
                volume=float(volume),
                order_id=None,
                error=f"{volume} rounds to {rounded} (need >= 1)",
                error_code="INSUFFICIENT_VOLUME",
            )

        grpc = self._ensure_grpc()
        instrument_id = await self._resolve_instrument_id(symbol)

        # Merge flat kwargs into effective SL/TP (options take precedence)
        effective_sl = options.stop_loss if options and options.stop_loss is not None else stop_loss
        effective_tp = options.take_profit if options and options.take_profit is not None else take_profit

        sl_value = sl_scale = tp_value = tp_scale = None
        if effective_sl is not None:
            p = price_from_decimal(effective_sl, _decimal_places(effective_sl))
            sl_value, sl_scale = p.value, p.scale
        if effective_tp is not None:
            p = price_from_decimal(effective_tp, _decimal_places(effective_tp))
            tp_value, tp_scale = p.value, p.scale

        try:
            result = await grpc.execute_order(
                instrument_id,
                volume,
                side,
                stop_loss_value=sl_value,
                stop_loss_scale=sl_scale,
                take_profit_value=tp_value,
                take_profit_scale=tp_scale,
            )
        except AmbiguousOutcomeError as exc:
            return TradeResult(
                status=TradeOutcome.AMBIGUOUS,
                symbol=symbol,
                side=side_str,
                volume=float(volume),
                order_id=None,
                error=str(exc),
                error_code="AMBIGUOUS_NO_RESPONSE",
            )

        return await self._build_trade_result(result, symbol, side_str, volume)

    async def _build_trade_result(
        self,
        grpc_result: Any,
        symbol: str,
        side_str: Literal["buy", "sell"],
        volume: int,
    ) -> TradeResult:
        """Map a GrpcTradeResult to a typed TradeResult."""
        if grpc_result.success:
            fill_price, fill_code = await self._poll_fill_price(symbol)
            return TradeResult(
                status=TradeOutcome.FILLED,
                symbol=symbol,
                side=side_str,
                volume=float(volume),
                price=fill_price,
                order_id=grpc_result.order_id,
                error=None,
                error_code=fill_code,
            )

        # Non-success: categorize by grpc_status / error text.
        status_code = getattr(grpc_result, "grpc_status", 0) or 0
        err_text = grpc_result.error or ""
        if status_code == 7:
            outcome = TradeOutcome.AUTH_EXPIRED
            error_code = "RBAC_DENIED"
        else:
            outcome = TradeOutcome.REJECTED
            error_code = None

        return TradeResult(
            status=outcome,
            symbol=symbol,
            side=side_str,
            volume=float(volume),
            order_id=grpc_result.order_id,
            error=err_text or None,
            error_code=error_code,
        )
```

**Note:** `_poll_fill_price` now returns a 2-tuple `(price, error_code)`.
Task 13 will implement that signature change; for now, temporarily make
`_poll_fill_price` return `(price, None)` by wrapping the existing body.
Replace the current `_poll_fill_price` (lines 414-435) with:

```python
    async def _poll_fill_price(
        self, symbol: str, attempts: int = 3, delay_sec: float = 1.0
    ) -> tuple[float | None, str | None]:
        """Poll positions after a successful trade to determine the fill price.

        Returns ``(price, error_code)``. ``error_code`` is None when the
        price was observed, ``"FILL_PRICE_UNKNOWN"`` when the position did
        not appear within ``attempts`` tries. The trade still succeeded —
        the order ID is the authoritative record.
        """
        target = symbol.upper()
        for i in range(attempts):
            try:
                positions = await self._ws.get_positions()
                for p in positions:
                    if p.symbol.upper() == target:
                        return p.open_price, None
            except Exception as exc:
                logger.warning(
                    "Fill-price poll attempt %d/%d failed: %s", i + 1, attempts, exc
                )
            if i < attempts - 1:
                await asyncio.sleep(delay_sec)
        logger.warning(
            "Could not determine fill price for %s after %d attempts",
            symbol,
            attempts,
        )
        return None, "FILL_PRICE_UNKNOWN"
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_client_trade_outcome_mapping.py tests/test_client_volume_validation.py -v`
Expected: **PASS** (all tests).

Run: `pytest tests/test_client_fill_price.py -v`
Expected: the `test_fill_price_none_when_position_never_appears` test will
PASS (price is still None; `error_code` is now set but that test doesn't
check it — Task 13 will tighten it).

- [ ] **Step 5: Commit**

```bash
git add src/xtb_api/client.py tests/test_client_trade_outcome_mapping.py tests/test_client_volume_validation.py
git commit -m "feat(client)!: map trade results to TradeOutcome (F16)

BREAKING: TradeResult now carries a typed status: TradeOutcome and an
optional error_code. Consumers inspecting TradeResult.error text for
insufficient-volume / RBAC / empty-response conditions should switch
to result.status and result.error_code instead."
```

---

## Task 12: Idempotency probe before JWT-refresh retry (F02)

**Files:**
- Modify: `src/xtb_api/client.py` (extend `_execute_trade` with a retry path that first calls `_find_matching_position`)
- Create: `tests/test_client_idempotent_retry.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_client_idempotent_retry.py`:

```python
"""JWT-refresh retry must not duplicate an already-filled order (F02)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from xtb_api.client import XTBClient
from xtb_api.types.trading import Position, TradeOutcome


def _make_client(monkeypatch: pytest.MonkeyPatch) -> XTBClient:
    c = XTBClient(email="x@y.z", password="p", account_number=1, session_file=None)
    c._auth = MagicMock()
    c._ws = MagicMock()
    fake_grpc = MagicMock()
    fake_grpc.execute_order = AsyncMock()
    fake_grpc.invalidate_jwt = MagicMock()
    monkeypatch.setattr(c, "_ensure_grpc", lambda: fake_grpc)
    monkeypatch.setattr(c, "_resolve_instrument_id", AsyncMock(return_value=42))
    c._fake_grpc = fake_grpc  # type: ignore[attr-defined]
    return c


def _pos(symbol: str, volume: float, side: str, order_id: str, price: float = 1.0) -> Position:
    return Position(
        symbol=symbol,
        volume=volume,
        side=side,  # type: ignore[arg-type]
        order_id=order_id,
        open_price=price,
        current_price=price,
    )


@pytest.mark.asyncio
async def test_rbac_retry_detects_already_filled_position(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the first call returns RBAC but a matching position already exists,
    return FILLED with that order_id — do not resubmit."""
    client = _make_client(monkeypatch)

    rbac_result = MagicMock(
        success=False,
        order_id=None,
        error="gRPC RBAC: access denied",
        grpc_status=7,
    )
    client._fake_grpc.execute_order = AsyncMock(return_value=rbac_result)  # type: ignore[attr-defined]

    # A position with matching symbol/side/volume is already live.
    already_filled = _pos("CIG.PL", 5, "buy", "ALREADY-EXEC", price=23.17)
    client._ws.get_positions = AsyncMock(return_value=[already_filled])

    result = await client.buy("CIG.PL", volume=5)

    assert result.status is TradeOutcome.FILLED
    assert result.order_id == "ALREADY-EXEC"
    # Crucially, execute_order was called ONCE, not twice — no retry.
    assert client._fake_grpc.execute_order.await_count == 1  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_rbac_retry_proceeds_when_no_matching_position(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No matching position → invalidate JWT and retry."""
    client = _make_client(monkeypatch)

    rbac_result = MagicMock(
        success=False,
        order_id=None,
        error="gRPC RBAC: access denied",
        grpc_status=7,
    )
    retry_result = MagicMock(success=True, order_id="NEW-OK", error=None, grpc_status=0)
    client._fake_grpc.execute_order = AsyncMock(  # type: ignore[attr-defined]
        side_effect=[rbac_result, retry_result]
    )
    # No positions exist yet — probe comes back empty.
    client._ws.get_positions = AsyncMock(return_value=[])

    result = await client.buy("CIG.PL", volume=5)

    assert result.status is TradeOutcome.FILLED
    assert result.order_id == "NEW-OK"
    assert client._fake_grpc.execute_order.await_count == 2  # type: ignore[attr-defined]
    client._fake_grpc.invalidate_jwt.assert_called_once()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_rbac_retry_position_wrong_side_does_not_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A position with the right symbol but wrong side must not short-circuit."""
    client = _make_client(monkeypatch)

    rbac_result = MagicMock(
        success=False,
        order_id=None,
        error="RBAC",
        grpc_status=7,
    )
    retry_result = MagicMock(success=True, order_id="NEW", error=None, grpc_status=0)
    client._fake_grpc.execute_order = AsyncMock(  # type: ignore[attr-defined]
        side_effect=[rbac_result, retry_result]
    )

    # An UNRELATED short position — wrong side, must not match.
    other_side = _pos("CIG.PL", 5, "sell", "OTHER")
    client._ws.get_positions = AsyncMock(return_value=[other_side])

    result = await client.buy("CIG.PL", volume=5)

    assert result.status is TradeOutcome.FILLED
    assert result.order_id == "NEW"
    assert client._fake_grpc.execute_order.await_count == 2  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_non_rbac_rejection_does_not_probe_positions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A plain rejection (e.g. NO_FUNDS) must not trigger the idempotency probe."""
    client = _make_client(monkeypatch)

    reject_result = MagicMock(
        success=False,
        order_id=None,
        error="NO_FUNDS",
        grpc_status=9,
    )
    client._fake_grpc.execute_order = AsyncMock(return_value=reject_result)  # type: ignore[attr-defined]
    client._ws.get_positions = AsyncMock(return_value=[])

    result = await client.buy("CIG.PL", volume=5)

    assert result.status is TradeOutcome.REJECTED
    # Positions not polled on a non-RBAC rejection.
    client._ws.get_positions.assert_not_awaited()
    assert client._fake_grpc.execute_order.await_count == 1  # type: ignore[attr-defined]
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest tests/test_client_idempotent_retry.py -v`
Expected: **FAIL** — current behavior retries on RBAC without probing.

- [ ] **Step 3: Implement**

In `src/xtb_api/client.py`, extend `_execute_trade` to perform the
idempotency probe before retrying on RBAC. Replace the portion of
`_execute_trade` that runs *after* the first `grpc.execute_order` call
(i.e. replace the block starting at `return await self._build_trade_result(...)`
at the end of the current `_execute_trade`) with this expanded retry
block:

```python
        # F02/F13: detect RBAC/AUTH_EXPIRED via grpc_status 7 — reliable
        # regardless of the free-text error message.
        if not result.success and getattr(result, "grpc_status", 0) == 7:
            # Idempotency probe: did the first call actually fill despite
            # the RBAC error? Compare live positions against the request.
            existing = await self._find_matching_position(symbol, volume, side_str)
            if existing is not None:
                logger.info(
                    "RBAC returned but matching position %s already exists — "
                    "skipping retry (idempotent short-circuit)",
                    existing.order_id,
                )
                return TradeResult(
                    status=TradeOutcome.FILLED,
                    symbol=symbol,
                    side=side_str,
                    volume=float(volume),
                    price=existing.open_price,
                    order_id=existing.order_id,
                    error=None,
                    error_code=None,
                )

            logger.info("RBAC error, refreshing JWT and retrying...")
            grpc.invalidate_jwt()
            try:
                result = await grpc.execute_order(
                    instrument_id,
                    volume,
                    side,
                    stop_loss_value=sl_value,
                    stop_loss_scale=sl_scale,
                    take_profit_value=tp_value,
                    take_profit_scale=tp_scale,
                )
            except AmbiguousOutcomeError as exc:
                return TradeResult(
                    status=TradeOutcome.AMBIGUOUS,
                    symbol=symbol,
                    side=side_str,
                    volume=float(volume),
                    order_id=None,
                    error=str(exc),
                    error_code="AMBIGUOUS_NO_RESPONSE",
                )

        return await self._build_trade_result(result, symbol, side_str, volume)
```

Then add a new helper method on `XTBClient` (after `_execute_trade`,
before `_poll_fill_price`):

```python
    async def _find_matching_position(
        self, symbol: str, volume: int, side_str: Literal["buy", "sell"]
    ) -> Position | None:
        """Find a live position that plausibly corresponds to a just-sent trade.

        Matching is best-effort: symbol (case-insensitive) + side + volume.
        A match means the first submission landed despite the RBAC error —
        caller must return FILLED instead of retrying.
        """
        try:
            positions = await self._ws.get_positions()
        except Exception as exc:
            logger.warning("Idempotency probe failed (get_positions): %s", exc)
            return None

        target = symbol.upper()
        for p in positions:
            if (
                p.symbol.upper() == target
                and p.side == side_str
                and abs(p.volume - float(volume)) < 1e-9
            ):
                return p
        return None
```

**IMPORTANT** — remove the old RBAC retry block. Specifically, delete
the previous `if not result.success and result.error and "RBAC" in result.error:`
block (lines ~377-389 in the original file, or whatever remains after
Task 11). The new block above replaces it.

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_client_idempotent_retry.py -v`
Expected: **PASS** (4 tests).
Run: `pytest tests/test_client_trade_outcome_mapping.py tests/test_client_volume_validation.py tests/test_client_fill_price.py -v`
Expected: **PASS** (no regressions).

- [ ] **Step 5: Commit**

```bash
git add src/xtb_api/client.py tests/test_client_idempotent_retry.py
git commit -m "fix(client): probe positions before JWT-refresh retry to avoid duplicate orders (F02, F13)"
```

---

## Task 13: Distinguish "fill price unknown" from "position never appeared" (F15, F40)

**Files:**
- Modify: `tests/test_client_fill_price.py` (tighten existing tests to assert `error_code`)
- Modify: `src/xtb_api/client.py` (already partly done in Task 11 — verify the tuple return is honored by `_build_trade_result`)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_client_fill_price.py`:

```python
from xtb_api.types.trading import TradeOutcome


@pytest.mark.asyncio
async def test_fill_price_unknown_sets_error_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the fill-price poll exhausts, error_code must explicitly say so."""
    client = _make_client(monkeypatch)
    client._fake_grpc.execute_order = AsyncMock(  # type: ignore[attr-defined]
        return_value=MagicMock(success=True, order_id="O1", error=None, grpc_status=0)
    )
    client._ws.get_positions = AsyncMock(return_value=[])  # never appears
    monkeypatch.setattr("asyncio.sleep", AsyncMock())

    result = await client.buy("CIG.PL", volume=1)

    assert result.status is TradeOutcome.FILLED  # trade still succeeded
    assert result.price is None
    assert result.error_code == "FILL_PRICE_UNKNOWN"


@pytest.mark.asyncio
async def test_fill_price_known_no_error_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy path: error_code is None when fill price was observed."""
    client = _make_client(monkeypatch)
    client._fake_grpc.execute_order = AsyncMock(  # type: ignore[attr-defined]
        return_value=MagicMock(success=True, order_id="O1", error=None, grpc_status=0)
    )
    client._ws.get_positions = AsyncMock(return_value=[_pos("CIG.PL", 42.5)])

    result = await client.buy("CIG.PL", volume=1)

    assert result.status is TradeOutcome.FILLED
    assert result.price == 42.5
    assert result.error_code is None


@pytest.mark.asyncio
async def test_fill_price_poll_exception_does_not_mask_fill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An exception in the poll must not turn a FILLED trade into an error."""
    client = _make_client(monkeypatch)
    client._fake_grpc.execute_order = AsyncMock(  # type: ignore[attr-defined]
        return_value=MagicMock(success=True, order_id="O1", error=None, grpc_status=0)
    )
    client._ws.get_positions = AsyncMock(side_effect=RuntimeError("network blip"))
    monkeypatch.setattr("asyncio.sleep", AsyncMock())

    result = await client.buy("CIG.PL", volume=1)

    assert result.status is TradeOutcome.FILLED
    assert result.order_id == "O1"
    assert result.price is None
    assert result.error_code == "FILL_PRICE_UNKNOWN"
```

- [ ] **Step 2: Run to verify fail or pass**

Run: `pytest tests/test_client_fill_price.py -v`
Expected: the three new tests **PASS** already because Task 11 wired up
the `(price, error_code)` tuple and `_build_trade_result` propagates
`error_code`. If any fails, fix the mapping in `_build_trade_result` so
that `fill_code` is placed in `TradeResult.error_code`.

- [ ] **Step 3: Implement (only if Step 2 reports failures)**

If the poll-exception test fails (caller sees price=None but
error_code=None), audit `_poll_fill_price` — the `except Exception`
should still hit the final `return None, "FILL_PRICE_UNKNOWN"` branch
when all attempts raise. No code change should be needed; if tests fail,
re-verify the tuple shape in `_build_trade_result`.

- [ ] **Step 4: Run full client-side suite**

Run: `pytest tests/test_client_fill_price.py tests/test_client_trade_outcome_mapping.py tests/test_client_volume_validation.py tests/test_client_idempotent_retry.py -v`
Expected: **PASS** (all tests).

- [ ] **Step 5: Commit**

```bash
git add tests/test_client_fill_price.py
git commit -m "test(client): assert error_code signals fill-price poll exhaustion (F15, F40)"
```

---

## Task 14: End-to-end `match`-statement smoke test

**Files:**
- Create: `tests/test_trade_outcome_match.py`

- [ ] **Step 1: Write the test**

Create `tests/test_trade_outcome_match.py`:

```python
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
```

- [ ] **Step 2: Run to verify pass**

Run: `pytest tests/test_trade_outcome_match.py -v`
Expected: **PASS** (3 tests).

- [ ] **Step 3: Run the full test suite**

Run: `pytest -v`
Expected: **PASS** across every test file. Any red test must be triaged
and fixed before committing.

- [ ] **Step 4: Commit**

```bash
git add tests/test_trade_outcome_match.py
git commit -m "test: end-to-end match-statement shape for TradeOutcome"
```

---

## Task 15: Update CHANGELOG for v1.0 breaking changes

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add a new "Unreleased" section entry**

Prepend to `CHANGELOG.md`, under the existing header, a block like:

```markdown
## [Unreleased] — v1.0 (workstream W1)

### Breaking Changes

- `TradeResult.success` is now a `@property` derived from
  `status is TradeOutcome.FILLED`. Constructors no longer accept
  `success=bool`; pass `status=TradeOutcome.*` instead. (F16)
- Empty gRPC trade responses raise `AmbiguousOutcomeError` (a
  `TradeError` subclass) instead of `ProtocolError` with a
  string-matchable message. Consumers that pattern-matched on
  `"gRPC call returned empty response"` must switch to
  `except AmbiguousOutcomeError`. (F01, F14)
- gRPC rejected-order messages are no longer clipped to 200 characters.
  (F22)
- `CASError` now has typed subclasses: `InvalidCredentialsError`,
  `AccountBlockedError`, `RateLimitedError`, `TwoFactorRequiredError`.
  Code reading `CASError.code` strings can migrate to
  `except InvalidCredentialsError:` etc. `CASError` remains a parent
  for forward compatibility. (F18)

### Additive

- New `TradeOutcome` enum with values `FILLED`, `REJECTED`, `AMBIGUOUS`,
  `INSUFFICIENT_VOLUME`, `AUTH_EXPIRED`, `RATE_LIMITED`, `TIMEOUT`.
  Exported from the top-level `xtb_api` package. (F16)
- `TradeResult.error_code: str | None` for stable short codes such as
  `"INSUFFICIENT_VOLUME"`, `"RBAC_DENIED"`, `"AMBIGUOUS_NO_RESPONSE"`,
  `"FILL_PRICE_UNKNOWN"`. (F15, F40)

### Fixes

- JSON decode failures inside the WebSocket listener now emit
  `ProtocolError` instead of a bare `RuntimeError`. (F21)
- `GrpcClient.execute_order` now narrows its exception handling to
  `httpx.HTTPError`; unexpected exceptions (logic bugs) propagate with
  full tracebacks instead of being silently stuffed into
  `GrpcTradeResult.error`. (F19)
- JWT-refresh retry on RBAC now first checks for a matching live
  position and short-circuits to `TradeOutcome.FILLED` if the initial
  send already landed, eliminating the duplicate-order risk. (F02)
- RBAC detection uses `grpc-status: 7` instead of string-matching
  `"RBAC"` in error text. (F13)
```

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): record W1 v1.0 changes"
```

---

## Self-Review

After all tasks are implemented, run the full suite one more time:

```bash
pytest -v
```

Expected: **PASS** across every test file. Also run `ruff check src/` and
fix any lint errors introduced.

Additionally re-read the spec §7 and §12 and confirm:

- [x] F01 — Empty gRPC → `AmbiguousOutcomeError` + `TradeOutcome.AMBIGUOUS`
  (Tasks 3, 9, 11).
- [x] F02 — Idempotency probe before JWT-refresh retry (Task 12).
- [x] F13 — RBAC via `grpc_status == 7`, not string match (Task 12).
- [x] F14 — Empty-response marker no longer a free-text string (Tasks 9, 11).
- [x] F15 — `_poll_fill_price` poll-exhaust is now explicit via
  `error_code="FILL_PRICE_UNKNOWN"` (Tasks 11, 13).
- [x] F16 — `TradeResult.status` + `error_code`, `success` derived
  (Task 2).
- [x] F18 — CAS subclasses + dispatch (Tasks 4, 10).
- [x] F19 — Narrowed `except Exception` in gRPC (Task 8).
- [x] F21 — `ProtocolError` on JSON decode (Task 6).
- [x] F22 — 200-char truncation removed (Task 7).
- [x] F40 — Fill-price unknown distinguishable via `error_code`
  (Tasks 11, 13).

Also verify the migration-guide snippets from spec §12 compile:

- "Classify empty-response as `AmbiguousOutcomeError`" — Tasks 3, 9, 11.
- "Use `TradeOutcome` instead of `success` + string match" — Tasks 2, 11.
- "New `CASError` subclasses" — Tasks 4, 10.

(The "reconnect exhaustion" and "Playwright extras" snippets belong to
W2 and W3 and are NOT in scope here.)

---

## Done criteria

- All 14 (+1 CHANGELOG) tasks committed on a feature branch.
- Full `pytest -v` passes locally.
- `ruff check src/` passes.
- No uses of `"RBAC" in ...` or `"gRPC call returned empty response" in ...`
  remain in `src/` (grep to confirm).
- Branch ready for PR against `master` with title
  "feat!: W1 typed trade outcomes + idempotent retry (closes F01, F02, F13–F16, F18, F19, F21, F22, F40)".
