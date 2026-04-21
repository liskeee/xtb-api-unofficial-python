# xtb-api-python — Queued orders (market closed) & cancel

Status: draft for review
Author: brainstormed with Claude Opus 4.7
Date: 2026-04-21

---

## 1. Context

XTB accepts market-order requests at any time. When the underlying
instrument's market is closed (e.g. placing a BUY on `AAPL.US` outside
NASDAQ hours), the broker **queues** the order rather than rejecting it.
The order sits in "pending" state on the broker side until the market
opens, at which point it is filled at the prevailing price.

The gRPC `NewMarketOrder` response is **byte-identical** for filled and
queued orders — verified against two HAR captures:

| | filled (`demo.har`, `06N.PL` during Warsaw hours) | queued (`demo_market_closed.har`, `AAPL.US` outside NASDAQ hours) |
|---|---|---|
| HTTP | 200 | 200 |
| grpc-status | 0 | 0 |
| response field 1 (UUID) | `16826ae6-cd02-4ed9-81d3-13d056d2f9d4` | `a4c205ea-84c0-45aa-b0e0-34ef7ce060fe` |
| response field 2.1 (order_number) | `872069505` | `872077045` |

The current library ([src/xtb_api/client.py:464](../../../src/xtb_api/client.py#L464))
treats any `grpc-status 0` as `TradeOutcome.FILLED` and then calls
`_poll_fill_price(symbol)` to resolve the price via `get_positions()`.
For a queued order the position never materialises, so callers get a
`TradeResult(status=FILLED, price=None, order_id=UUID)` — a phantom fill
that is silently wrong.

The captured HAR also reveals the cancel protocol used by xStation5:
`CashTradingNewOrderService/DeleteOrders`, taking a packed repeated
uint64 list of order numbers (7-byte request payload for a single
cancel: `0a 05 f5 ad eb 9f 03` = `{field 1: packed [872077045]}`).
Response: `{field 1: cancellation UUID, field 2.1: the cancelled order
number}`, grpc-status 0.

**Scope**

In:
- Detect queued orders after a successful `NewMarketOrder` round-trip
  and surface them as `TradeOutcome.QUEUED`.
- Populate `TradeResult.order_number` so callers have what they need
  to cancel.
- Add `client.cancel_order(order_number)` hitting `DeleteOrders`,
  returning a typed `CancelResult` / `CancelOutcome`.

Out:
- No auto-cancel: `buy()` / `sell()` surface `QUEUED`; the caller
  decides whether to hold or cancel. (Design decision, see §10.)
- No batch cancel in the public API. The wire stays honest (packed
  repeated uint64) but the public method is single-order; bulk cancel
  can be added later without breaking changes.
- No subscription streams (`SubscribeNewMarketOrderConfirmation`,
  `SubscribeDeleteOrdersConfirmation`). Poll-based detection is
  simpler and sufficient for the first cut.
- No reconciliation on reconnect — only the "just-placed" case. A
  separate session-resume / audit flow can cover orders placed in a
  previous session.
- No change to limit / stop pending orders — those remain covered by
  the existing `get_orders()` / `PendingOrder` path.

---

## 2. Detection flow

After `GrpcClient.execute_order` returns `success=True` with both
`order_id` (UUID) and `order_number` (uint64 — new field we expose on
`GrpcTradeResult`; see §5), `XTBClient._build_trade_result` runs:

1. `positions = await ws.get_positions()` — match by `(symbol, side,
   volume)` using the existing `_find_matching_position` helper
   ([src/xtb_api/client.py:497](../../../src/xtb_api/client.py#L497)).
   Hit → `FILLED`; call `_poll_fill_price` to pick up the fill price.
2. Miss → `orders = await ws.get_orders()` — match by
   `order.order_id == str(order_number)`. Hit → `QUEUED`.
3. Still miss → `await asyncio.sleep(0.5)`, repeat steps 1 and 2 once.
4. Still miss → `AMBIGUOUS` with `error_code="FILL_STATE_UNKNOWN"`.
   Caller reconciles on their own schedule.

Exceptions from either probe (WS disconnect, request timeout) are
caught and treated as a miss for *that probe only* — the other probe
and the second pass still run. If both probes have raised on both
passes, return `AMBIGUOUS` with the last exception's message in
`error`.

Latency budget on the happy (filled) path: one `getPositions` call
(typical ~50–200 ms). Queued path: `getPositions` + `getOrders`.
`AMBIGUOUS` path: both calls twice plus 500 ms.

**Why both sources of truth**: `get_positions()` is authoritative for
filled state (the position appears only after fill), and `get_orders()`
covers limit/stop **and** queued-market orders — we're assuming the
latter lands in the same pending list. The second pass with a short
sleep handles a race where neither the position nor the pending order
has propagated yet when we first look.

**Assumption to verify at implementation time**: market-closed queued
market orders appear in `getAllOrders`. XTB's own nomenclature
("pending") and the UI's use of the same subscription stream for all
non-filled orders make this very likely, but a 5-minute demo-account
smoke test should confirm before closing out the implementation.
Contingency: if queued market orders are **not** in `getAllOrders`,
fall back to a longer positions-only poll with a configurable deadline
(e.g. 3 × 500 ms) and treat "no position after deadline" as `QUEUED`.
This is strictly worse (can't distinguish queued from a slow fill) so
we only adopt it if necessary.

---

## 3. Current-state reference

Files that will change, with their current responsibilities:

- [src/xtb_api/types/trading.py](../../../src/xtb_api/types/trading.py) —
  Pydantic models: `Position`, `PendingOrder`, `AccountBalance`,
  `TradeOutcome`, `TradeResult`. Self-contained, no imports from
  `client.py`. Good place to grow cancel types.
- [src/xtb_api/grpc/proto.py](../../../src/xtb_api/grpc/proto.py) —
  Constants (`GRPC_AUTH_ENDPOINT`, `GRPC_NEW_ORDER_ENDPOINT`,
  `GRPC_WEB_TEXT_CONTENT_TYPE`, `SIDE_BUY`, `SIDE_SELL`) and builders
  (`build_create_access_token_request`, `build_new_market_order`,
  `build_grpc_web_text_body`), plus low-level parsers
  (`parse_grpc_frames`, `parse_proto_fields`, `extract_jwt`).
- [src/xtb_api/grpc/client.py](../../../src/xtb_api/grpc/client.py) —
  `GrpcClient` with JWT caching, `buy` / `sell` / `execute_order`, and
  `_parse_trade_response`. Already extracts the order UUID via regex;
  does **not** currently extract the order_number (field 2.1).
- [src/xtb_api/grpc/types.py](../../../src/xtb_api/grpc/types.py) —
  `GrpcTradeResult` dataclass with `success`, `order_id`, `grpc_status`,
  `error`.
- [src/xtb_api/client.py](../../../src/xtb_api/client.py) — `XTBClient`
  orchestrator. `_build_trade_result` is the single place that maps
  `GrpcTradeResult` → `TradeResult` and is the surgical point for the
  detection flow change.
- [src/xtb_api/ws/ws_client.py](../../../src/xtb_api/ws/ws_client.py)
  lines 564–587 — `get_positions` and `get_orders` already exist; no
  changes needed on the WS side.
- [src/xtb_api/__init__.py](../../../src/xtb_api/__init__.py) — public
  re-exports; grows `CancelResult`, `CancelOutcome`, and (via existing
  re-export of `TradeOutcome`) the new `QUEUED` value.

---

## 4. Public API additions

### 4.1 `TradeOutcome.QUEUED`

Add one enum value:

```python
class TradeOutcome(StrEnum):
    FILLED = "FILLED"
    QUEUED = "QUEUED"          # NEW: broker accepted, market closed / awaiting open
    REJECTED = "REJECTED"
    AMBIGUOUS = "AMBIGUOUS"
    INSUFFICIENT_VOLUME = "INSUFFICIENT_VOLUME"
    AUTH_EXPIRED = "AUTH_EXPIRED"
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT = "TIMEOUT"
```

Name rationale: `QUEUED` rather than `PENDING` because `PendingOrder`
(limit/stop) already exists and overloading "pending" in two different
meanings inside one library is a footgun.

### 4.2 `TradeResult.order_number`

Add one optional field:

```python
class TradeResult(BaseModel):
    ...
    order_number: int | None = None   # NEW: broker order number; feed into cancel_order
    ...

    @property
    def success(self) -> bool:        # unchanged; still FILLED-only
        return self.status is TradeOutcome.FILLED
```

Populated whenever the gRPC response carried field 2.1 — true for both
`FILLED` and `QUEUED`. For `REJECTED`, `AMBIGUOUS`,
`INSUFFICIENT_VOLUME` and friends, it stays `None`.

### 4.3 Cancel types

New in `src/xtb_api/types/trading.py`:

```python
class CancelOutcome(StrEnum):
    """Typed outcome of a cancel request."""
    CANCELLED = "CANCELLED"   # grpc-status 0; broker accepted the cancel
    REJECTED  = "REJECTED"    # broker refused: unknown order, already filled, etc.
    AMBIGUOUS = "AMBIGUOUS"   # network/protocol failure; reconcile via get_orders()


class CancelResult(BaseModel):
    """Cancel execution result. Mirrors TradeResult's shape conventions."""
    model_config = {"extra": "forbid"}

    status: CancelOutcome
    order_number: int
    cancellation_id: str | None = None   # UUID from DeleteOrders response
    error: str | None = None
    error_code: str | None = None

    @property
    def success(self) -> bool:
        return self.status is CancelOutcome.CANCELLED
```

### 4.4 `XTBClient.cancel_order`

```python
class XTBClient:
    async def cancel_order(self, order_number: int) -> CancelResult:
        """Cancel a queued (or pending) broker order by its order number.

        Pass the `order_number` from a queued `TradeResult`. Returns a
        typed `CancelResult`; inspect `.status` against `CancelOutcome`.

        `CancelOutcome.REJECTED` is common and expected — if the order
        filled between the `buy()` call and `cancel_order()`, the broker
        has no queued order to cancel.
        """
```

Single-order only, per brainstorming decision (Q3-A). The gRPC wire
supports batch (packed repeated uint64) and we preserve that honestly
at the `GrpcClient` layer (`cancel_orders(list[int])`), but the
public surface exposes only the single-order form. Bulk cancel can be
added later as a pure addition.

---

## 5. Internal changes

### 5.1 `xtb_api/grpc/proto.py`

Add:

- `GRPC_DELETE_ORDERS_ENDPOINT` — the full URL, same host as
  `GRPC_NEW_ORDER_ENDPOINT`, path
  `/pl.xtb.ipax.pub.grpc.cashtradingneworder.v1.CashTradingNewOrderService/DeleteOrders`.
- `build_delete_orders_request(order_numbers: list[int]) -> bytes` —
  emits `field 1` as length-delimited (wire type 2) carrying a packed
  varint sequence of the order numbers. For `[872077045]` this must
  produce exactly `0a 05 f5 ad eb 9f 03` (verified against HAR).
- `parse_delete_orders_response(payload: bytes) -> tuple[str | None, int | None]` —
  returns `(cancellation_id, order_number)` from `field 1` (UUID
  string) and `field 2.1` (varint). Mirrors the existing
  `extract_jwt` / ad-hoc UUID regex pattern but purpose-built.
- `parse_new_market_order_response(payload: bytes) -> tuple[str | None, int | None]` —
  refactor of the current regex-based UUID extraction in
  `GrpcClient._parse_trade_response` so we also get `order_number`
  (field 2.1) back. Keeps the parser testable as a pure function.

### 5.2 `xtb_api/grpc/types.py`

Extend `GrpcTradeResult`:

```python
@dataclass(slots=True)
class GrpcTradeResult:
    success: bool
    order_id: str | None = None
    order_number: int | None = None   # NEW
    grpc_status: int | None = None
    error: str | None = None
```

Add:

```python
@dataclass(slots=True)
class GrpcCancelResult:
    success: bool
    order_number: int
    cancellation_id: str | None = None
    grpc_status: int | None = None
    error: str | None = None
```

### 5.3 `xtb_api/grpc/client.py`

- `_parse_trade_response` switches from the inline UUID regex to
  `parse_new_market_order_response`; `GrpcTradeResult.order_number`
  gets populated on success.
- Add `async def cancel_orders(self, order_numbers: list[int]) -> list[GrpcCancelResult]`:
  - JWT fetch via `_ensure_jwt` (same flow as `execute_order`).
  - Build body via `build_delete_orders_request`, POST to
    `GRPC_DELETE_ORDERS_ENDPOINT`.
  - Response shape: one data frame per cancelled order (based on the
    HAR we have only the single-order case — worth confirming during
    implementation that batch cancels return N frames, but for the
    single-order API this is moot).
  - Errors: network → `GrpcCancelResult(success=False,
    error=str(exc))` per order; non-zero grpc-status → `success=False`
    with the wire message.
- Both `cancel_order` and bulk cancel share the same parsing path.

### 5.4 `xtb_api/client.py`

- `_build_trade_result` gains the detection flow from §2. On success,
  it **no longer** unconditionally returns `FILLED`; instead it runs
  the position/orders probe and branches. `_poll_fill_price` is only
  called on the `FILLED` branch (today it runs on any success, which
  is the bug source for queued orders).
- New `async def cancel_order(self, order_number: int) -> CancelResult`:
  thin wrapper calling `self._ensure_grpc().cancel_orders([order_number])[0]`
  and mapping `GrpcCancelResult` → `CancelResult`. Error taxonomy:
  - `success=True` → `CANCELLED`.
  - `success=False, grpc_status in (non-zero)` → `REJECTED`, error
    text surfaced. `error_code` left `None` unless we can identify a
    stable XTB code (we don't today — the HAR doesn't expose an error
    catalog).
  - `httpx.HTTPError` / network → `AMBIGUOUS` with
    `error_code="AMBIGUOUS_NO_RESPONSE"`.

### 5.5 `xtb_api/__init__.py`

Add `CancelResult` and `CancelOutcome` to the public re-exports and
the `__all__` list.

---

## 6. Error handling

Classification table for `cancel_order`:

| Broker response | `CancelOutcome` | `error_code` |
|---|---|---|
| grpc-status 0 | `CANCELLED` | `None` |
| grpc-status ≠ 0, message mentions "already filled" / "not found" | `REJECTED` | `None` (raw wire message in `error`) |
| grpc-status ≠ 0, RBAC (status 7) | `REJECTED` | `RBAC_DENIED` — same convention as `TradeResult` |
| `httpx.HTTPError` / connection drop | `AMBIGUOUS` | `AMBIGUOUS_NO_RESPONSE` |
| Empty response body | `AMBIGUOUS` | `AMBIGUOUS_NO_RESPONSE` |

For the QUEUED-detection flow:

| Failure mode | Behaviour |
|---|---|
| `ws.get_positions()` raises (WS disconnect) | Caught; try `ws.get_orders()` alone. If that also raises, return `AMBIGUOUS` with the underlying error in `error`. |
| `ws.get_orders()` raises | Return `AMBIGUOUS` with the underlying error in `error` (a position-positive match at step 1 short-circuits before this, so we only get here if step 1 also missed). |
| Both probes return empty twice | `AMBIGUOUS` with `error_code="FILL_STATE_UNKNOWN"`, `error` set to a descriptive message naming the order number. |

No retry loop on the trade-side probes — the library already has one
RBAC retry inside `execute_order`, and adding another retry layer in
`_build_trade_result` would compound delays on the unhappy path.

---

## 7. Tests

All tests are unit-level with no network. Three files touched or
created:

### 7.1 `tests/test_trade_outcomes.py` (grow existing)

New cases — all use a fake `GrpcClient` and a fake `WsClient` stub
(matching the pattern already used in the file):

- `test_queued_order_detected_via_pending_orders_list` — gRPC returns
  `success=True, order_number=872077045`, `get_positions()` returns
  `[]`, `get_orders()` returns a `PendingOrder(order_id="872077045",
  ...)`. Expected: `TradeResult(status=QUEUED, order_number=872077045,
  order_id=UUID)`.
- `test_filled_order_still_returns_filled` — regression guard:
  positions match by symbol/side/volume → `FILLED`, `order_number`
  populated.
- `test_neither_position_nor_order_found_is_ambiguous` — both probes
  empty on both passes → `AMBIGUOUS` with `error_code="FILL_STATE_UNKNOWN"`.
- `test_get_positions_failure_falls_through_to_orders` — first probe
  raises; orders probe succeeds → `QUEUED`.
- `test_order_number_populated_on_filled` — legacy callers who only
  read `order_id` still work; `order_number` is new and additive.

### 7.2 `tests/test_cancel_order.py` (new)

- `test_cancel_happy_path` — fake gRPC returns grpc-status 0 with
  cancellation UUID and original order number → `CancelResult(status=
  CANCELLED, cancellation_id=UUID, order_number=N)`.
- `test_cancel_rejected_order_not_found` — fake gRPC returns non-zero
  status with "order not found" in grpc-message → `REJECTED` with the
  wire message surfaced in `error`.
- `test_cancel_network_error_is_ambiguous` — fake gRPC raises
  `httpx.HTTPError` → `AMBIGUOUS` with
  `error_code="AMBIGUOUS_NO_RESPONSE"`.
- `test_cancel_result_success_property` — `success` iff
  `status is CANCELLED`.

### 7.3 `tests/test_grpc_proto.py` (grow existing)

Pure byte round-trip tests against the actual HAR captures — these
are the wire-format regression guards:

- `test_build_delete_orders_request_single` — call
  `build_delete_orders_request([872077045])`; assert the 7-byte payload
  matches `bytes.fromhex("0a05f5adeb9f03")`.
- `test_parse_delete_orders_response` — feed in the 48-byte data
  frame from `demo_market_closed.har` entry 3; assert the returned
  `(cancellation_id, order_number)` equals
  `("9e5b4600-2ecb-4e4b-a92c-e465367a80f9", 872077045)`.
- `test_parse_new_market_order_response_extracts_order_number` — feed
  the 46-byte data frame from `demo_market_closed.har` entry 1; assert
  `(order_id, order_number) == ("a4c205ea-84c0-45aa-b0e0-34ef7ce060fe",
  872077045)`.

No integration test placing a real order — all wire-level assertions
are driven from the captured HARs.

---

## 8. Docs / examples

### 8.1 `examples/grpc_trade.py`

Add a `QUEUED` case to the `describe()` match block:

```python
case TradeOutcome.QUEUED:
    return (
        f"QUEUED  order={result.order_id}  order_number={result.order_number}  "
        f"— market closed; order will fill when market opens. "
        f"Cancel with: await client.cancel_order({result.order_number})"
    )
```

### 8.2 `examples/cancel_queued_order.py` (new)

Minimal standalone example gated by `XTB_EXAMPLE_TRADE=1`. Flow:
place a BUY of `AAPL.US` (which is usually market-closed for non-US
business hours), expect `QUEUED`, print the order number, call
`cancel_order`, print the `CancelResult`. Uses the demo account via
`XTB_ACCOUNT_TYPE=demo` (cross-references the sister spec on demo
mode).

### 8.3 README

New subsection under Trading:

```markdown
### Queued orders (market closed)

When the instrument's market is closed, XTB accepts the order and
queues it until market open. The library surfaces this as
`TradeOutcome.QUEUED`:

    result = await client.buy("AAPL.US", volume=1)
    if result.status is TradeOutcome.QUEUED:
        print(f"Queued order {result.order_number}; cancelling...")
        await client.cancel_order(result.order_number)

`result.order_number` is the broker-assigned integer order number and
is populated for both filled and queued trades. A filled order
reports `TradeOutcome.FILLED` (unchanged).
```

### 8.4 CHANGELOG

Under `## [0.8.0]` (next version; may be bumped by the demo-mode spec
landing first):

```markdown
### Added
- `TradeOutcome.QUEUED` — new outcome for market-order requests that
  XTB accepts but does not immediately fill (typically: market closed).
  Previously these were reported as `FILLED` with `price=None` — a
  silent misclassification.
- `TradeResult.order_number` — integer broker order number, populated
  from the gRPC `NewMarketOrder` response for both filled and queued
  trades. Feed into `client.cancel_order()`.
- `XTBClient.cancel_order(order_number)` — cancel a queued/pending
  broker order via gRPC `DeleteOrders`. Returns `CancelResult` with
  `CancelOutcome` (`CANCELLED` / `REJECTED` / `AMBIGUOUS`).

### Fixed
- Market-closed orders are no longer silently reported as `FILLED` when
  the broker has actually queued them.
```

---

## 9. Backwards compatibility

- Consumers reading `TradeResult.success` continue to work: it stays
  `True` iff `status is FILLED`. Queued orders now correctly report
  `success=False`.
- Consumers that match on `TradeOutcome` values: their
  `case TradeOutcome.FILLED` arm continues to work; they gain a new
  `QUEUED` arm they may not handle. Today those same callers are
  being *silently lied to* (QUEUED shows up as FILLED with
  `price=None`), so the new behaviour is strictly more correct, not
  less compatible.
- `TradeResult.order_number` is additive (default `None`). Pydantic
  `extra="forbid"` means callers constructing `TradeResult` directly
  in their own code (rare — library-produced) would need to accept
  the new field; low risk.
- New public symbols (`CancelResult`, `CancelOutcome`) are additive.

Minor version bump is sufficient.

---

## 10. Decision log

- **Q1 — Queued-vs-filled detection.** Chose "positions-then-orders
  probe" (Option B). Alternatives considered: position-poll-only (no
  pending signal — can't distinguish queued from slow fill) and
  subscription stream (much more code for no actual win over a
  probe). See §2.
- **Q2 — Auto-cancel policy.** Chose "surface only, caller decides"
  (Option A). Library does not auto-cancel a queued order behind
  the caller's back. Reason: the original bug report wants
  *visibility* into the queued state; a silent undo would surprise
  consumers who do want to queue overnight. Consumers who prefer the
  auto-cancel behaviour can write it themselves in one line.
- **Q3 — Cancel API surface.** Chose single-order `cancel_order(int)`
  (Option A). gRPC wire supports batch; keeping it honest at the
  `GrpcClient` layer but exposing single-order publicly matches the
  rest of the library's ergonomics (`buy`, `sell`, `get_positions`
  are all single-shot). Batch can be added later without breaking
  changes.
- **Outcome name.** `QUEUED` rather than `PENDING`. `PendingOrder`
  already refers to limit/stop orders; overloading "pending" in two
  different meanings is a footgun.
- **Detection timing.** 500 ms sleep before the second probe. Chosen
  for a worst case of one full second of added latency on the
  ambiguous path. If the smoke test shows fills propagate slower
  than 500 ms consistently, this can be tightened in implementation.
- **Error classification on cancel.** We don't yet have XTB's error
  code catalog for cancel-time failures (HAR doesn't expose one), so
  `CancelResult.error_code` stays `None` for broker-rejected cancels
  unless we can identify a stable wire code. Free-text
  `grpc-message` goes into `error`. Keeps the library honest — don't
  invent stable codes we haven't verified.
