# xtb-api-python — Deep Audit & Roadmap (v1.0)

Status: draft for review
Author: brainstormed with Claude Opus 4.7
Date: 2026-04-17

---

## 1. Context & scope

`xtb-api-python` (v0.5.4, ~4.2k LOC, on PyPI) is an unofficial Python client
for XTB's xStation5 platform. It has one production consumer today —
`xtb-investor-pro`, whose broker adapter at
`xtb-investor-pro/src/investor/broker/xtb.py` is the highest-fidelity
reference we have for the library's real-world ergonomics. That adapter
reveals systemic friction:

- A fresh `XTBClient` is constructed per call because the client binds to
  the first event loop it touched; a persistent client cannot survive
  `asyncio.run()` cycles.
- Volume is pre-rounded to `int` in the adapter because the library validates
  the rounded value but forwards the un-rounded `volume` to gRPC.
- Outcome classification is done by string-matching the library's error
  text (`"gRPC call returned empty response"`, `"RBAC"`), which is both
  fragile and a code smell the library should not push onto consumers.

In parallel, the v0.5.2 → v0.5.3 → v0.5.4 ping-pong on `get_positions`
semantics (see [CHANGELOG.md](../../../CHANGELOG.md)) shows that the
transport layer has unclear internal contracts and no tests against
recorded wire traffic, so the same regression could recur.

This document performs a systematic audit across three themes and proposes
a sequenced roadmap:

1. **Stability & resilience** — correctness of the wire protocols and
   reconnect/heartbeat/idempotency story.
2. **Error classification** — typed outcomes vs. string-matching, and the
   shape of the exception hierarchy at the public boundary.
3. **External-user ergonomics & install UX** — what it takes to `pip install`
   the library and do useful work, and what surprises users on first run.

### Goals

- Inventory concrete, file-line-cited findings across the three themes.
- Rank each finding P0 / P1 / P2 against a stated audience weighting.
- Propose 3–5 workstreams that close the findings, with clear breaking-vs-
  additive boundaries, sizes, and dependencies.
- Commit to a single breaking **v1.0** bundling W1+W2+W3; W4 and W5 ship
  additively after v1.0.

### Non-goals

- This document does **not** implement anything. It produces a roadmap.
- Each workstream becomes its own design+plan via the standard
  brainstorming → writing-plans → executing-plans loop when it is scheduled.
- No decisions are made here that bind version numbers or release dates
  beyond "v1.0 bundles W1+W2+W3".

### Audience weighting

The roadmap is prioritized against the following weighted user mix:

| Weight | Audience                               | What they need |
|--------|----------------------------------------|---|
| 30 %   | Hobbyist / single-script users         | `pip install` works in 5 minutes; Quick Start runs cleanly; errors read like English. |
| 50 %   | Automation authors (investor-pro-shape)| Long-lived or well-documented ephemeral client; typed outcomes, not string-matching; first-class ambiguous-outcome handling. |
| 20 %   | Library integrators                    | Strict typing, stable public surface, no hidden side-effects on import, `decimal`-friendly pricing. |

Findings whose closure most moves the needle for the 50% slice are
scheduled into v1.0. Hobbyist install UX is a close second, driven by
W3's Playwright extras restructure. Integrator-facing polish (W4, W5)
ships after v1.0 as additive changes.

---

## 2. Method

### How findings were gathered

Two parallel audits, one per the two highest-risk subsystems:

- **Transport layer audit** — read all of `ws/ws_client.py`,
  `ws/parsers.py`, `grpc/client.py`, `grpc/proto.py`, and the trade pipeline
  in `client.py:284-435`. Cross-referenced against `xtb-investor-pro`'s
  adapter to identify forced string-matching and fresh-per-call patterns.
- **Auth + install audit** — read all of `auth/cas_client.py`,
  `auth/browser_auth.py`, `auth/auth_manager.py`, the `xtb-api doctor`
  CLI in `__main__.py`, `pyproject.toml`, and `README.md`'s install story.

The recent CHANGELOG (v0.3.0 → v0.5.4) was read to surface recurring
bug classes that a typed surface would have prevented (auth window edges,
push-vs-reqId confusion, event-loop zombie clients).

### Severity ladder

Findings are triaged against **what breaks and for whom**:

- **P0** — data loss, duplicate-order risk, silent wrong-thing, or
  security weakness. Must close before v1.0.
- **P1** — ergonomic pain that every consumer in the 50% slice feels, or
  an install blocker for the 30% slice.
- **P2** — cleanup, documentation debt, latent risk that manifests only
  under specific conditions. Ships after v1.0 unless tightly coupled to
  a P0/P1 fix.

Finding IDs (F01-F40) are stable once this document is approved;
downstream specs reference them by ID.

### Use of `xtb-investor-pro` as reference

`xtb-investor-pro` is the single real-world consumer. Every finding that
flows from consumer pain cites the adapter file (and line, where useful)
as evidence that the finding is not theoretical. The migration guide in
§12 explicitly uses the investor-pro adapter as the pilot consumer for
verifying v1.0 breaking changes.

---

## 3. Findings — Stability & resilience

12 findings, P0 → P2.

### F01 — Empty gRPC response is treated as failure, but the order may be placed **[P0]**

`grpc/client.py:109-110` raises `ProtocolError("gRPC call returned empty
response")` when the HTTP response is 2xx but the body is empty. At
`grpc/client.py:250-252` this is caught and converted into
`GrpcTradeResult(success=False)`. An empty response after a successful
HTTP call is precisely the case where the order *may* have reached the
matching engine but the response was lost in transit. Reporting a
definitive `success=False` is wrong: the outcome is **ambiguous** and
should be a first-class state.

**Files:** [src/xtb_api/grpc/client.py](../../../src/xtb_api/grpc/client.py)

### F02 — JWT refresh retry can duplicate a filled order **[P0]**

`client.py:377-389` retries the full trade on any `"RBAC"` string-match
in the error. No idempotency key, no pre-retry check of `get_positions`
to confirm the first attempt did not already fill. If the first attempt
succeeded at the matching engine and the response was garbled into an
RBAC-looking error, the retry submits a duplicate order.

**Files:** [src/xtb_api/client.py:377-389](../../../src/xtb_api/client.py)

### F03 — `asyncio.Lock()` created at `__init__` forces fresh-per-call clients **[P1]**

