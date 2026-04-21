# Queued Orders & Cancel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop classifying market-closed orders as phantom `FILLED` results. Detect queued orders via a positions-then-pending-orders probe, surface a new `TradeOutcome.QUEUED` with the broker `order_number`, and add `XTBClient.cancel_order(order_number)` hitting XTB's gRPC `DeleteOrders` endpoint.

**Architecture:** Three-layer additive change. Wire layer: new protobuf builder for `DeleteOrders` (packed repeated uint64) and a shared parser for the `(UUID, order_number)` response shape used by both `NewMarketOrder` and `DeleteOrders`. gRPC client layer: `GrpcTradeResult` grows `order_number`, new `GrpcCancelResult`, new `GrpcClient.cancel_orders(list[int])`. Public surface: `TradeOutcome.QUEUED` value, `TradeResult.order_number` field, new `CancelOutcome` / `CancelResult` models, new `XTBClient.cancel_order(int)` thin-wrapper. Detection lives inside `XTBClient._build_trade_result` — on gRPC success, probe `get_positions()` for a match (→`FILLED`), fall through to `get_orders()` (→`QUEUED`), retry once after 500 ms, then `AMBIGUOUS`.

**Tech Stack:** Python 3.12+, Pydantic v2, pytest + pytest-asyncio + pytest-httpx, httpx. Spec reference: [docs/superpowers/specs/2026-04-21-queued-orders-design.md](../specs/2026-04-21-queued-orders-design.md).

**Context:** HAR analysis (`demo.har` vs `demo_market_closed.har`) proved the gRPC `NewMarketOrder` response is byte-identical for filled vs queued orders — both return `grpc-status 0`, a UUID in field 1, and the broker `order_number` (varint) in field 2.1. Today's code ([src/xtb_api/client.py:464](../../../src/xtb_api/client.py#L464)) calls `_poll_fill_price` on any `grpc-status 0`, which returns `None` for queued orders → the caller gets `TradeResult(status=FILLED, price=None, order_id=UUID)`, a silent lie. The cancel wire (`DeleteOrders`) was captured at 7 bytes for a single cancel: `0a 05 f5 ad eb 9f 03` = `{field 1: packed repeated uint64 = [872077045]}`; response: 48 bytes carrying a cancellation UUID in field 1 and the cancelled order number in field 2.1.

**Corrections vs spec:**

- Spec §5.2 defines `GrpcTradeResult` / `GrpcCancelResult` as `@dataclass(slots=True)`. The existing code in [src/xtb_api/grpc/types.py](../../../src/xtb_api/grpc/types.py) uses Pydantic `BaseModel`. This plan matches the codebase (Pydantic). Existing `GrpcTradeResult.grpc_status` also defaults to `int = 0`, not `int | None`; plan keeps that.
- Spec §7.1 places trade-outcome tests in `tests/test_trade_outcomes.py`. The actual file is [tests/test_client_trade_outcome_mapping.py](../../../tests/test_client_trade_outcome_mapping.py). Detection-flow tests go in a new focused file `tests/test_client_queued_detection.py` to keep `test_client_trade_outcome_mapping.py` stable; regression cases stay where they are.
- Spec §8.4 uses `## [0.8.0]` headings for the changelog. The project's `CHANGELOG.md` is auto-generated in the `## v0.7.2 (2026-04-21)` format from conventional commits; plan matches that style (and conventional-commit prefixes on each task's commit).

---

## File structure

Files created or modified by this plan:

- **Modify** `src/xtb_api/grpc/proto.py` — add `GRPC_DELETE_ORDERS_ENDPOINT`, `build_delete_orders_request`, `parse_new_market_order_response`, `parse_delete_orders_response`.
- **Modify** `src/xtb_api/grpc/types.py` — add `order_number` to `GrpcTradeResult`; add `GrpcCancelResult` model.
- **Modify** `src/xtb_api/grpc/client.py` — replace inline UUID regex in `_parse_trade_response` with `parse_new_market_order_response`; add `cancel_orders(list[int])`.
- **Modify** `src/xtb_api/types/trading.py` — add `TradeOutcome.QUEUED`, `TradeResult.order_number`, `CancelOutcome`, `CancelResult`.
- **Modify** `src/xtb_api/client.py` — detection flow inside `_build_trade_result`; new public `cancel_order` method.
- **Modify** `src/xtb_api/__init__.py` — re-export `CancelResult`, `CancelOutcome`.
- **Modify** `tests/test_proto.py` — grow with three test classes for the new proto helpers.
- **Create** `tests/test_client_queued_detection.py` — detection flow tests with fake WS + fake gRPC.
- **Create** `tests/test_cancel_order.py` — `XTBClient.cancel_order` tests with fake gRPC.
- **Modify** `tests/test_grpc_client.py` — one regression test that `_parse_trade_response` populates `order_number` for a real-shape success response.
- **Modify** `examples/grpc_trade.py` — add a `QUEUED` arm to `describe()`.
- **Create** `examples/cancel_queued_order.py` — minimal "buy AAPL.US outside US hours, cancel if queued" demo.
- **Modify** `README.md` — add a "Queued orders" subsection under Trading.
- **Modify** `CHANGELOG.md` — add a pending v0.8.0 entry (or merge into whatever the next release is).

No module is renamed, deleted, or moved.

---

## Task 1: Build `DeleteOrders` protobuf request

**Files:**
- Modify: `src/xtb_api/grpc/proto.py`
- Test: `tests/test_proto.py`

- [ ] **Step 1: Write the failing test**

Add this class at the bottom of `tests/test_proto.py` (after `TestExtractJwt`):

```python
class TestBuildDeleteOrdersRequest:
    """DeleteOrders request: field 1 = packed repeated uint64 (order numbers).

    Wire reference: captured in demo_market_closed.har entry 3, single cancel
    of order 872077045 produced exactly these 7 payload bytes.
    """

    def test_single_order_matches_har_bytes(self):
        from xtb_api.grpc.proto import build_delete_orders_request

        msg = build_delete_orders_request([872077045])
        # Expected: 0a (field 1, wire 2) 05 (length) f5 ad eb 9f 03 (packed varint 872077045)
        assert msg == bytes.fromhex("0a05f5adeb9f03")

    def test_multiple_orders_packed(self):
        from xtb_api.grpc.proto import build_delete_orders_request

        msg = build_delete_orders_request([1, 127, 128])
        # Packed payload: 01 (varint 1) 7f (varint 127) 80 01 (varint 128) → 4 bytes
        # Full: 0a (tag) 04 (length) 01 7f 80 01
        assert msg == bytes.fromhex("0a04017f8001")

    def test_empty_list_produces_empty_packed_field(self):
        from xtb_api.grpc.proto import build_delete_orders_request

        # field 1 with length 0 is still valid protobuf
        msg = build_delete_orders_request([])
        assert msg == bytes.fromhex("0a00")
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `.venv/bin/python -m pytest tests/test_proto.py::TestBuildDeleteOrdersRequest -v`
Expected: `ImportError` on `build_delete_orders_request` (function does not exist yet).

- [ ] **Step 3: Implement `build_delete_orders_request`**

Insert the following function into `src/xtb_api/grpc/proto.py` directly after `build_create_access_token_request` (around line 147) and before `parse_grpc_frames`:

```python
def build_delete_orders_request(order_numbers: list[int]) -> bytes:
    """Build DeleteOrders protobuf message.

    Wire format (from HAR analysis, single-cancel case):
        Field 1 (bytes, wire type 2): packed repeated uint64 — concatenated
            varints of the broker order numbers to cancel. No inner tags.

    For ``[872077045]`` this produces ``0a 05 f5 ad eb 9f 03`` (7 bytes).
    """
    packed = b"".join(encode_varint(n) for n in order_numbers)
    return encode_field_bytes(1, packed)
```

- [ ] **Step 4: Run the test and confirm it passes**

Run: `.venv/bin/python -m pytest tests/test_proto.py::TestBuildDeleteOrdersRequest -v`
Expected: all three tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/xtb_api/grpc/proto.py tests/test_proto.py
git commit -m "feat(grpc): add build_delete_orders_request for packed cancel wire"
```

---

## Task 2: Add shared response parser for `(UUID, order_number)` shape

Both `NewMarketOrder` and `DeleteOrders` responses share the structure `{field 1: UUID string, field 2: {field 1: uint64 order_number, ...}}`. One shared helper keeps parsing DRY.

**Files:**
- Modify: `src/xtb_api/grpc/proto.py`
- Test: `tests/test_proto.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_proto.py`:

```python
class TestParseNewMarketOrderResponse:
    """Parse the (UUID, order_number) response shape used by NewMarketOrder
    and DeleteOrders. Reference bytes reconstructed from demo_market_closed.har.
    """

    def _build_response(self, uuid_str: str, order_number: int, trailing: bytes = b"") -> bytes:
        """Reconstruct a response frame: field1=UUID bytes, field2={field1=order_number varint, trailing}."""
        from xtb_api.grpc.proto import encode_field_bytes, encode_field_varint

        inner = encode_field_varint(1, order_number) + trailing
        return encode_field_bytes(1, uuid_str.encode("utf-8")) + encode_field_bytes(2, inner)

    def test_extracts_uuid_and_order_number(self):
        from xtb_api.grpc.proto import parse_new_market_order_response

        # Shape of demo_market_closed.har entry 1 (NewMarketOrder response, 46B)
        payload = self._build_response("a4c205ea-84c0-45aa-b0e0-34ef7ce060fe", 872077045)
        assert len(payload) == 46

        order_id, order_number = parse_new_market_order_response(payload)
        assert order_id == "a4c205ea-84c0-45aa-b0e0-34ef7ce060fe"
        assert order_number == 872077045

    def test_empty_payload_returns_none_tuple(self):
        from xtb_api.grpc.proto import parse_new_market_order_response

        assert parse_new_market_order_response(b"") == (None, None)

    def test_uuid_only_no_order_number(self):
        from xtb_api.grpc.proto import encode_field_bytes, parse_new_market_order_response

        payload = encode_field_bytes(1, b"deadbeef-dead-beef-dead-beefdeadbeef")
        order_id, order_number = parse_new_market_order_response(payload)
        assert order_id == "deadbeef-dead-beef-dead-beefdeadbeef"
        assert order_number is None

    def test_falls_back_to_regex_when_field1_is_not_utf8(self):
        from xtb_api.grpc.proto import encode_field_bytes, parse_new_market_order_response

        # Simulate a future wire change where the UUID is nested deeper — the
        # parser must still find it via a regex sweep so we don't silently
        # regress against captures where field 1 shape changes.
        hidden = b"\xff\xfe" + b"a4c205ea-84c0-45aa-b0e0-34ef7ce060fe".ljust(40, b"\x00")
        payload = encode_field_bytes(99, hidden)
        order_id, _ = parse_new_market_order_response(payload)
        assert order_id == "a4c205ea-84c0-45aa-b0e0-34ef7ce060fe"


class TestParseDeleteOrdersResponse:
    """DeleteOrders response shape matches NewMarketOrder — same helper."""

    def test_extracts_cancellation_uuid_and_order_number(self):
        from xtb_api.grpc.proto import (
            encode_field_bytes,
            encode_field_varint,
            parse_delete_orders_response,
        )

        # Shape of demo_market_closed.har entry 3 (DeleteOrders response, 48B).
        # Nested field 2 carries order_number plus an empty field 2 bytes — reproduce
        # the trailing "12 00" seen in the capture.
        inner = encode_field_varint(1, 872077045) + encode_field_bytes(2, b"")
        payload = encode_field_bytes(1, b"9e5b4600-2ecb-4e4b-a92c-e465367a80f9") + encode_field_bytes(2, inner)
        assert len(payload) == 48

        cancellation_id, order_number = parse_delete_orders_response(payload)
        assert cancellation_id == "9e5b4600-2ecb-4e4b-a92c-e465367a80f9"
        assert order_number == 872077045
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `.venv/bin/python -m pytest tests/test_proto.py::TestParseNewMarketOrderResponse tests/test_proto.py::TestParseDeleteOrdersResponse -v`
Expected: `ImportError` on `parse_new_market_order_response` / `parse_delete_orders_response`.

- [ ] **Step 3: Implement the shared parser + two thin wrappers**

Add to `src/xtb_api/grpc/proto.py` directly after `extract_jwt` (around line 215), before the side constants:

```python
_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)


def _parse_uuid_and_order_number(payload: bytes) -> tuple[str | None, int | None]:
    """Shared parser for the (UUID, order_number) response shape.

    Used by both NewMarketOrder and DeleteOrders responses:

        { field 1: UUID string,
          field 2: { field 1: uint64 order_number, ... } }

    Field 1 is parsed as UTF-8 first; if it doesn't decode cleanly the
    helper falls back to a UUID regex sweep over the entire payload so
    wire-shape drift doesn't silently lose the order_id.
    """
    if not payload:
        return None, None

    fields = parse_proto_fields(payload)
    order_id: str | None = None
    order_number: int | None = None

    field1 = fields.get(1)
    if field1:
        _, raw = field1[0]
        if isinstance(raw, bytes):
            try:
                candidate = raw.decode("utf-8")
                # Accept it as the order_id regardless of format — XTB has used
                # UUIDs consistently so far, but the parser shouldn't reject
                # valid strings just because they don't match a pattern.
                order_id = candidate
            except UnicodeDecodeError:
                order_id = None

    field2 = fields.get(2)
    if field2:
        _, nested = field2[0]
        if isinstance(nested, bytes):
            inner = parse_proto_fields(nested)
            inner1 = inner.get(1)
            if inner1:
                _, v = inner1[0]
                if isinstance(v, int):
                    order_number = v

    # Regex fallback: if we failed to pull order_id from field 1 (wire drift),
    # scan the raw bytes for a UUID.
    if order_id is None:
        match = _UUID_RE.search(payload.decode("latin-1"))
        if match:
            order_id = match.group(0)

    return order_id, order_number


def parse_new_market_order_response(payload: bytes) -> tuple[str | None, int | None]:
    """Parse a NewMarketOrder data-frame payload to ``(order_id, order_number)``."""
    return _parse_uuid_and_order_number(payload)


def parse_delete_orders_response(payload: bytes) -> tuple[str | None, int | None]:
    """Parse a DeleteOrders data-frame payload to ``(cancellation_id, order_number)``."""
    return _parse_uuid_and_order_number(payload)
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `.venv/bin/python -m pytest tests/test_proto.py::TestParseNewMarketOrderResponse tests/test_proto.py::TestParseDeleteOrdersResponse -v`
Expected: all 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/xtb_api/grpc/proto.py tests/test_proto.py
git commit -m "feat(grpc): add shared (UUID, order_number) response parser"
```

---

## Task 3: Add `GRPC_DELETE_ORDERS_ENDPOINT` constant

**Files:**
- Modify: `src/xtb_api/grpc/proto.py`
- Test: `tests/test_proto.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_proto.py`:

```python
class TestEndpoints:
    """Endpoint constants must match the xStation5 HAR-captured URLs."""

    def test_delete_orders_endpoint_matches_xstation5_url(self):
        from xtb_api.grpc.proto import GRPC_DELETE_ORDERS_ENDPOINT

        assert GRPC_DELETE_ORDERS_ENDPOINT == (
            "https://ipax.xtb.com/"
            "pl.xtb.ipax.pub.grpc.cashtradingneworder.v1.CashTradingNewOrderService/DeleteOrders"
        )
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `.venv/bin/python -m pytest tests/test_proto.py::TestEndpoints -v`
Expected: `ImportError`.

- [ ] **Step 3: Add the constant**

Append to the endpoints block at the bottom of `src/xtb_api/grpc/proto.py`, after `GRPC_CLOSE_POSITION_ENDPOINT`:

```python
GRPC_DELETE_ORDERS_ENDPOINT = (
    f"{GRPC_BASE_URL}/pl.xtb.ipax.pub.grpc.cashtradingneworder.v1.CashTradingNewOrderService/DeleteOrders"
)
```

- [ ] **Step 4: Run the test and confirm it passes**

Run: `.venv/bin/python -m pytest tests/test_proto.py::TestEndpoints -v`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/xtb_api/grpc/proto.py tests/test_proto.py
git commit -m "feat(grpc): add GRPC_DELETE_ORDERS_ENDPOINT constant"
```

---

## Task 4: Extend `GrpcTradeResult` with `order_number`; add `GrpcCancelResult`

**Files:**
- Modify: `src/xtb_api/grpc/types.py`
- Test: inline doctest-free — covered by later tasks' tests

- [ ] **Step 1: Edit the model**

Replace the entire content of `src/xtb_api/grpc/types.py` with:

```python
"""Result types for gRPC-web trading."""

from __future__ import annotations

from pydantic import BaseModel


class GrpcTradeResult(BaseModel):
    """Result of a gRPC-web trade execution."""

    success: bool
    order_id: str | None = None
    order_number: int | None = None
    grpc_status: int = 0
    error: str | None = None


class GrpcCancelResult(BaseModel):
    """Result of a gRPC-web DeleteOrders call for a single order number."""

    success: bool
    order_number: int
    cancellation_id: str | None = None
    grpc_status: int = 0
    error: str | None = None