`ws/ws_client.py:98` creates `self._symbols_lock = asyncio.Lock()` at
construction time, binding the client to the running event loop (or
failing if called outside one). This is why `xtb-investor-pro`'s adapter
builds a fresh `XTBClient` per broker call — a persistent client cannot
survive the loop switch that `asyncio.run()` performs between calls.

**Files:** [src/xtb_api/ws/ws_client.py](../../../src/xtb_api/ws/ws_client.py)

### F04 — `ws_client.py` is 911 LOC mixing five concerns **[P1]**

The single file handles connection lifecycle, heartbeat, reconnect,
reqId-based RPC, push subscriptions, and high-level reads
(`get_balance`, `get_positions`, `get_orders`, `search_instrument`). The
v0.5.3 regression happened because the push-vs-reqId contract for
`get_positions` was unclear even to someone reading the file carefully.
Any change to reconnect logic risks breaking subscriptions; any change
to RPC handling risks breaking push events.

**Files:** [src/xtb_api/ws/ws_client.py](../../../src/xtb_api/ws/ws_client.py)

### F05 — Reconnect exhaustion only emits an `'error'` event, no raise **[P1]**

`ws/ws_client.py:852-890` runs an exponential-backoff reconnect with a
hard cap of 10 attempts. On exhaustion, it emits the `'error'` event
carrying a `ReconnectionError` but does not re-raise into any awaiting
futures or the public surface. A caller `await`ing `client.get_balance()`
during reconnect exhaustion sees a `XTBConnectionError("Connection
closed")` (from the pending-futures cleanup), not a `ReconnectionError`
— losing the "we tried 10 times and gave up" signal that distinguishes a
transient drop from a persistent failure.

**Files:** [src/xtb_api/ws/ws_client.py](../../../src/xtb_api/ws/ws_client.py)

### F06 — Missed heartbeat pings do not trigger reconnect **[P1]**

`ws/ws_client.py:809-822` runs the ping loop but a missed ping is
silently skipped. The listen loop only closes the socket on
`ConnectionClosed`. A dead socket that never returns a `ConnectionClosed`
(common under NAT or stateful middleboxes) stays "connected" until the
next business RPC attempts to send and times out 30 s later.

**Files:** [src/xtb_api/ws/ws_client.py](../../../src/xtb_api/ws/ws_client.py)

### F07 — Late RPC responses arriving after timeout are silently dropped **[P1]**

`ws/ws_client.py:343-346` pops the future from `_pending_requests` on
timeout. If the response arrives later, the message handler
(`ws_client.py:781`) finds nothing in the dict and drops the response.
Under load, slow responses from a server that has recovered can orphan
request state without telling the caller that anything happened.

**Files:** [src/xtb_api/ws/ws_client.py](../../../src/xtb_api/ws/ws_client.py)

### F08 — gRPC frame parser truncates on partial frames, keeps only last data frame **[P2]**

`grpc/client.py:274-297` breaks out of the frame loop on an incomplete
frame (`if pos + length > len(response_bytes): break`) and silently
continues. `data_payload = frame_data` overwrites if multiple data
frames arrive. Trailer statuses other than 0 collapse into generic
failure. Multi-frame or malformed responses can lose data or misclassify
errors without any log.

**Files:** [src/xtb_api/grpc/client.py](../../../src/xtb_api/grpc/client.py)

### F09 — Volume validation rounds for the `< 1` check but forwards raw float **[P2]**

`client.py:337-347` performs `rounded = int(volume + 0.5)` for the
`< 1` guard, but `client.py:369` forwards the original `volume` argument
to `grpc.execute_order()`. `xtb-investor-pro`'s adapter pre-rounds
defensively for this reason (`broker/xtb.py:140, 162`). Single source of
truth: round once, forward the rounded value.

**Files:** [src/xtb_api/client.py:337-369](../../../src/xtb_api/client.py)

### F10 — No tests against recorded wire traffic **[P2]**