```

- [ ] **Step 2: Verify the module imports cleanly**

Run: `.venv/bin/python -c "from xtb_api.grpc.types import GrpcTradeResult, GrpcCancelResult; r = GrpcTradeResult(success=True, order_number=42); print(r.order_number); c = GrpcCancelResult(success=True, order_number=42); print(c.order_number)"`
Expected: prints `42` twice.

- [ ] **Step 3: Run the existing gRPC client tests to confirm no regression**

Run: `.venv/bin/python -m pytest tests/test_grpc_client.py -v`
Expected: all existing tests pass (we only added optional fields).

- [ ] **Step 4: Commit**

```bash
git add src/xtb_api/grpc/types.py
git commit -m "feat(grpc): add order_number on GrpcTradeResult and new GrpcCancelResult"
```

---

## Task 5: Populate `order_number` inside `GrpcClient._parse_trade_response`

**Files:**
- Modify: `src/xtb_api/grpc/client.py`
- Test: `tests/test_grpc_client.py`

- [ ] **Step 1: Locate the current `_parse_trade_response` site**

Read [src/xtb_api/grpc/client.py:275-335](../../../src/xtb_api/grpc/client.py#L275-L335). The current implementation walks gRPC frames, captures the `grpc_status` from the trailer, and runs an inline UUID regex on the data-frame bytes to extract `order_id`. We will replace the inline regex with `parse_new_market_order_response` so `order_number` is captured as well.

- [ ] **Step 2: Write the failing regression test**

Append to `tests/test_grpc_client.py`:

```python
class TestParseTradeResponseExtractsOrderNumber:
    """Regression guard: successful NewMarketOrder responses must populate
    both order_id (UUID) and order_number (uint64) on the GrpcTradeResult.

    Fixture bytes reconstructed from demo_market_closed.har entry 1.
    """

    def _success_response_frame(self) -> bytes:
        from xtb_api.grpc.proto import (
            build_grpc_frame,
            encode_field_bytes,
            encode_field_varint,
        )

        uuid_str = "a4c205ea-84c0-45aa-b0e0-34ef7ce060fe"
        inner = encode_field_varint(1, 872077045)
        data_msg = encode_field_bytes(1, uuid_str.encode("utf-8")) + encode_field_bytes(2, inner)
        data_frame = build_grpc_frame(data_msg)

        # Trailer frame: flag 0x80 + length + "grpc-status:0\r\n"
        trailer = b"grpc-status:0\r\n"
        import struct

        trailer_frame = struct.pack(">BI", 0x80, len(trailer)) + trailer
        return data_frame + trailer_frame

    def test_populates_order_id_and_order_number(self):
        from xtb_api.grpc.client import GrpcClient

        client = GrpcClient(account_number="1")
        result = client._parse_trade_response(self._success_response_frame())

        assert result.success is True
        assert result.order_id == "a4c205ea-84c0-45aa-b0e0-34ef7ce060fe"
        assert result.order_number == 872077045
        assert result.grpc_status == 0
```

- [ ] **Step 3: Run the test and confirm it fails**

Run: `.venv/bin/python -m pytest tests/test_grpc_client.py::TestParseTradeResponseExtractsOrderNumber -v`
Expected: fails because the current implementation never sets `order_number`.

- [ ] **Step 4: Refactor `_parse_trade_response`**

In `src/xtb_api/grpc/client.py`, at the top of the imports section, add:

```python
from xtb_api.grpc.proto import (
    GRPC_AUTH_ENDPOINT,
    GRPC_DELETE_ORDERS_ENDPOINT,
    GRPC_NEW_ORDER_ENDPOINT,
    GRPC_WEB_TEXT_CONTENT_TYPE,
    SIDE_BUY,
    SIDE_SELL,
    build_create_access_token_request,
    build_delete_orders_request,
    build_grpc_web_text_body,
    build_new_market_order,
    extract_jwt,
    parse_delete_orders_response,
    parse_new_market_order_response,
)
```

Then inside `_parse_trade_response`, replace the current success branch (the `if grpc_status == 0:` block that runs the inline UUID regex — around lines 313–321) with:

```python
        # Success requires explicit grpc-status 0 from trailer
        if grpc_status == 0:
            order_id, order_number = parse_new_market_order_response(data_payload)
            logger.info("Trade executed successfully via gRPC")
            return GrpcTradeResult(
                success=True,
                order_id=order_id,
                order_number=order_number,
                grpc_status=0,
            )
```

Remove the now-unused `re` import if `re` isn't used elsewhere in the file (it was only used for the inline UUID regex — check: search for other `re.` usages first, and if none, drop `import re`).

- [ ] **Step 5: Run the new test and the existing gRPC client tests**

Run: `.venv/bin/python -m pytest tests/test_grpc_client.py -v`
Expected: new `TestParseTradeResponseExtractsOrderNumber` passes AND all pre-existing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add src/xtb_api/grpc/client.py tests/test_grpc_client.py
git commit -m "refactor(grpc): extract order_number alongside order_id on trade success"
```

---

## Task 6: Add `GrpcClient.cancel_orders(list[int])`

**Files:**
- Modify: `src/xtb_api/grpc/client.py`
- Test: `tests/test_grpc_client.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_grpc_client.py`:

```python
class TestCancelOrders:
    """GrpcClient.cancel_orders wraps DeleteOrders gRPC."""

    def _success_response(self, cancellation_uuid: str, order_number: int) -> bytes:
        """Build a DeleteOrders success response (data frame + grpc-status:0 trailer)."""
        import base64
        import struct

        from xtb_api.grpc.proto import (
            build_grpc_frame,
            encode_field_bytes,
            encode_field_varint,
        )

        inner = encode_field_varint(1, order_number)
        data_msg = (
            encode_field_bytes(1, cancellation_uuid.encode("utf-8"))
            + encode_field_bytes(2, inner)
        )
        data_frame = build_grpc_frame(data_msg)
        trailer = b"grpc-status:0\r\n"
        trailer_frame = struct.pack(">BI", 0x80, len(trailer)) + trailer
        return base64.b64encode(data_frame + trailer_frame).decode("ascii")

    @pytest.mark.asyncio
    async def test_cancel_single_order_happy_path(
        self, monkeypatch: pytest.MonkeyPatch, httpx_mock
    ) -> None:
        from xtb_api.grpc.client import GrpcClient
        from xtb_api.grpc.proto import GRPC_DELETE_ORDERS_ENDPOINT

        client = GrpcClient(account_number="1")

        # Short-circuit JWT acquisition
        async def _fake_jwt() -> str:
            return "FAKE.JWT.TOKEN"

        monkeypatch.setattr(client, "_ensure_jwt", _fake_jwt)

        httpx_mock.add_response(
            method="POST",
            url=GRPC_DELETE_ORDERS_ENDPOINT,
            text=self._success_response("9e5b4600-2ecb-4e4b-a92c-e465367a80f9", 872077045),
        )

        results = await client.cancel_orders([872077045])

        assert len(results) == 1
        r = results[0]
        assert r.success is True
        assert r.order_number == 872077045
        assert r.cancellation_id == "9e5b4600-2ecb-4e4b-a92c-e465367a80f9"
        assert r.grpc_status == 0

        await client.disconnect()

    @pytest.mark.asyncio
    async def test_cancel_non_zero_grpc_status_marks_failure(
        self, monkeypatch: pytest.MonkeyPatch, httpx_mock
    ) -> None:
        import base64
        import struct

        from xtb_api.grpc.client import GrpcClient
        from xtb_api.grpc.proto import GRPC_DELETE_ORDERS_ENDPOINT, build_grpc_frame

        client = GrpcClient(account_number="1")

        async def _fake_jwt() -> str:
            return "FAKE.JWT.TOKEN"

        monkeypatch.setattr(client, "_ensure_jwt", _fake_jwt)

        # Empty data frame + non-zero grpc-status trailer
        data_frame = build_grpc_frame(b"")
        trailer = b"grpc-status:5\r\ngrpc-message:order not found\r\n"
        trailer_frame = struct.pack(">BI", 0x80, len(trailer)) + trailer
        body = base64.b64encode(data_frame + trailer_frame).decode("ascii")

        httpx_mock.add_response(
            method="POST",
            url=GRPC_DELETE_ORDERS_ENDPOINT,
            text=body,
        )

        results = await client.cancel_orders([42])
        assert len(results) == 1
        r = results[0]
        assert r.success is False
        assert r.grpc_status == 5
        assert r.order_number == 42
        assert r.error is not None and "order not found" in r.error

        await client.disconnect()

    @pytest.mark.asyncio
    async def test_cancel_network_error_returns_failure_with_error(
        self, monkeypatch: pytest.MonkeyPatch, httpx_mock
    ) -> None:
        import httpx

        from xtb_api.grpc.client import GrpcClient
        from xtb_api.grpc.proto import GRPC_DELETE_ORDERS_ENDPOINT

        client = GrpcClient(account_number="1")

        async def _fake_jwt() -> str:
            return "FAKE.JWT.TOKEN"

        monkeypatch.setattr(client, "_ensure_jwt", _fake_jwt)

        httpx_mock.add_exception(
            httpx.ConnectError("boom"),
            method="POST",
            url=GRPC_DELETE_ORDERS_ENDPOINT,
        )

        results = await client.cancel_orders([42])
        assert len(results) == 1
        r = results[0]
        assert r.success is False
        assert r.order_number == 42
        assert r.error is not None and "boom" in r.error

        await client.disconnect()
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `.venv/bin/python -m pytest tests/test_grpc_client.py::TestCancelOrders -v`
Expected: `AttributeError: 'GrpcClient' object has no attribute 'cancel_orders'`.

- [ ] **Step 3: Implement `cancel_orders`**

Add the following method to `GrpcClient` in `src/xtb_api/grpc/client.py`, directly after `execute_order`:

```python
    async def cancel_orders(self, order_numbers: list[int]) -> list[GrpcCancelResult]:
        """Cancel one or more broker orders via DeleteOrders gRPC.

        Input order numbers are sent as a packed repeated uint64 in a single
        wire call. Returns one ``GrpcCancelResult`` per input order number,
        in input order. On network failure every order reports the same
        underlying error string.
        """
        from xtb_api.grpc.types import GrpcCancelResult

        jwt = await self._ensure_jwt()
        logger.info("gRPC cancel: order_numbers=%s", order_numbers)

        proto_msg = build_delete_orders_request(order_numbers)
        body_b64 = build_grpc_web_text_body(proto_msg)

        try:
            response_bytes = await self._grpc_call(GRPC_DELETE_ORDERS_ENDPOINT, body_b64, jwt=jwt)
        except httpx.HTTPError as e:
            logger.warning("gRPC cancel network error: %s", e, exc_info=True)
            return [
                GrpcCancelResult(success=False, order_number=n, error=str(e))
                for n in order_numbers
            ]

        return self._parse_cancel_response(response_bytes, order_numbers)

    def _parse_cancel_response(
        self, response_bytes: bytes, order_numbers: list[int]
    ) -> list[GrpcCancelResult]:
        """Parse a DeleteOrders response into one result per requested order.

        The wire carries one data frame per cancelled order plus one trailer
        frame. A non-zero grpc-status in the trailer applies to every
        requested order (broker-level rejection). An unpaired data frame
        (e.g. partial success) propagates fields from the frame's UUID+number
        onto the matching input order; any unmatched input orders get a
        ``grpc_status``-based failure result.
        """
        import struct

        from xtb_api.grpc.types import GrpcCancelResult

        grpc_status: int | None = None
        grpc_message: str | None = None
        data_frames: list[bytes] = []

        pos = 0
        while pos + 5 <= len(response_bytes):
            flag = response_bytes[pos]
            length = struct.unpack(">I", response_bytes[pos + 1 : pos + 5])[0]
            pos += 5
            if pos + length > len(response_bytes):
                break
            frame_data = response_bytes[pos : pos + length]
            pos += length

            if flag & 0x80:
                trailer_text = frame_data.decode("latin-1", errors="replace")
                for line in trailer_text.split("\r\n"):
                    if line.startswith("grpc-status:"):
                        with contextlib.suppress(ValueError):
                            grpc_status = int(line.split(":", 1)[1].strip())
                    elif line.startswith("grpc-message:"):
                        grpc_message = line.split(":", 1)[1].strip()
            else:
                data_frames.append(frame_data)

        # Build a lookup of parsed data frames by order_number
        parsed: dict[int, str | None] = {}
        for frame in data_frames:
            cancellation_id, order_number = parse_delete_orders_response(frame)
            if order_number is not None:
                parsed[order_number] = cancellation_id

        status = grpc_status if grpc_status is not None else 0
        results: list[GrpcCancelResult] = []
        for n in order_numbers:
            if status == 0 and n in parsed:
                results.append(
                    GrpcCancelResult(
                        success=True,
                        order_number=n,
                        cancellation_id=parsed[n],
                        grpc_status=0,
                    )
                )
            else:
                error_msg = grpc_message or f"gRPC cancel failed (status={status})"
                results.append(
                    GrpcCancelResult(
                        success=False,
                        order_number=n,
                        grpc_status=status,
                        error=error_msg,
                    )
                )
        return results
```

- [ ] **Step 4: Run the cancel tests and confirm they pass**

Run: `.venv/bin/python -m pytest tests/test_grpc_client.py::TestCancelOrders -v`
Expected: all three tests pass.

- [ ] **Step 5: Run the full gRPC client test module to confirm no regression**

Run: `.venv/bin/python -m pytest tests/test_grpc_client.py -v`
Expected: everything green.

- [ ] **Step 6: Commit**

```bash
git add src/xtb_api/grpc/client.py tests/test_grpc_client.py
git commit -m "feat(grpc): add cancel_orders hitting DeleteOrders with packed uint64"
```

---

## Task 7: Add `TradeOutcome.QUEUED`, `TradeResult.order_number`, and cancel types

**Files:**
- Modify: `src/xtb_api/types/trading.py`
- Test: `tests/test_trade_outcome.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_trade_outcome.py`:

```python
class TestQueuedOutcome:
    def test_queued_is_distinct_and_not_success(self):
        from xtb_api.types.trading import TradeOutcome, TradeResult

        assert TradeOutcome.QUEUED.value == "QUEUED"
        r = TradeResult(
            status=TradeOutcome.QUEUED,
            symbol="AAPL.US",
            side="buy",
            volume=1.0,
            order_id="abc",
            order_number=872077045,
        )
        assert r.status is TradeOutcome.QUEUED
        assert r.success is False
        assert r.order_number == 872077045

    def test_order_number_defaults_to_none(self):
        from xtb_api.types.trading import TradeOutcome, TradeResult

        r = TradeResult(status=TradeOutcome.REJECTED, symbol="X", side="buy", volume=1.0)
        assert r.order_number is None


class TestCancelOutcomeAndResult:
    def test_cancel_outcome_values(self):
        from xtb_api.types.trading import CancelOutcome

        assert CancelOutcome.CANCELLED.value == "CANCELLED"
        assert CancelOutcome.REJECTED.value == "REJECTED"
        assert CancelOutcome.AMBIGUOUS.value == "AMBIGUOUS"

    def test_cancel_result_success_property(self):
        from xtb_api.types.trading import CancelOutcome, CancelResult

        ok = CancelResult(
            status=CancelOutcome.CANCELLED,
            order_number=42,
            cancellation_id="uuid",
        )
        assert ok.success is True

        bad = CancelResult(status=CancelOutcome.REJECTED, order_number=42)
        assert bad.success is False

    def test_cancel_result_rejects_extra_fields(self):
        import pydantic

        from xtb_api.types.trading import CancelOutcome, CancelResult

        with pytest.raises(pydantic.ValidationError):
            CancelResult(
                status=CancelOutcome.CANCELLED,
                order_number=42,
                extra_garbage="no",  # type: ignore[call-arg]
            )