All transport-layer tests use `AsyncMock` stubs. The v0.5.3 regression
(documented in [CHANGELOG.md](../../../CHANGELOG.md#v054-2026-04-15)) shipped
because the mocks matched the wrong mental model of the wire protocol
and no recorded traffic told us otherwise. XTB can change response
shapes at any time; without golden wire fixtures, we will only catch
regressions in production.

**Files:** [tests/](../../../tests/), [CHANGELOG.md](../../../CHANGELOG.md)

### F11 — Concurrent `get_tgt()` calls race on refresh **[P2]**

`auth/auth_manager.py:93-126` reads `_cached_tgt` / `_cached_expires_at`
without a lock. Two concurrent calls that arrive with an expired cache
both invoke `_login_with_fallback()` → duplicate CAS login. Not a
correctness bug today (both writes converge), but a wasted roundtrip and
a potential "new device" email from XTB.

**Files:** [src/xtb_api/auth/auth_manager.py:93-126](../../../src/xtb_api/auth/auth_manager.py)

### F12 — `_ensure_http` event-loop detection may be vestigial **[P2]**

`auth/cas_client.py:85-100` detects and replaces the `httpx.AsyncClient`
when the event loop changes. This was added to handle a v0.3.0 bug with
`get_tgt_sync()` calling `asyncio.run()` (the closed-loop zombie). Modern
httpx handles loop changes natively; the guard may no longer be needed
and the complexity is non-trivial. Worth verifying with a test before
removal.

**Files:** [src/xtb_api/auth/cas_client.py:85-100](../../../src/xtb_api/auth/cas_client.py)

---

## 4. Findings — Error classification

11 findings, P1 → P2. (No P0s — the correctness bugs that error
classification would surface are counted under §3.)

### F13 — String-match on `"RBAC"` triggers JWT refresh **[P1]**

`client.py:378` and `grpc/client.py:313` both use `"RBAC" in error` to
decide whether to refresh JWT and retry. If XTB ever rewords the error,
retries stop firing and every trade after a JWT expiry fails silently.
The trigger should be a typed exception or a structured status code.

**Files:** [src/xtb_api/client.py:378](../../../src/xtb_api/client.py), [src/xtb_api/grpc/client.py:313](../../../src/xtb_api/grpc/client.py)

### F14 — `"gRPC call returned empty response"` marker leaks into consumers **[P1]**

`xtb-investor-pro/src/investor/broker/xtb.py:231` string-matches this
exact phrase to classify the empty-response (ambiguous) case. The library
should either expose an `AmbiguousOutcomeError` subclass (or a
`TradeOutcome.AMBIGUOUS` state on `TradeResult`) so the consumer doesn't
own the interpretation.

**Files:** `xtb-investor-pro/src/investor/broker/xtb.py:231`
(external consumer cited for reference)

### F15 — `_poll_fill_price` returns `None` silently on both failure modes **[P1]**

`client.py:414-435` returns `None` whether the position never appeared
in three retries (transient poll failure) or the order never filled at
all (matching-engine rejection visible only via a separate query). The
caller cannot tell these apart; both look like "we don't know the fill
price" but only one means "we don't know if the trade happened."

**Files:** [src/xtb_api/client.py:414-435](../../../src/xtb_api/client.py)

### F16 — `TradeResult` has `success: bool` + free-text `error`, no status enum **[P1]**

[src/xtb_api/types/trading.py](../../../src/xtb_api/types/trading.py)
exposes a binary success flag and a loose error string. There is no
enum for `FILLED`, `REJECTED`, `AMBIGUOUS`, `INSUFFICIENT_VOLUME`,
`AUTH_EXPIRED`, `RATE_LIMITED`, `TIMEOUT`. Consumers end up
re-classifying the error string to recover the state the library
already computed.

**Files:** [src/xtb_api/types/trading.py](../../../src/xtb_api/types/trading.py)

### F17 — 2FA fallback silently uses the WAF-blocked REST path **[P1]**

`auth/auth_manager.py:192-199` only sets `_browser_auth` when the REST
login raised during the initial call. If REST login **succeeded** but
returned a 2FA challenge, the manager attempts REST 2FA — which the
WAF blocks — instead of falling through to the browser path. The failure
message is opaque ("CAS_AUTH_TWO_FACTOR_FAILED"-ish) with no pointer
that a browser fallback exists.

**Files:** [src/xtb_api/auth/auth_manager.py:192-199](../../../src/xtb_api/auth/auth_manager.py)

### F18 — `CASError` is one class; consumers must inspect `.code` string **[P2]**

[exceptions.py:22-32](../../../src/xtb_api/exceptions.py) exposes a single
`CASError` that carries `.code`. Distinguishing invalid credentials vs.
account blocked vs. rate-limit vs. 2FA-required requires string
comparisons on a server-provided code. Four subclasses
(`InvalidCredentialsError`, `AccountBlockedError`, `RateLimitedError`,
`TwoFactorRequiredError`) cover >95% of handled cases.

**Files:** [src/xtb_api/exceptions.py](../../../src/xtb_api/exceptions.py)

### F19 — Bare `Exception` catch in gRPC trade execution loses tracebacks **[P2]**

`grpc/client.py:251-252` catches `Exception` and converts to a string
error. Unexpected failures — protobuf build errors, serialization bugs,
httpx internal errors — all collapse into an opaque "something failed"
and the traceback is discarded.

**Files:** [src/xtb_api/grpc/client.py:251-252](../../../src/xtb_api/grpc/client.py)

### F20 — Event-handler exceptions are swallowed; async results never awaited **[P2]**

`ws/ws_client.py:160-175` logs-and-continues when an event handler
raises. Async handlers are scheduled as tasks but never awaited; an
unhandled exception inside them surfaces only as `asyncio` warnings at
interpreter shutdown.

**Files:** [src/xtb_api/ws/ws_client.py:160-175](../../../src/xtb_api/ws/ws_client.py)

### F21 — JSON decode error emits bare `RuntimeError` instead of `ProtocolError` **[P2]**

`ws/ws_client.py:772-775` emits `RuntimeError("Failed to parse
message: ...")` on JSON decode failure. The exception hierarchy already
has `ProtocolError` for exactly this case; using it would let consumers
catch `except ProtocolError` uniformly.

**Files:** [src/xtb_api/ws/ws_client.py:772-775](../../../src/xtb_api/ws/ws_client.py)

### F22 — Server error message truncated to 200 chars **[P2]**

`grpc/client.py:318` does `f"gRPC order rejected: {response_text[:200]}"`
and discards the remainder. Long rejection messages lose the structured
part that would have told a user why the trade was rejected.

**Files:** [src/xtb_api/grpc/client.py:318](../../../src/xtb_api/grpc/client.py)

### F23 — `Xs6Side.BUY=0` vs `SIDE_BUY=1` mismatch guarded only by docstring **[P2]**

[client.py:265-269](../../../src/xtb_api/client.py) warns via docstring that
the WebSocket and gRPC side constants disagree. A single public `Side`
enum at the boundary, with protocol-specific mappings hidden inside
`ws/` and `grpc/`, would make the mistake impossible rather than
"documented".

**Files:** [src/xtb_api/client.py:265-269](../../../src/xtb_api/client.py)

---

## 5. Findings — Ergonomics & install UX

17 findings, P1 → P2. (No P0s.)

### F24 — `playwright>=1.40` is a **base** dependency **[P1]**

[pyproject.toml:33](../../../pyproject.toml) lists `playwright` in
`[project.dependencies]`. Every `pip install xtb-api-python` — including
users who only want `get_balance()` over WebSocket and will never touch
the browser path — pays the Playwright install tax (~100 MB wheel + a
mandatory post-install `playwright install chromium` step). This is the
single biggest hobbyist adoption blocker.

**Files:** [pyproject.toml](../../../pyproject.toml)

### F25 — Python 3.12 floor excludes 3.11 LTS-era systems **[P1]**

[pyproject.toml:11](../../../pyproject.toml) sets `requires-python =
">=3.12"`. Nothing in the codebase appears to strictly need 3.12 over
3.11 (type union `|`, `match`, and string-interpolation features are
all 3.10+). The 3.11 floor covers every major LTS Linux shipping in
2026; 3.12 doesn't.

**Files:** [pyproject.toml](../../../pyproject.toml)

### F26 — Auto-derived `*_cookies.json` sibling file is undocumented **[P1]**

`auth/auth_manager.py:82-83` auto-derives the cookies file path from
`session_file`. The behavior is invisible to a reader of the public
`__init__.py` docstrings and the README — a user setting
`session_file="~/.xtb_session"` gets `~/.xtb_session_cookies` created
silently, which they didn't ask for.

**Files:** [src/xtb_api/auth/auth_manager.py:82-83](../../../src/xtb_api/auth/auth_manager.py)

### F27 — Cookies file has no 0600 enforcement on read **[P1]**

`auth/cas_client.py:488-498` loads cookies from any world-readable file
without warning. The cookies include CASTGC, which is sufficient to
impersonate the account. The session file has a 0600 warn-and-fix path;
the cookies file should match it.

**Files:** [src/xtb_api/auth/cas_client.py:488-498](../../../src/xtb_api/auth/cas_client.py)

### F28 — Playwright browser leaks when user catches mid-2FA exception **[P1]**

`auth/browser_auth.py:204-207` intentionally leaves the browser open
between `login()` returning a 2FA challenge and the caller invoking
`submit_otp()`. If the caller catches an exception between those two
calls and never invokes `close()`, Chromium lingers as a zombie.

**Files:** [src/xtb_api/auth/browser_auth.py:204-207](../../../src/xtb_api/auth/browser_auth.py)

### F29 — No `async with XTBClient(...) as c:` context manager **[P1]**

[client.py:111-127](../../../src/xtb_api/client.py) exposes `connect` and
`disconnect` as standalone methods. Every real consumer writes a
`try/finally` to pair them. An `__aenter__/__aexit__` implementation
would guarantee disconnect on exception and make the Quick Start
shorter.

**Files:** [src/xtb_api/client.py:111-127](../../../src/xtb_api/client.py)

### F30 — No sync wrapper for non-async callers **[P1]**

There is no `SyncXTBClient` or equivalent. `xtb-investor-pro` is forced
to dispatch broker calls via its own `run_async()` bridge, and that
bridge is what exposed the event-loop-binding bug (F03). Other
non-async consumers (notebooks, Django management commands, CLI tools)
hit the same wall.

**Files:** [src/xtb_api/client.py](../../../src/xtb_api/client.py)

### F31 — `XTBAuth` standalone usage not shown in README **[P2]**

[__init__.py:6](../../../src/xtb_api/__init__.py) exports `XTBAuth` but
[README.md](../../../README.md) only mentions it as `client.auth`. A
non-trivial use case — "I want to cache a TGT for multiple short-lived
clients" — has no documented entry point.

**Files:** [README.md](../../../README.md)

### F32 — `cookies_file` parameter missing from `AuthManager.__init__` docstring **[P2]**

`auth/auth_manager.py:54-75` documents `session_file` and `cas_config`
but not `cookies_file`. A user who wants to override the auto-derived
path (F26) has to read the source to discover the parameter.

**Files:** [src/xtb_api/auth/auth_manager.py:54-75](../../../src/xtb_api/auth/auth_manager.py)

### F33 — `doctor` CLI doesn't check network, extras, or path permissions **[P2]**

[__main__.py:87-127](../../../src/xtb_api/__main__.py) checks Python, the
package, and the Playwright binary. It does not verify reachability of
`api5reala.x-station.eu`, that `session_file` / `cookies_file` parents
are writable, or that the `[totp]` extra is installed. All three are
first-run footguns that `doctor` could catch.

**Files:** [src/xtb_api/__main__.py:87-127](../../../src/xtb_api/__main__.py)

### F34 — `pyotp` labeled optional is effectively required for 2FA users **[P2]**

[pyproject.toml:46](../../../pyproject.toml) lists `pyotp` under
`[project.optional-dependencies].totp`. A 2FA-enabled account without
`pyotp` gets `AUTH_MANAGER_PYOTP_MISSING` from `AuthManager`. The README
install section doesn't flag that `[totp]` is effectively mandatory for
the majority of XTB accounts.

**Files:** [pyproject.toml](../../../pyproject.toml), [README.md](../../../README.md)

### F35 — Paths use `expanduser` but not `expandvars` **[P2]**

`auth/auth_manager.py:79` and `auth/cas_client.py:82` expand `~` but
not `$HOME` / `${XDG_CONFIG_HOME}`. Shell-script and 12-factor users
who pass `session_file=$XDG_CONFIG_HOME/xtb/session` get a literal
`$XDG_CONFIG_HOME` directory.

**Files:** [src/xtb_api/auth/auth_manager.py:79](../../../src/xtb_api/auth/auth_manager.py), [src/xtb_api/auth/cas_client.py:82](../../../src/xtb_api/auth/cas_client.py)

### F36 — Session file 0600 enforced on write, not atomically on first create **[P2]**

`auth/auth_manager.py:266-273` warns and fixes permissive permissions
at load time, but the first-create path writes the file with the
process's umask and fixes it after the fact. A two-step dance exists
where a parallel reader can observe world-readable content for a
microsecond.

**Files:** [src/xtb_api/auth/auth_manager.py:266-273](../../../src/xtb_api/auth/auth_manager.py)

### F37 — Timezone offset silently defaults to 0 if TZ unset **[P2]**

`auth/cas_client.py:527-538` computes the local TZ offset. If the host
has no TZ set, the offset is 0 (UTC) and the request is sent without
error. XTB may or may not accept that; a silent wrong value is worse
than a crisp exception.

**Files:** [src/xtb_api/auth/cas_client.py:527-538](../../../src/xtb_api/auth/cas_client.py)

### F38 — Cookie merge never clears expired cookies — unbounded file growth **[P2]**

`auth/cas_client.py:500-525` merges new cookies into the existing file
but never removes expired ones. Over months the file grows indefinitely
with stale entries.

**Files:** [src/xtb_api/auth/cas_client.py:500-525](../../../src/xtb_api/auth/cas_client.py)

### F39 — TOTP window margin hardcodes a 30 s assumption **[P2]**

`auth/auth_manager.py:231-237` sleeps if fewer than 2 s remain in the
current TOTP window. The `totp.interval` attribute is used inconsistently
elsewhere but the margin logic assumes 30 s. Custom TOTP configurations
or future pyotp changes could silently skew the margin.

**Files:** [src/xtb_api/auth/auth_manager.py:231-237](../../../src/xtb_api/auth/auth_manager.py)

### F40 — `TradeResult.price` poll timeout is indistinguishable from never-filled **[P2]**

Same root cause as F15, surfaced on a different field. A caller that
needs to reconcile expected vs. actual fill price gets `None` for two
very different states. The fix is coupled to F15 — resolve once via
the `TradeOutcome` enum in W1.

**Files:** [src/xtb_api/client.py:414-435](../../../src/xtb_api/client.py)

---

## 6. Roadmap overview

### Release strategy

One breaking **v1.0** bundles W1 + W2 + W3. W4 and W5 are additive and
ship as v1.x point releases afterward.

```
v1.0   W1 (typed outcomes) + W2 (loop-safe client) + W3 (auth minimization)
         │                     │                      │
         └── breaking ──────────┴──────────────────────┘

v1.x   W4 (transport split + wire-traffic fixtures)   [internal, additive]
v1.x   W5 (install UX, docs, security polish)         [additive]
```

### Why one v1.0 cut

- The user base beyond `xtb-investor-pro` is small today; a
  `v0.6 → v0.7 → v1.0` arc produces three migrations where one suffices.
- `TradeResult.status` (W1) interacts with the loop-safety reconnect
  signaling (W2) — doing these in lock-step avoids two releases of
  "partially typed outcomes."
- The `[browser]` extras restructure (W3) is the only install-contract
  break and it pairs naturally with the public-surface changes in W1.

### Dependency diagram

```
  (independent)
  ┌─────────┐
  │   W3    │   auth minimization + extras
  └────┬────┘
       │ contributes PYOTP_FIRST path
       ▼
  ┌─────────┐       ┌─────────┐       ┌─────────┐
  │   W1    │◄──────│   W2    │       │   W5    │
  │ typed   │ uses  │ loop-   │       │  polish │
  │ outcomes│ types │ safe    │       │         │
  └────┬────┘       └────┬────┘       └─────────┘
       │                  │
       └──────┬───────────┘
              ▼
         ┌─────────┐
         │   W4    │  (optional, internal)
         └─────────┘
```

### Ordering rationale against audience weighting

- **50% automation authors** — W1 (typed outcomes, idempotent retry) and
  W2 (loop-safe, context manager, sync wrapper) are both existential for
  this slice. They go into v1.0 together.
- **30% hobbyists** — W3 (Playwright minimization + extras + 3.11 support)
  removes the single biggest install tax. It goes into v1.0.
- **20% integrators** — W4 (internal refactor) and W5 (polish) ship
  additively. Integrators benefit from v1.0 via W1's stricter typing; the
  wire-fixture coverage in W4 is a reliability uplift without an API
  change.

---

## 7. W1 — Typed outcomes & idempotent trade retry

### Purpose

Eliminate the string-matching error-classification pattern at the public
boundary. Introduce a `TradeOutcome` enum so consumers stop owning the
interpretation of empty-response / RBAC / rejection flavors, and close
the duplicate-order risk in the JWT-refresh retry path. Primarily serves
the 50% automation-author slice.

### Findings closed

F01, F02 (both P0); F13, F14, F15, F16 (P1); F18, F19, F21, F22, F40 (P2).

### What changes

- New enum `TradeOutcome { FILLED, REJECTED, AMBIGUOUS,
  INSUFFICIENT_VOLUME, AUTH_EXPIRED, RATE_LIMITED, TIMEOUT }` in
  [types/trading.py](../../../src/xtb_api/types/trading.py).
- `TradeResult` gains `status: TradeOutcome` and `error_code: ErrorCode
  | None`; `success` becomes a derived `@property` returning
  `status is TradeOutcome.FILLED`.
- New exception `AmbiguousOutcomeError(TradeError)` raised from
  [grpc/client.py](../../../src/xtb_api/grpc/client.py) in place of the
  empty-response `ProtocolError`.
- Idempotency in `client._execute_trade`: before the RBAC retry,
  re-query `get_positions()` and compare against the intended symbol /
  volume / timestamp window. If a matching position already exists, return
  `TradeOutcome.FILLED` with the discovered `order_id` instead of
  resubmitting.
- New `CASError` subclasses in
  [exceptions.py](../../../src/xtb_api/exceptions.py):
  `InvalidCredentialsError`, `AccountBlockedError`, `RateLimitedError`,
  `TwoFactorRequiredError`. `CASError` remains as the common parent.
- `ProtocolError` replaces bare `RuntimeError` in JSON-decode paths.
- Full server error text preserved; no 200-char truncation.

### What stays the same

- WebSocket read APIs (`get_balance`, `get_positions`, `get_orders`,
  `get_quote`, `search_instrument`) keep their signatures and return types.
- Auth flow is untouched (W3 handles that).
- Trade method signatures (`buy`, `sell`) unchanged — only the return
  type gains fields.

### Breaking vs. additive

**Breaking.** The v1.0 cut removes the string-match contract consumers
may depend on. Specifically:

- `TradeResult.success` is now a `@property`, not a field — existing code
  that assigns to it or mutates it breaks.
- Consumers that catch `ProtocolError` for the empty-response case must
  switch to `AmbiguousOutcomeError`.
- Consumers that pattern-match on `error` text for RBAC / empty-response
  now get explicit `status` + `error_code` fields they should switch to.

Migration snippets for each: §12.

### Size

**M (3–5 days).** ~15–20 new tests (enum round-trip, idempotency replay,
`AmbiguousOutcomeError` in each raise site, subclass hierarchy).

### Dependencies

None inbound. W2 imports `TradeOutcome` for its reconnect-exhaustion
handling. Ship W1 first within the v1.0 cut.

### Out of scope for this workstream

- Decimal pricing conversion (stays float in v1.0 — queue for v2.0 if
  needed by integrators).
- W2's `async with` / sync wrapper — separate workstream.
- Any changes to auth errors beyond the four `CASError` subclasses.

---

## 8. W2 — Loop-safe client + context manager + sync wrapper

### Purpose

Make `XTBClient` usable as a long-lived object across `asyncio.run()`
cycles, expose an ergonomic `async with` form, and provide a
`SyncXTBClient` for blocking callers. Close the reconnect-signaling gap
so awaiting callers observe exhaustion.

### Findings closed

F03, F05, F06, F07, F11 (P1); F29, F30 (P1).

### What changes

- Lazy initialization of `asyncio.Lock` / `asyncio.Event` /
  `asyncio.Queue` objects: created on first `connect()`, rebind if the
  running loop differs from the one they were bound to (compare
  `asyncio.get_running_loop()` identity against a cached reference).
- `XTBClient.__aenter__` / `__aexit__` implementing
  `async with XTBClient(...) as c:` with guaranteed disconnect on
  exception paths.
- New class `SyncXTBClient` in `src/xtb_api/sync.py`: wraps the async
  client in a single private event loop running on a dedicated thread.
  Exposes the same read / trade methods synchronously. Lifetime tied to
  a `with SyncXTBClient(...) as c:` block.
- Reconnect exhaustion (`ws_client.py:852-890`) now propagates
  `ReconnectionError` into pending request futures via `_cleanup`, so
  awaiters see the specific exception instead of the generic
  `XTBConnectionError("Connection closed")`.
- Heartbeat miss path: after N consecutive unacknowledged pings, close
  the socket to trigger reconnect instead of silent skip.
- Late-response handling: pending requests keep a short grace window
  after timeout so late responses are logged and discarded cleanly,
  without orphaning server-side state silently.
- `asyncio.Lock` guards the TGT cache read/refresh path to dedupe
  concurrent re-logins.

### What stays the same

- Existing `connect()` / `disconnect()` standalone method pair remains
  supported for callers not using `async with`.
- Public API of `XTBClient` read methods unchanged.

### Breaking vs. additive

**Additive surface, behavioral break in v1.0.** Reconnect exhaustion now
raises `ReconnectionError` into `await`ing code instead of only firing
the event; callers with a `try/except XTBConnectionError` continue to
work (parent class), but callers that rely on "the await just returns
somehow" need to adapt. The lazy-init change is transparent.

### Size

**M (3–5 days).** ~10–15 new tests covering loop switches, context-
manager exception paths, sync-wrapper lifetime, heartbeat-miss reconnect,
and reconnect-exhaustion propagation.

### Dependencies

Imports `TradeOutcome.TIMEOUT` from W1 for the heartbeat-triggered abort
path. Land W1 first, then W2.

### Out of scope for this workstream

- The `ws_client.py` split into four modules — that's W4, internal.
- Auth concurrency beyond the TGT-refresh lock (W3 + W5).

---

## 9. W3 — Playwright-minimized auth + extras restructure

### Purpose

Remove the Playwright install tax from users who don't need a browser.
Fix the silent 2FA fallback bug. Broaden Python support to 3.11 so
production stacks can adopt. Primarily serves the 30% hobbyist slice;
also de-risks automation-author deployments.

### Findings closed

F17 (P1 — 2FA fallback bug); F24 (P1 — Playwright base dep); F25
(P1 — 3.12 floor); F28 (P1 — browser cleanup leak); F34 (P2 — pyotp
labeling).

### What changes

- [pyproject.toml](../../../pyproject.toml):
  - Move `playwright` from `[project.dependencies]` to a new extra
    `[project.optional-dependencies].browser`.
  - Drop `requires-python` from `>=3.12` to `>=3.11`, contingent on a
    clean test sweep on 3.11 (smoke-test task under W3).
  - Add `browser` to the documented extras alongside `totp`, `dev`.
- Auth decision tree (`auth/auth_manager.py`):
  - `totp_secret` supplied → REST login + `pyotp`-computed code, no
    browser launch.
  - `totp_secret` missing AND 2FA challenge returned → clear error:
    "2FA required but no `totp_secret` configured; install
    `xtb-api-python[browser]` for interactive 2FA or provide a TOTP
    secret."
  - WAF blocks REST login → fall back to browser path (requires
    `[browser]` extra). Clear error if extra is not installed:
    `CASError("BROWSER_EXTRA_NOT_INSTALLED", ...)`.
  - **Fixes F17:** REST succeeded + 2FA challenge now falls through to
    browser path if `totp_secret` is empty, instead of attempting
    WAF-blocked REST 2FA.
- `auth/browser_auth.py` gains a `__del__` / weakref-finalizer that
  closes a leaked browser on garbage collection, plus a contextmanager
  `browser_session()` helper so callers who catch exceptions still
  release Chromium.
- `README.md` install section rewritten:
  - Default `pip install xtb-api-python` — REST + TOTP, no Chromium.
  - `pip install xtb-api-python[browser]` — browser fallback for
    WAF-blocked or no-TOTP-secret flows.
  - `pip install xtb-api-python[totp]` — TOTP support (now documented
    as effectively required for 2FA accounts).
  - Decision matrix: "which extras do I need?" table.

### What stays the same

- `XTBClient` construction signature.
- `AuthManager` public surface.
- Session / cookies file formats (W5 handles security polish).

### Breaking vs. additive

**Breaking install contract.** Users who relied on Playwright being
installed by default need to update their command to
`pip install xtb-api-python[browser]`. The library detects the missing
extra and emits a targeted error instructing the user, so the failure
mode is informative, not silent.

### Size

**M (3–4 days).** Mostly packaging + CI matrix + auth decision-tree
tests. New CI job for Python 3.11 + one for 3.11 with `[browser]`.

### Dependencies

None. Can run in parallel with W1 and W2.

### Out of scope for this workstream

- Removing the browser path entirely — XTB's WAF still blocks some
  login flavors; the browser must remain as a fallback.
- Bundling chromium via an alternative package.

---

## 10. W4 — Transport surface split + wire-traffic fixtures

### Purpose

Internal refactor that makes the transport layer maintainable and
prevents a recurrence of the v0.5.3 regression. Ships after v1.0 as a
pure internal change.

### Findings closed

F04 (P1 — `ws_client.py` 911 LOC); F08 (P2 — frame parser partials);
F09 (P2 — volume forwarding); F10 (P2 — wire fixtures); F20 (P2 —
event-handler exceptions); F23 (P2 — side-constant mismatch).

### What changes

- Split `ws/ws_client.py` into four focused modules:
  - `ws/transport.py` (~200 LOC) — connection lifecycle, heartbeat,
    reconnect.
  - `ws/rpc.py` (~150 LOC) — reqId-based send/await, pending-futures
    map, timeout handling.
  - `ws/subscriptions.py` (~200 LOC) — push-event dispatcher, handler
    registration.
  - `ws/api.py` (~250 LOC) — `get_balance`, `get_positions`,
    `get_orders`, `search_instrument`, `get_quote`. Uses rpc + subscriptions
    primitives.
- `XTBWebSocketClient` becomes a thin facade over the four modules,
  preserving its public API.
- Single public `Side` enum with protocol-specific mappings inside
  `ws/` and `grpc/` — callers only touch `Side.BUY` / `Side.SELL`.
- Volume rounded once in `client._execute_trade`, forwarded as `int`;
  redundant `int(...)` downstream calls removed.
- Recorded wire fixtures under `tests/fixtures/wire/` capturing:
  `getBalance`, `getPositions`, `getOrders` (empty and populated),
  `getSymbolsAll`, a 2FA login exchange, a JWT refresh, and a successful
  trade + post-trade position echo. Replay tests assert the parsers
  interpret real bytes correctly.
- gRPC frame parser logs + raises `ProtocolError` on malformed /
  multi-frame responses instead of silently truncating.
- Event-handler exceptions logged with traceback, not discarded; async
  handlers awaited with per-handler timeouts.

### What stays the same

- `XTBWebSocketClient` public method signatures.
- `XTBClient` remains the one-stop façade.
- `Xs6Side` / `SIDE_BUY` / `SIDE_SELL` remain exported for back-compat
  but are deprecated in favor of `Side`.

### Breaking vs. additive

**Additive.** Internal-only split; public surface unchanged.

### Size

**L (1–2 weeks).** 20+ new tests including the wire-fixture replay
suite. The fixture-capture phase is itself a substantial task (record
against a demo account).

### Dependencies

Consumes `TradeOutcome` from W1 for `api.py` return types. Can happen
any time after W1 lands.

### Out of scope for this workstream

- Rewriting the gRPC encoder/decoder from scratch (too large; defer to
  v2.0 if needed).
- Changing the reqId allocation scheme.

---

## 11. W5 — Install UX, docs, security polish

### Purpose

Scattered small fixes that individually don't move the needle but
collectively clean up the install + docs + security story. Additive,
low risk, ships whenever convenient after v1.0.

### Findings closed

F12, F26, F27, F31, F32, F33, F35, F36, F37, F38, F39.

### What changes

- **Security**:
  - Enforce 0600 on cookies file at read time (mirrors session file
    behavior) — F27.
  - First-create session and cookies files with `os.open(..., O_CREAT |
    O_EXCL, 0o600)` to avoid the warn-and-fix window — F36.
  - Timezone offset raises a typed `ConfigurationError` if unknown
    rather than defaulting to 0 — F37.
- **Docs**:
  - README section on standalone `XTBAuth` usage with a runnable
    snippet — F31.
  - `AuthManager.__init__` docstring fully enumerates `cookies_file`
    and its auto-derivation rule — F26, F32.
- **CLI**:
  - `xtb-api doctor` gains checks for network reachability
    (`api5reala.x-station.eu:443`), parent-directory writability of
    `session_file` / `cookies_file`, and the presence of `[totp]` /
    `[browser]` extras when configured — F33.
- **Paths**:
  - `os.path.expandvars` + `expanduser` on every user-supplied path —
    F35.
- **Maintenance**:
  - Cookie merge prunes cookies with `expires < now` before writing —
    F38.
  - TOTP window-margin reads `totp.interval` instead of hardcoding 30 —
    F39.
  - Verify (via test) whether `_ensure_http` event-loop detection is
    still required; remove if not — F12.

### What stays the same

Everything else.

### Breaking vs. additive

**Additive.** All changes preserve existing behavior except the
`ConfigurationError` on unknown TZ, which replaces a silent wrong value
— that is arguably a bug-fix, not a break.

### Size

**S (2–3 days).**

### Dependencies

None. Can ship any time after v1.0.

### Out of scope for this workstream

- Anything involving the transport or trade pipeline — handled in
  W1/W2/W4.

---

## 12. v1.0 breaking-change migration guide

Each entry pairs a breaking change with a before/after snippet the
`xtb-investor-pro` broker adapter
(`xtb-investor-pro/src/investor/broker/xtb.py`) can use as the pilot
migration. Entries are sourced from W1-W3 only; W4 and W5 are
additive.

### Classify empty-response as `AmbiguousOutcomeError` (closes F01, F14, from W1)

Why: The empty-response case was a `ProtocolError` whose message had to
be string-matched. Consumers now catch a typed exception.

Before:
```python
try:
    r = await client.buy(sym, volume)
except ProtocolError as e:
    if "gRPC call returned empty response" in str(e):
        return TradeResult(success=False, ambiguous=True, error=str(e))
    return TradeResult(success=False, ambiguous=False, error=str(e))
```

After:
```python
from xtb_api.exceptions import AmbiguousOutcomeError

try:
    r = await client.buy(sym, volume)
except AmbiguousOutcomeError as e:
    return TradeResult(success=False, ambiguous=True, error=str(e))
except TradeError as e:
    return TradeResult(success=False, ambiguous=False, error=str(e))
```

Affects: `xtb-investor-pro/src/investor/broker/xtb.py:231`, and the
`_classify_protocol_error` helper at `broker/xtb.py:234-251` can be
deleted outright.

### Use `TradeOutcome` instead of `success` + string match (closes F15, F16, F40, from W1)

Why: The `success: bool` + free-text `error` pattern forced consumers
to re-classify. `TradeResult.status` is now authoritative.

Before:
```python
r = await client.buy(sym, volume)
if r.success:
    handle_filled(r.order_id, r.price)
elif "insufficient" in (r.error or "").lower():
    handle_rejected_insufficient(...)
else:
    handle_rejected_generic(r.error)
```

After:
```python
from xtb_api import TradeOutcome

r = await client.buy(sym, volume)
match r.status:
    case TradeOutcome.FILLED:
        handle_filled(r.order_id, r.price)
    case TradeOutcome.INSUFFICIENT_VOLUME:
        handle_rejected_insufficient(...)
    case TradeOutcome.REJECTED:
        handle_rejected_generic(r.error)
    case TradeOutcome.AMBIGUOUS:
        handle_ambiguous(r.order_id)
```

`TradeResult.success` still exists as a `@property` for one-line checks
that don't need the full state.

Affects: `xtb-investor-pro/src/investor/broker/xtb.py:142-174` —
`buy()` and `sell()` can delete the `ProtocolError` catch and read
`r.status` instead.

### Handle reconnect exhaustion as an exception, not only an event (from W2)

Why: Callers `await`ing during a protracted outage should see a
specific `ReconnectionError` rather than the generic
`XTBConnectionError("Connection closed")`.

Before:
```python
try:
    await client.get_balance()
except XTBConnectionError:
    # Reconnect attempts exhausted? or just a single drop?
    # We can't tell.
    ...
```

After:
```python
from xtb_api.exceptions import ReconnectionError, XTBConnectionError

try:
    await client.get_balance()
except ReconnectionError:
    alert_ops("broker unreachable after 10 retries")
except XTBConnectionError:
    # Transient — our retry wrapper will try again shortly.
    ...
```

Affects: anywhere `xtb-investor-pro` catches `XTBConnectionError` it can
optionally split to handle exhaustion more loudly.

### Install Playwright as an extra, not by default (closes F24, from W3)

Why: Most deployments don't need Chromium. The base install is now
lean; add the extra if you need the browser fallback.

Before:
```bash
pip install xtb-api-python
playwright install chromium
```

After:
```bash
# REST + TOTP, no browser (most accounts):
pip install "xtb-api-python[totp]"

# Browser fallback (for accounts where REST is WAF-blocked or no TOTP
# secret is configured):
pip install "xtb-api-python[browser,totp]"
playwright install chromium
```

Affects: `xtb-investor-pro/pyproject.toml` and its `Dockerfile` — add
`[browser,totp]` to the dependency pin.

### New `CASError` subclasses (closes F18, from W1)

Why: `except CASError` catches everything, but code that wants to
distinguish bad-creds from rate-limit shouldn't read `.code`.

Before:
```python
try:
    await client.connect()
except CASError as e:
    if e.code == "CAS_AUTH_INVALID_CREDENTIALS":
        ...
    elif e.code == "CAS_RATE_LIMIT":
        ...
```

After:
```python
from xtb_api.exceptions import (
    InvalidCredentialsError, RateLimitedError, TwoFactorRequiredError,
)

try:
    await client.connect()
except InvalidCredentialsError:
    ...
except RateLimitedError:
    ...
except TwoFactorRequiredError:
    ...
except CASError:  # unknown CAS code, still caught
    ...
```

Affects: any caller that reads `e.code`. The `.code` attribute is kept
on `CASError` for forward compatibility with new XTB error codes.

---

## 13. Open questions / explicit deferrals

These are decisions intentionally not made in this document. They are
raised here so the reader sees what's *not* settled.

### O1 — Is `_ensure_http` loop-detection still needed after dropping the `asyncio.run` sync wrappers?

F12 flagged this as possibly vestigial. W5 adds a test to find out;
if the test proves the guard unnecessary, removal ships in the same
workstream. If the guard is still load-bearing, it stays.

### O2 — Python 3.11 support: which workstream owns it?

Draft schedule puts the `requires-python` bump in W3 alongside the
extras restructure. If the smoke test on 3.11 surfaces more than a
trivial set of issues, the bump moves to W5 (polish) and W3 ships
without it. Either way, it's in v1.x at the latest.

### O3 — W4 scope: full split vs. fixtures only?

W4 as drafted splits `ws/ws_client.py` into four modules *and* adds
wire-traffic fixtures. These can ship independently. If the split
becomes contentious, the wire fixtures can ship alone as a P2 fix for
F10 in a minor release.

### O4 — Decimal pricing?

Integrators (the 20% slice) sometimes ask for `Decimal` throughout the
pricing path. This is a v2.0-sized change (every `Quote`, `Position`,
`TradeResult` field plus the gRPC price scale/value pair). Explicitly
out of scope for v1.0 and not scheduled.

### O5 — Fresh-per-call pattern documentation?

W2 makes the long-lived client first-class. Should the ephemeral
per-call pattern (used today by `xtb-investor-pro`) be documented as a
supported alternative? Decision deferred to the W2 design doc; the
roadmap does not commit either way.

---

## 14. Appendix

### A. Severity ladder — concrete examples

- **P0** — "If a customer deploys this, they lose money": duplicate
  orders, silent wrong-thing, data loss, credentials leaked.
- **P1** — "Every user in the 50% automation-author slice writes a
  workaround": fresh-per-call clients, string-matching errors,
  pre-rounding volumes.
- **P2** — "A reader of the source says 'huh, this should be tighter'":
  unused defensive code, cosmetic fixes, latent edge cases that require
  specific conditions to manifest.

### B. Finding-ID stability policy

- F-numbers are assigned in this document and are stable forever.
- Subsequent specs (W1 design, W2 design, ...) reference findings by
  ID.
- If a finding is later discovered to be wrong, it is marked
  `[REJECTED]` with a note; the ID is not reused.
- New findings get the next available ID and go into a `§Addenda`
  section on this document if they surface during workstream
  implementation.

### C. Glossary

| Term | Meaning |
|---|---|
| **Ambiguous outcome** | A trade attempt where the library cannot determine whether the order reached the matching engine. Distinct from "rejected" (confirmed refusal) and "filled" (confirmed acceptance). |
| **reqId echo** | XTB xStation5 CoreAPI's default RPC response: the server echoes the request's `reqId` on the normal response channel. |
| **Push channel** | A separate status=1 stream on the same WebSocket for unsolicited updates (ticks, position changes). |
| **Ephemeral client** | `XTBClient` constructed, connected, used once, disconnected. The pattern `xtb-investor-pro` uses today. |
| **Long-lived client** | `XTBClient` that survives multiple operations and potentially multiple `asyncio.run()` cycles. Made first-class by W2. |

### D. Related documents

- [docs/superpowers/specs/2026-04-09-xtb-api-refactoring-design.md](./2026-04-09-xtb-api-refactoring-design.md)
  — the original v0.3.0 refactor spec that established the exception
  hierarchy.
- [docs/superpowers/specs/2026-04-10-publish-polish-design.md](./2026-04-10-publish-polish-design.md)
  — the publish-polish design behind v0.3.0/v0.4.0.
- [docs/superpowers/specs/2026-04-15-docs-refresh-v0.5-design.md](./2026-04-15-docs-refresh-v0.5-design.md)
  — the v0.5 docs-refresh pass.

---

End of design document.