```

If the file does not already import `pytest`, add `import pytest` at the top.

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `.venv/bin/python -m pytest tests/test_trade_outcome.py::TestQueuedOutcome tests/test_trade_outcome.py::TestCancelOutcomeAndResult -v`
Expected: `ImportError` on `CancelOutcome` / `CancelResult`; `AttributeError` on `TradeOutcome.QUEUED`; `TypeError` on `order_number=` kwarg.

- [ ] **Step 3: Extend `src/xtb_api/types/trading.py`**

Make the following changes in `src/xtb_api/types/trading.py`:

(a) Add `QUEUED` to `TradeOutcome` — replace the existing enum block with:

```python
class TradeOutcome(StrEnum):
    """Typed outcome of a trade request.

    Values:
    - ``FILLED`` — broker confirmed the order, position is open.
    - ``QUEUED`` — broker accepted the order but did not fill (typically
      because the instrument's market is closed). The order is live on
      the broker side until market open or an explicit cancel. Use
      ``XTBClient.cancel_order(result.order_number)`` to kill it.
    - ``REJECTED`` — broker refused (bad symbol, insufficient funds, etc.).
    - ``AMBIGUOUS`` — network or protocol failure after the send; the trade
      may or may not have been placed. Caller must reconcile via
      ``get_positions()`` / ``get_orders()``.
    - ``INSUFFICIENT_VOLUME`` — local pre-check: volume rounds to < 1.
    - ``AUTH_EXPIRED`` — JWT/TGT rejected (RBAC). Should be retried by the
      library; only surfaced if retry also fails.
    - ``RATE_LIMITED`` — broker throttled the request.
    - ``TIMEOUT`` — request exceeded its deadline.
    """

    FILLED = "FILLED"
    QUEUED = "QUEUED"
    REJECTED = "REJECTED"
    AMBIGUOUS = "AMBIGUOUS"
    INSUFFICIENT_VOLUME = "INSUFFICIENT_VOLUME"
    AUTH_EXPIRED = "AUTH_EXPIRED"
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT = "TIMEOUT"
```

(b) Add `order_number: int | None = None` to `TradeResult` — update the field list and docstring:

```python
class TradeResult(BaseModel):
    """Trade execution result.

    ``status`` is the authoritative field. ``success`` is a convenience
    property equivalent to ``status is TradeOutcome.FILLED`` and is kept
    for one-line checks.

    Fields:
        status: TradeOutcome — the typed result category.
        order_id: broker-assigned UUID string, if known.
        order_number: broker-assigned integer order number, if known.
            Feed into ``XTBClient.cancel_order`` to cancel a queued order.
        symbol: the symbol traded.
        side: "buy" or "sell".
        volume: requested volume (post-rounding for the < 1 check).
        price: fill price, if observable via a position poll.
        error: free-text error message from the broker (if any).
        error_code: stable short code for the outcome flavor. Examples:
            "INSUFFICIENT_VOLUME", "RBAC_DENIED", "AMBIGUOUS_NO_RESPONSE",
            "FILL_PRICE_UNKNOWN", "FILL_STATE_UNKNOWN", "NETWORK_ERROR".
            May also carry the raw broker code when one is surfaced.
    """

    model_config = {"extra": "forbid"}

    status: TradeOutcome
    symbol: str
    side: Literal["buy", "sell"]
    volume: float | None = None
    price: float | None = None
    order_id: str | None = None
    order_number: int | None = None
    error: str | None = None
    error_code: str | None = None

    @property
    def success(self) -> bool:
        """True iff ``status is TradeOutcome.FILLED``."""
        return self.status is TradeOutcome.FILLED
```

(c) Add cancel types at the bottom of the file (after `TradeResult`):

```python
class CancelOutcome(StrEnum):
    """Typed outcome of a cancel request.

    Values:
    - ``CANCELLED`` — broker accepted the cancel (grpc-status 0).
    - ``REJECTED`` — broker refused. Common cases: the order already
      filled between the trade request and the cancel, or the order
      number is unknown.
    - ``AMBIGUOUS`` — network or protocol failure; caller should
      reconcile via ``get_orders()``.
    """

    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    AMBIGUOUS = "AMBIGUOUS"


class CancelResult(BaseModel):
    """Cancel execution result.

    ``status`` is the authoritative field. ``success`` is a convenience
    property equivalent to ``status is CancelOutcome.CANCELLED``.
    """

    model_config = {"extra": "forbid"}

    status: CancelOutcome
    order_number: int
    cancellation_id: str | None = None
    error: str | None = None
    error_code: str | None = None

    @property
    def success(self) -> bool:
        """True iff ``status is CancelOutcome.CANCELLED``."""
        return self.status is CancelOutcome.CANCELLED
```

- [ ] **Step 4: Run the new tests and confirm they pass**

Run: `.venv/bin/python -m pytest tests/test_trade_outcome.py::TestQueuedOutcome tests/test_trade_outcome.py::TestCancelOutcomeAndResult -v`
Expected: all tests pass.

- [ ] **Step 5: Run the full trading-type test modules**

Run: `.venv/bin/python -m pytest tests/test_trade_outcome.py tests/test_trade_outcome_match.py tests/test_ws_trade_result_shape.py -v`
Expected: everything green — existing tests that did not reference `QUEUED` or `order_number` are unaffected.

- [ ] **Step 6: Commit**

```bash
git add src/xtb_api/types/trading.py tests/test_trade_outcome.py
git commit -m "feat(types): add TradeOutcome.QUEUED, order_number, CancelResult"
```

---

## Task 8: Detection flow in `XTBClient._build_trade_result`

**Files:**
- Modify: `src/xtb_api/client.py`
- Create: `tests/test_client_queued_detection.py`

- [ ] **Step 1: Write the failing tests in a new file**

Create `tests/test_client_queued_detection.py`:

```python
"""Detection flow: classify gRPC-successful orders as FILLED / QUEUED / AMBIGUOUS.

The gRPC NewMarketOrder response is byte-identical for filled vs queued orders;
XTBClient._build_trade_result uses get_positions() / get_orders() as the
tie-breaker. See spec §2 for the full probe sequence.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from xtb_api.client import XTBClient
from xtb_api.types.trading import PendingOrder, Position, TradeOutcome


def _make_client(monkeypatch: pytest.MonkeyPatch) -> XTBClient:
    c = XTBClient(email="x@y.z", password="p", account_number=1, session_file=None)
    c._auth = MagicMock()
    c._ws = MagicMock()
    c._ws.get_positions = AsyncMock(return_value=[])
    c._ws.get_orders = AsyncMock(return_value=[])
    fake_grpc = MagicMock()
    fake_grpc.execute_order = AsyncMock()
    fake_grpc.invalidate_jwt = MagicMock()
    monkeypatch.setattr(c, "_ensure_grpc", lambda: fake_grpc)
    monkeypatch.setattr(c, "_resolve_instrument_id", AsyncMock(return_value=42))
    # Disable the 500 ms sleep in tests — nothing depends on real time.
    monkeypatch.setattr("xtb_api.client.asyncio.sleep", AsyncMock(return_value=None))
    c._fake_grpc = fake_grpc  # type: ignore[attr-defined]
    return c


@pytest.mark.asyncio
async def test_filled_order_matched_by_position(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _make_client(monkeypatch)
    client._fake_grpc.execute_order = AsyncMock(  # type: ignore[attr-defined]
        return_value=MagicMock(
            success=True,
            order_id="UUID-1",
            order_number=872069505,
            error=None,
            grpc_status=0,
        )
    )
    pos = Position(
        symbol="CIG.PL",
        volume=1,
        open_price=10.0,
        current_price=10.0,
        side="buy",
        order_id="UUID-1",
    )
    client._ws.get_positions = AsyncMock(return_value=[pos])

    result = await client.buy("CIG.PL", volume=1)

    assert result.status is TradeOutcome.FILLED
    assert result.order_id == "UUID-1"
    assert result.order_number == 872069505
    # get_orders should not even be consulted on the filled path
    client._ws.get_orders.assert_not_awaited()


@pytest.mark.asyncio
async def test_queued_order_matched_by_pending_orders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _make_client(monkeypatch)
    client._fake_grpc.execute_order = AsyncMock(  # type: ignore[attr-defined]
        return_value=MagicMock(
            success=True,
            order_id="UUID-2",
            order_number=872077045,
            error=None,
            grpc_status=0,
        )
    )
    client._ws.get_positions = AsyncMock(return_value=[])
    pending = PendingOrder(
        symbol="AAPL.US",
        volume=1,
        price=0.0,
        side="buy",
        order_id="872077045",
    )
    client._ws.get_orders = AsyncMock(return_value=[pending])

    result = await client.buy("AAPL.US", volume=1)

    assert result.status is TradeOutcome.QUEUED
    assert result.order_number == 872077045
    assert result.order_id == "UUID-2"
    assert result.error_code is None


@pytest.mark.asyncio
async def test_neither_position_nor_order_is_ambiguous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _make_client(monkeypatch)
    client._fake_grpc.execute_order = AsyncMock(  # type: ignore[attr-defined]
        return_value=MagicMock(
            success=True,
            order_id="UUID-3",
            order_number=999,
            error=None,
            grpc_status=0,
        )
    )
    client._ws.get_positions = AsyncMock(return_value=[])
    client._ws.get_orders = AsyncMock(return_value=[])

    result = await client.buy("AAPL.US", volume=1)

    assert result.status is TradeOutcome.AMBIGUOUS
    assert result.error_code == "FILL_STATE_UNKNOWN"
    # The probe must retry once (second pass after the 500 ms sleep).
    assert client._ws.get_positions.await_count == 2
    assert client._ws.get_orders.await_count == 2


@pytest.mark.asyncio
async def test_get_positions_failure_falls_through_to_orders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _make_client(monkeypatch)
    client._fake_grpc.execute_order = AsyncMock(  # type: ignore[attr-defined]
        return_value=MagicMock(
            success=True,
            order_id="UUID-4",
            order_number=111,
            error=None,
            grpc_status=0,
        )
    )
    client._ws.get_positions = AsyncMock(side_effect=RuntimeError("ws bounced"))
    pending = PendingOrder(
        symbol="AAPL.US",
        volume=1,
        price=0.0,
        side="buy",
        order_id="111",
    )
    client._ws.get_orders = AsyncMock(return_value=[pending])

    result = await client.buy("AAPL.US", volume=1)

    assert result.status is TradeOutcome.QUEUED
    assert result.order_number == 111


@pytest.mark.asyncio
async def test_both_probes_raising_gives_ambiguous_with_underlying_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _make_client(monkeypatch)
    client._fake_grpc.execute_order = AsyncMock(  # type: ignore[attr-defined]
        return_value=MagicMock(
            success=True,
            order_id="UUID-5",
            order_number=222,
            error=None,
            grpc_status=0,
        )
    )
    client._ws.get_positions = AsyncMock(side_effect=RuntimeError("pos bounced"))
    client._ws.get_orders = AsyncMock(side_effect=RuntimeError("orders bounced"))

    result = await client.buy("AAPL.US", volume=1)

    assert result.status is TradeOutcome.AMBIGUOUS
    assert result.error_code == "FILL_STATE_UNKNOWN"
    assert result.error is not None and ("pos bounced" in result.error or "orders bounced" in result.error)
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `.venv/bin/python -m pytest tests/test_client_queued_detection.py -v`
Expected: the filled test passes (already works via existing `_find_matching_position` path); queued/ambiguous/fallthrough tests fail because `_build_trade_result` does not yet probe `get_orders()` or distinguish QUEUED.

- [ ] **Step 3: Rewrite `_build_trade_result` with the detection flow**

Open `src/xtb_api/client.py` and locate `_build_trade_result` (around line 456). Replace the entire method with:

```python
    async def _build_trade_result(
        self,
        grpc_result: Any,
        symbol: str,
        side_str: Literal["buy", "sell"],
        volume: int,
    ) -> TradeResult:
        """Map a GrpcTradeResult to a typed TradeResult.

        On gRPC success the wire is ambiguous (filled and queued orders return
        an identical shape), so we probe the WS-side `get_positions()` and
        `get_orders()` to classify the outcome. See spec §2.
        """
        order_number: int | None = getattr(grpc_result, "order_number", None)

        if grpc_result.success:
            return await self._classify_accepted_trade(
                symbol=symbol,
                side_str=side_str,
                volume=volume,
                order_id=grpc_result.order_id,
                order_number=order_number,
            )

        # Non-success: categorize by grpc_status / error text.
        status_code = getattr(grpc_result, "grpc_status", 0) or 0
        err_text = grpc_result.error or ""
        if status_code == 7:
            outcome = TradeOutcome.AUTH_EXPIRED
            error_code: str | None = "RBAC_DENIED"
        else:
            outcome = TradeOutcome.REJECTED
            error_code = None

        return TradeResult(
            status=outcome,
            symbol=symbol,
            side=side_str,
            volume=float(volume),
            order_id=grpc_result.order_id,
            order_number=order_number,
            error=err_text or None,
            error_code=error_code,
        )

    async def _classify_accepted_trade(
        self,
        *,
        symbol: str,
        side_str: Literal["buy", "sell"],
        volume: int,
        order_id: str | None,
        order_number: int | None,
    ) -> TradeResult:
        """Decide FILLED vs QUEUED vs AMBIGUOUS after a gRPC-accepted order.

        Probe 1: positions match by (symbol, side, volume) → FILLED.
        Probe 2: pending orders match by order_id == str(order_number) → QUEUED.
        Retry both probes once after 500 ms. Then AMBIGUOUS.
        """
        last_exc: str | None = None

        for attempt in range(2):
            if attempt == 1:
                await asyncio.sleep(0.5)

            try:
                position = await self._find_matching_position(symbol, volume, side_str)
            except Exception as exc:  # noqa: BLE001 — broad by design; we fall through
                logger.warning("get_positions probe failed: %s", exc)
                position = None
                last_exc = str(exc)

            if position is not None:
                fill_price, fill_code = await self._poll_fill_price(symbol)
                return TradeResult(
                    status=TradeOutcome.FILLED,
                    symbol=symbol,
                    side=side_str,
                    volume=float(volume),
                    price=fill_price,
                    order_id=order_id,
                    order_number=order_number,
                    error=None,
                    error_code=fill_code,
                )

            if order_number is not None:
                try:
                    orders = await self._ws.get_orders()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("get_orders probe failed: %s", exc)
                    orders = []
                    last_exc = str(exc)

                target = str(order_number)
                if any(o.order_id == target for o in orders):
                    return TradeResult(
                        status=TradeOutcome.QUEUED,
                        symbol=symbol,
                        side=side_str,
                        volume=float(volume),
                        order_id=order_id,
                        order_number=order_number,
                    )

        err_msg = (
            f"gRPC accepted order (order_id={order_id}, order_number={order_number}) "
            "but neither a matching position nor a pending order was found"
        )
        if last_exc:
            err_msg = f"{err_msg}; last probe error: {last_exc}"
        logger.warning(err_msg)
        return TradeResult(
            status=TradeOutcome.AMBIGUOUS,
            symbol=symbol,
            side=side_str,
            volume=float(volume),
            order_id=order_id,
            order_number=order_number,
            error=err_msg,
            error_code="FILL_STATE_UNKNOWN",
        )
```

- [ ] **Step 4: Run the detection tests and confirm they pass**

Run: `.venv/bin/python -m pytest tests/test_client_queued_detection.py -v`
Expected: all 5 tests pass.

- [ ] **Step 5: Run the existing trade-outcome-mapping and idempotent-retry tests to confirm no regression**

Run: `.venv/bin/python -m pytest tests/test_client_trade_outcome_mapping.py tests/test_client_idempotent_retry.py tests/test_client_fill_price.py -v`
Expected: everything green. If any existing test expected `order_number is None` on a `FILLED` result, update it to accept the new populated value — but do not remove test coverage.

- [ ] **Step 6: Commit**

```bash
git add src/xtb_api/client.py tests/test_client_queued_detection.py
git commit -m "feat(client): detect QUEUED market-closed orders via positions+orders probe

Before: grpc-status 0 was treated as FILLED even for market-closed orders
that XTB had merely queued, producing TradeResult(status=FILLED, price=None)
— a silent misclassification.

After: on gRPC success, probe get_positions() for a match (FILLED), then
get_orders() keyed by order_number (QUEUED), retrying once after 500 ms
before settling on AMBIGUOUS with error_code=FILL_STATE_UNKNOWN."
```

---

## Task 9: `XTBClient.cancel_order(order_number)` public method

**Files:**
- Modify: `src/xtb_api/client.py`
- Create: `tests/test_cancel_order.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cancel_order.py`:

```python
"""XTBClient.cancel_order wraps GrpcClient.cancel_orders for a single order."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from xtb_api.client import XTBClient
from xtb_api.grpc.types import GrpcCancelResult
from xtb_api.types.trading import CancelOutcome


def _make_client(monkeypatch: pytest.MonkeyPatch) -> XTBClient:
    c = XTBClient(email="x@y.z", password="p", account_number=1, session_file=None)
    c._auth = MagicMock()
    c._ws = MagicMock()
    fake_grpc = MagicMock()
    fake_grpc.cancel_orders = AsyncMock()
    monkeypatch.setattr(c, "_ensure_grpc", lambda: fake_grpc)
    c._fake_grpc = fake_grpc  # type: ignore[attr-defined]
    return c


@pytest.mark.asyncio
async def test_cancel_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client(monkeypatch)
    client._fake_grpc.cancel_orders = AsyncMock(  # type: ignore[attr-defined]
        return_value=[
            GrpcCancelResult(
                success=True,
                order_number=872077045,
                cancellation_id="9e5b4600-2ecb-4e4b-a92c-e465367a80f9",
                grpc_status=0,
            )
        ]
    )

    result = await client.cancel_order(872077045)

    assert result.status is CancelOutcome.CANCELLED
    assert result.order_number == 872077045
    assert result.cancellation_id == "9e5b4600-2ecb-4e4b-a92c-e465367a80f9"
    assert result.success is True
    client._fake_grpc.cancel_orders.assert_awaited_once_with([872077045])  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_cancel_rejected_order_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _make_client(monkeypatch)
    client._fake_grpc.cancel_orders = AsyncMock(  # type: ignore[attr-defined]
        return_value=[
            GrpcCancelResult(
                success=False,
                order_number=42,
                grpc_status=5,
                error="order not found",
            )
        ]
    )

    result = await client.cancel_order(42)

    assert result.status is CancelOutcome.REJECTED
    assert result.order_number == 42
    assert result.cancellation_id is None
    assert result.error == "order not found"
    assert result.success is False


@pytest.mark.asyncio
async def test_cancel_rbac_denied_marks_rejected_with_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _make_client(monkeypatch)
    client._fake_grpc.cancel_orders = AsyncMock(  # type: ignore[attr-defined]
        return_value=[
            GrpcCancelResult(
                success=False,
                order_number=42,
                grpc_status=7,
                error="rbac denied",
            )
        ]
    )

    result = await client.cancel_order(42)

    assert result.status is CancelOutcome.REJECTED
    assert result.error_code == "RBAC_DENIED"


@pytest.mark.asyncio
async def test_cancel_network_failure_is_ambiguous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _make_client(monkeypatch)
    # GrpcClient.cancel_orders returns success=False with a network-error
    # string (grpc_status=0 since no trailer was ever observed).
    client._fake_grpc.cancel_orders = AsyncMock(  # type: ignore[attr-defined]
        return_value=[
            GrpcCancelResult(
                success=False,
                order_number=42,
                grpc_status=0,
                error="ConnectError: boom",
            )
        ]
    )

    result = await client.cancel_order(42)

    assert result.status is CancelOutcome.AMBIGUOUS
    assert result.error_code == "AMBIGUOUS_NO_RESPONSE"
    assert result.error is not None and "boom" in result.error
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `.venv/bin/python -m pytest tests/test_cancel_order.py -v`
Expected: `AttributeError: 'XTBClient' object has no attribute 'cancel_order'`.

- [ ] **Step 3: Implement `XTBClient.cancel_order`**

In `src/xtb_api/client.py`, add to the imports at the top:

```python
from xtb_api.types.trading import (
    AccountBalance,
    CancelOutcome,
    CancelResult,
    PendingOrder,
    Position,
    TradeOptions,
    TradeOutcome,
    TradeResult,
)
```

Then append this method to `XTBClient` just after `sell` (around line 215), in the Trading section:

```python
    async def cancel_order(self, order_number: int) -> CancelResult:
        """Cancel a queued or pending broker order by its order number.

        Pass the ``order_number`` from a ``TradeResult`` (populated on
        both FILLED and QUEUED outcomes). Returns a typed
        :class:`CancelResult` whose ``status`` is a :class:`CancelOutcome`.

        ``CancelOutcome.REJECTED`` is a common and expected outcome — if
        the order filled between the trade request and the cancel, the
        broker has no queued order left to cancel.
        """
        grpc = self._ensure_grpc()
        grpc_results = await grpc.cancel_orders([order_number])
        grpc_result = grpc_results[0]

        if grpc_result.success:
            return CancelResult(
                status=CancelOutcome.CANCELLED,
                order_number=grpc_result.order_number,
                cancellation_id=grpc_result.cancellation_id,
            )

        # Network failures leave grpc_status=0 (no trailer observed); broker
        # rejections carry a non-zero grpc_status from the trailer.
        if grpc_result.grpc_status == 0:
            return CancelResult(
                status=CancelOutcome.AMBIGUOUS,
                order_number=grpc_result.order_number,
                error=grpc_result.error,
                error_code="AMBIGUOUS_NO_RESPONSE",
            )

        error_code: str | None = None
        if grpc_result.grpc_status == 7:
            error_code = "RBAC_DENIED"

        return CancelResult(
            status=CancelOutcome.REJECTED,
            order_number=grpc_result.order_number,
            error=grpc_result.error,
            error_code=error_code,
        )
```

- [ ] **Step 4: Run the cancel tests and confirm they pass**

Run: `.venv/bin/python -m pytest tests/test_cancel_order.py -v`
Expected: all 4 tests pass.

- [ ] **Step 5: Run the existing client test modules as a regression check**

Run: `.venv/bin/python -m pytest tests/test_client.py tests/test_client_trade_outcome_mapping.py tests/test_client_queued_detection.py -v`
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add src/xtb_api/client.py tests/test_cancel_order.py
git commit -m "feat(client): add XTBClient.cancel_order for queued-order cancellation"
```

---

## Task 10: Re-export `CancelResult` and `CancelOutcome`

**Files:**
- Modify: `src/xtb_api/__init__.py`

- [ ] **Step 1: Write the failing import test**

Append to `tests/test_version.py` (or create a small new `tests/test_public_api.py` if you prefer — see step 2 for the preferred path):

```python
class TestPublicCancelReExports:
    def test_cancel_symbols_importable_from_package_root(self):
        from xtb_api import CancelOutcome, CancelResult, TradeOutcome

        assert CancelOutcome.CANCELLED.value == "CANCELLED"
        assert CancelResult is not None
        # QUEUED was added alongside cancel — same gate.
        assert TradeOutcome.QUEUED.value == "QUEUED"
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `.venv/bin/python -m pytest tests/test_version.py::TestPublicCancelReExports -v`
Expected: `ImportError: cannot import name 'CancelOutcome'`.

- [ ] **Step 3: Update `src/xtb_api/__init__.py`**

Extend the imports from `xtb_api.types.trading`:

```python
from xtb_api.types.trading import (
    AccountBalance,
    CancelOutcome,
    CancelResult,
    PendingOrder,
    Position,
    TradeOptions,
    TradeOutcome,
    TradeResult,
)
```

Add `"CancelResult"` and `"CancelOutcome"` to the `__all__` list under the `# Data models` grouping — place them alphabetically after `AccountBalance`:

```python
    # Data models
    "Position",
    "PendingOrder",
    "AccountBalance",
    "CancelResult",
    "CancelOutcome",
    "TradeResult",
    "TradeOutcome",
    "TradeOptions",
    "Quote",
    "InstrumentSearchResult",
```

- [ ] **Step 4: Run the test and confirm it passes**

Run: `.venv/bin/python -m pytest tests/test_version.py::TestPublicCancelReExports -v`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/xtb_api/__init__.py tests/test_version.py
git commit -m "feat(api): re-export CancelResult and CancelOutcome from package root"
```

---

## Task 11: Add `QUEUED` arm in `examples/grpc_trade.py`

**Files:**
- Modify: `examples/grpc_trade.py`

- [ ] **Step 1: Read the current describe() match block**

Open [examples/grpc_trade.py](../../../examples/grpc_trade.py). The `describe()` function matches every `TradeOutcome` value except `QUEUED`, which is new. Without an arm for `QUEUED`, the match expression will return `None` for queued orders — misleading.

- [ ] **Step 2: Add the `QUEUED` case**

Insert a new case in the `describe()` match block, directly after `case TradeOutcome.FILLED:`:

```python
        case TradeOutcome.QUEUED:
            return (
                f"QUEUED  order={result.order_id}  order_number={result.order_number}"
                f"  — market closed; order will fill when market opens. "
                f"Cancel with: await client.cancel_order({result.order_number})"
            )
```

- [ ] **Step 3: Verify the file still imports cleanly and is runnable (syntax-only check)**

Run: `.venv/bin/python -c "import ast; ast.parse(open('examples/grpc_trade.py').read())"`
Expected: no output (clean parse).

- [ ] **Step 4: Commit**

```bash
git add examples/grpc_trade.py
git commit -m "docs(examples): show QUEUED branch in grpc_trade example"
```

---

## Task 12: New `examples/cancel_queued_order.py`

**Files:**
- Create: `examples/cancel_queued_order.py`

- [ ] **Step 1: Create the example**

Write the following to `examples/cancel_queued_order.py`:

```python
"""Place a buy, cancel it if XTB queued it due to a closed market.

Demonstrates the v1.0 queued-order surface (TradeOutcome.QUEUED +
XTBClient.cancel_order). The classic trigger is placing a BUY on a US
stock outside NASDAQ hours from a non-US timezone — XTB accepts the
order but parks it until market open.

WARNING: this example places a real order. Set XTB_ACCOUNT_TYPE=demo
in your environment unless you deliberately want a live order.

Run with::

    export XTB_EXAMPLE_TRADE=1
    export XTB_ACCOUNT_TYPE=demo
    python examples/cancel_queued_order.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from xtb_api import CancelOutcome, TradeOutcome, XTBClient

SYMBOL = "AAPL.US"
VOLUME = 1


async def main() -> int:
    if os.environ.get("XTB_EXAMPLE_TRADE") != "1":
        print("Refusing to place a real order without XTB_EXAMPLE_TRADE=1 in env.")
        return 2

    client = XTBClient(
        email=os.environ["XTB_EMAIL"],
        password=os.environ["XTB_PASSWORD"],
        account_number=int(os.environ["XTB_ACCOUNT_NUMBER"]),
        totp_secret=os.environ.get("XTB_TOTP_SECRET", ""),
        session_file=Path.home() / ".xtb_session",
    )

    try:
        await client.connect()
        print(f"Placing BUY {SYMBOL} vol={VOLUME} (expecting QUEUED if market is closed)...")

        result = await client.buy(SYMBOL, volume=VOLUME)
        print(f"buy() → status={result.status.value}  order_number={result.order_number}  order_id={result.order_id}")

        if result.status is not TradeOutcome.QUEUED:
            print(f"Not queued (status={result.status.value}); exiting without cancel.")
            return 0

        assert result.order_number is not None
        print(f"Cancelling queued order {result.order_number}...")
        cancel = await client.cancel_order(result.order_number)
        print(
            f"cancel_order() → status={cancel.status.value}  "
            f"cancellation_id={cancel.cancellation_id}  error={cancel.error!r}"
        )
        return 0 if cancel.status is CancelOutcome.CANCELLED else 1

    finally:
        await client.disconnect()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

- [ ] **Step 2: Syntax-only parse check**

Run: `.venv/bin/python -c "import ast; ast.parse(open('examples/cancel_queued_order.py').read())"`
Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add examples/cancel_queued_order.py
git commit -m "docs(examples): add cancel_queued_order demonstrating QUEUED + cancel"
```

---

## Task 13: README + CHANGELOG updates

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Locate the Trading section in README**

Open `README.md`. Find the Trading section (usually under "Usage" or similar). Pick an insertion point immediately after the `buy()` / `sell()` subsection so that "queued orders" reads as a natural extension.

- [ ] **Step 2: Insert the "Queued orders" subsection**

Add the following block after the existing `buy()`/`sell()` example in `README.md`:

````markdown
### Queued orders (market closed)

When the instrument's market is closed, XTB accepts the order and queues
it until market open. The library surfaces this as `TradeOutcome.QUEUED`
rather than lying about a fill:

```python
result = await client.buy("AAPL.US", volume=1)

match result.status:
    case TradeOutcome.FILLED:
        print(f"Filled at {result.price}")
    case TradeOutcome.QUEUED:
        print(f"Queued {result.order_number}; cancelling...")
        cancel = await client.cancel_order(result.order_number)
        print(f"Cancel status: {cancel.status}")
    case _:
        print(f"Trade failed: {result.status} — {result.error}")
```

`TradeResult.order_number` is populated for both `FILLED` and `QUEUED`
outcomes. `cancel_order()` returns a typed `CancelResult` with
`CancelOutcome` values (`CANCELLED`, `REJECTED`, `AMBIGUOUS`).
````

- [ ] **Step 3: Prepend a pending entry to `CHANGELOG.md`**

Open `CHANGELOG.md`. Immediately after the `# CHANGELOG` header line and before `## v0.7.2`, insert:

```markdown
## v0.8.0 (unreleased)

### Features

- **types**: Add `TradeOutcome.QUEUED` for market-order requests that XTB
  accepts but does not immediately fill (typically: the instrument's market
  is closed). Previously classified as `FILLED` with `price=None` — a silent
  misclassification.
- **types**: Populate `TradeResult.order_number` (integer broker order
  number) from the gRPC `NewMarketOrder` response for both filled and queued
  trades. Feed into `XTBClient.cancel_order()`.
- **client**: Add `XTBClient.cancel_order(order_number)` hitting the gRPC
  `DeleteOrders` endpoint. Returns a typed `CancelResult` with
  `CancelOutcome` values `CANCELLED`, `REJECTED`, or `AMBIGUOUS`.

### Bug Fixes

- **client**: Market-closed orders are no longer silently reported as
  `FILLED` when the broker has actually queued them.
```

(If the release tooling regenerates this file from conventional commits,
the hand-written entry will be superseded at release time. Leaving it in
the working tree signals intent for reviewers in the meantime.)

- [ ] **Step 4: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "docs: document QUEUED outcome and cancel_order in README and CHANGELOG"
```

---

## Task 14: Full-suite regression + manual smoke verification

This task has no new code — it verifies the whole surface works together and closes out the §2 spec assumption about `getAllOrders` returning queued market orders.

- [ ] **Step 1: Run the complete test suite**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: all tests pass. If anything flaps or fails, fix it in a follow-up commit before proceeding.

- [ ] **Step 2: Run type / lint gates the project already uses**

Run: `.venv/bin/python -m mypy src tests`
Expected: no errors introduced by the new code. If the project also has `ruff`, run `.venv/bin/python -m ruff check src tests`.

- [ ] **Step 3: Manual smoke test on the demo account**

Prerequisites: demo account credentials in env, `XTB_ACCOUNT_TYPE=demo`, US market currently closed (before 15:30 CEST / after 22:00 CEST).

```bash
export XTB_EXAMPLE_TRADE=1
export XTB_ACCOUNT_TYPE=demo
.venv/bin/python examples/cancel_queued_order.py
```

Expected output:

```
Placing BUY AAPL.US vol=1 (expecting QUEUED if market is closed)...
buy() → status=QUEUED  order_number=<integer>  order_id=<UUID>
Cancelling queued order <integer>...
cancel_order() → status=CANCELLED  cancellation_id=<UUID>  error=None
```

If `status=FILLED` instead of `QUEUED` the market is open; rerun outside
NASDAQ hours. If `status=AMBIGUOUS` with `error_code=FILL_STATE_UNKNOWN`
the `getAllOrders` assumption in spec §2 does not hold for queued market
orders — file a bug and extend `_classify_accepted_trade` to fall back
to a positions-only poll with a longer deadline (see spec §2 contingency).

- [ ] **Step 4: Commit any fixes from smoke-test feedback, or proceed to release**

If the smoke test surfaced issues, commit the fixes with conventional-commit
prefixes (`fix(client): ...` or similar) before tagging a release. If
everything passed, the feature is ready; bumping the version and tagging
belongs to a separate release task, not this plan.

---

## Self-review

- **Spec coverage** — Walked every spec section and mapped it to a task:
  §1 Context (motivation documented in plan header). §2 Detection flow →
  Task 8. §3 Current-state reference (documentary; no code). §4.1
  `TradeOutcome.QUEUED` → Task 7. §4.2 `TradeResult.order_number` →
  Task 7 (and populated in Task 5 at the gRPC layer, consumed in Task 8).
  §4.3 Cancel types → Task 7. §4.4 `XTBClient.cancel_order` → Task 9.
  §5.1 proto changes → Tasks 1, 2, 3. §5.2 types changes → Task 4.
  §5.3 gRPC client changes → Tasks 5, 6. §5.4 `XTBClient` changes →
  Tasks 8, 9. §5.5 public re-exports → Task 10. §6 Error handling → built
  into Tasks 8 and 9 (FILL_STATE_UNKNOWN, AMBIGUOUS_NO_RESPONSE,
  RBAC_DENIED). §7 Tests → Tasks 1–10 each include their own tests.
  §8 Docs / examples → Tasks 11, 12, 13. §9 Backwards compatibility →
  nothing in the plan breaks existing behaviour; no task needed. §10
  Decision log → preserved in spec; plan doesn't re-litigate.

- **Placeholder scan** — no `TBD`, `TODO`, "implement later", "add
  appropriate error handling", or "similar to Task N" shortcuts. Every
  code step shows the code; every test step shows the test body; every
  command is concrete and its expected output is stated.

- **Type consistency** — `GrpcTradeResult.order_number` / `GrpcCancelResult`
  / `TradeResult.order_number` / `CancelOutcome` / `CancelResult` match
  across Tasks 4, 5, 6, 7, 8, 9, 10. `cancel_order(int) -> CancelResult`
  is used uniformly. `error_code` values (`FILL_STATE_UNKNOWN`,
  `AMBIGUOUS_NO_RESPONSE`, `RBAC_DENIED`) are spelled identically in
  tests and implementation. The `_classify_accepted_trade` signature
  matches between the Task 8 implementation block and the test
  expectations (positions-then-orders probe, one retry).

- **Gaps closed inline** — spec §5.2 said `@dataclass`; codebase uses
  Pydantic; plan explicitly matches codebase (Correction header).
  Spec §7.1 pointed at a non-existent test file; plan re-routes to the
  actual existing file plus a new focused file (Correction header).
  Spec §8.4 uses a CHANGELOG section style that conflicts with the
  project's auto-generated conventional-commit style; plan matches
  project style (Correction header).
