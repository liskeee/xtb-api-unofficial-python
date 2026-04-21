# CHANGELOG

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


## v0.7.2 (2026-04-21)

### Bug Fixes

- **auth**: Map CAS 404 to CAS_TGT_EXPIRED so AuthManager recovers automatically
  ([`42588e3`](https://github.com/liskeee/xtb-api-unofficial-python/commit/42588e396f7c712b8ef6a8a6c434f2ae420da56e))

XTB's CAS v1 service-ticket endpoint returns HTTP 404 ("TGT ... could not be found or is considered
  invalid") when the Ticket-Granting Ticket has been rotated or forcibly logged out server-side —
  not 401. Before this fix, only 401 was mapped to CAS_TGT_EXPIRED, so 404 fell through to the
  generic CAS_SERVICE_TICKET_FAILED code which AuthManager.get_service_ticket does not catch. The
  cached TGT never got invalidated, no fresh CAS login was attempted, and every subsequent request
  kept hitting the dead TGT until the local 8h timestamp expired.

Observed in prod: bot ran for hours with cached TGT "valid for 2h 44m" while every
  portfolio.sync.get_positions call failed with the 404. Manual recovery required deleting the
  session file and re-extracting via browser.

Also mirrors the fix into the v2 endpoint for symmetry.


## v0.7.1 (2026-04-20)

### Bug Fixes

- **auth**: Update navigation wait strategy for login
  ([`ee15864`](https://github.com/liskeee/xtb-api-unofficial-python/commit/ee15864592ded9136da4c4d99d02109f5021a3df))

* Change the wait strategy for navigating to the login page from "domcontentloaded" to "commit". *
  This adjustment addresses an issue with XTB's WAF that injects a synchronous bot-detection script,
  preventing the HTML parser from completing. * The new strategy ensures that the email input field
  is the real readiness gate for the login process.

### Documentation

- **examples**: Rewrite examples against v1.0 public API
  ([`2a25452`](https://github.com/liskeee/xtb-api-unofficial-python/commit/2a25452c357d6cbae8318d2f1ab29f9a78796f01))

The three example scripts still referenced an abandoned factory API (XTBClient.websocket(...),
  WSAuthOptions, WSCredentials, client.get_account_number(), client.ws.on(...)). They did not parse
  against current master and were misleading for anyone onboarding against v0.7.0 / the upcoming
  v1.0 surface.

Rewrite all three against the real public API:

- basic_usage.py: uses the XTBClient(email, password, account_number, ...) constructor, reports
  session_source after connect so a reader can see whether remember-device is working, and walks
  through balance / positions / search / quote. - live_quotes.py: subscribes via
  client.subscribe_ticks(symbol), using plain ticker names rather than the internal sym_key format
  (resolved internally now), with contextlib.suppress instead of bare try/except/pass on cleanup. -
  grpc_trade.py: rewritten as a typed-outcome consumer template with an exhaustive `match
  TradeResult.status:` over every TradeOutcome case. Gated behind XTB_EXAMPLE_TRADE=1 so running the
  file accidentally cannot submit a real order. Replaces the old raw-Chrome-CDP / GrpcClient
  example, which showed an internal integration no longer exposed on the public surface.

All three parse, import cleanly, and pass ruff check + format.


## v0.7.0 (2026-04-17)

### Bug Fixes

- **client**: Probe positions before JWT-refresh retry to avoid duplicate orders (F02, F13)
  ([`3433048`](https://github.com/liskeee/xtb-api-unofficial-python/commit/3433048b861d7ad447140d2d4867af9b0d1ff9b7))

Detect RBAC/AUTH_EXPIRED via grpc_status == 7 (not free-text error match). Before invalidating the
  JWT and retrying, probe live positions for a plausible match (symbol + side + volume). If found,
  return FILLED with the existing order_id — the first submission landed despite the RBAC error, and
  retrying would duplicate the order.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>

- **client**: Unknown symbol surfaces as REJECTED, not raised
  ([`f5f3a06`](https://github.com/liskeee/xtb-api-unofficial-python/commit/f5f3a06c286cdefd170340b12be078de433a8f86))

_execute_trade caught InstrumentNotFoundError from _resolve_instrument_id and turned it into a typed
  TradeResult (REJECTED / INSTRUMENT_NOT_FOUND), matching the WS path and the rest of W1's
  typed-outcome contract. Before this, gRPC-routed trades raised while WS-routed trades returned a
  result, forcing consumers to wrap every call in try/except.

Discovered while running the W1 live-validation script against a real account: the unknown-symbol
  path broke the outcome invariant that every trade method returns a TradeResult.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>

- **grpc**: Narrow except Exception to httpx.HTTPError in execute_order (F19)
  ([`85086a8`](https://github.com/liskeee/xtb-api-unofficial-python/commit/85086a854a2ba9e707342805f6832e4486f5331a))

The broad `except Exception` used to swallow unrelated bugs (ValueError, AssertionError) into a
  "failed trade" result. Narrowing to `httpx.HTTPError` keeps network/HTTP failures observable while
  letting genuine bugs bubble up with their traceback intact.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>

- **grpc**: Preserve full server error text (was clipped to 200 chars) (F22)
  ([`faa2a6b`](https://github.com/liskeee/xtb-api-unofficial-python/commit/faa2a6b77edd4bf0e26b2ae2de59c315b9b91230))

The 200-char cap lost debug-relevant tail (e.g. validation-error details past char ~180). Callers
  now get the full server message for logging.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>

- **ws**: Build TradeResult with TradeOutcome (was using removed success= kwarg)
  ([`564b1db`](https://github.com/liskeee/xtb-api-unofficial-python/commit/564b1dbc20c7e945461ffc1a849fb2491700658e))

The WS trade path (XTBWebSocketClient._execute_trade) was still constructing TradeResult with the
  removed success= kwarg. Since TradeResult now sets model_config = {"extra": "forbid"} and requires
  status: TradeOutcome, every buy()/sell() call raised pydantic.ValidationError.

Replace all three construction sites with TradeOutcome.REJECTED / TradeOutcome.FILLED, and add a
  regression smoke test exercising each branch.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>

- **ws**: Emit ProtocolError instead of RuntimeError on JSON decode failure (F21)
  ([`71e0150`](https://github.com/liskeee/xtb-api-unofficial-python/commit/71e0150ff7f6f8de32da732473fec42b8b5e6c16))

Malformed WS frames now surface as a typed ProtocolError. Consumers that catch `except
  ProtocolError` will now see decode failures instead of needing a bare RuntimeError catch.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>

- **ws**: Get_balance polls TOTAL_BALANCE until snapshot populates
  ([`eed72bc`](https://github.com/liskeee/xtb-api-unofficial-python/commit/eed72bc5a07ae71d611f3f5934628b8aa3da4578))

XTB's getAndSubscribeElement acknowledges immediately with an empty element list and pushes the
  populated xtotalbalance snapshot later over the same WebSocket. The naive single-shot call
  returned zeros for freshly-opened sessions — the live validator surfaced this as balance=0.0
  equity=0.0 on an account with real funds.

get_balance now polls the subscription with a 200ms cadence up to a 3000ms deadline (tunable via the
  new _BALANCE_SNAPSHOT_POLL_MS and _BALANCE_SNAPSHOT_MAX_WAIT_MS module constants) and returns the
  first response that carries an xtotalbalance payload. On timeout it falls back to the zeroed
  snapshot with a warning log so the contract is preserved.

The retry loop lives inside get_balance rather than the push-event layer; wiring subscription-push
  routing into the high-level reads is W4 scope. Three regression tests pin the fast-path,
  multi-poll, and timeout-fallback behaviors.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>

### Chores

- Add live-validation script + ignore session files
  ([`663464d`](https://github.com/liskeee/xtb-api-unofficial-python/commit/663464d8bd206b91b21d8bef27d75009f01c7eae))

scripts/validate_live.py is a re-runnable validator for the W1 typed-outcome surface against a real
  XTB account. Default mode is read-only (balance, positions, search + non-destructive typed-failure
  assertions). Live mode (--live AND XTB_VALIDATE_LIVE=1 — both required) also exercises buy+sell on
  a configurable ticker (default CIG.PL).

Uses a minimal inline .env parser to avoid adding python-dotenv as a dep. Accepts either
  XTB_ACCOUNT_NUMBER or XTB_USER_ID so it plays nicely with existing consumer .env files. --env-file
  lets callers point at an .env outside the repo.

Also extends .gitignore to cover the session cache files the library creates on connect
  (*_cookies.json, .xtb_session) — these hold auth material and must not be committed.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>

### Code Style

- Apply ruff format across src/ and tests/
  ([`a658a66`](https://github.com/liskeee/xtb-api-unofficial-python/commit/a658a6640639a121ee6ec40fca6968b3a764bcdf))

CI runs `ruff format --check` in addition to `ruff check`; four files drifted from the project
  format (collapsed arg lists, joined short statements). Pure formatting — no functional change.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>

- **tests**: Sort imports in exception re-export tests
  ([`e0a84a7`](https://github.com/liskeee/xtb-api-unofficial-python/commit/e0a84a7b142eda0d60b8ae4b74a84569bafda6d6))

Drop unused alias for RateLimitedError to keep ruff isort happy.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>

### Documentation

- **changelog**: Record W1 v1.0 changes
  ([`7011c2d`](https://github.com/liskeee/xtb-api-unofficial-python/commit/7011c2dceb8f5db5987d11f230e87709144c40ef))

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>

### Features

- **auth**: Dispatch CAS error codes to typed subclasses (F18)
  ([`3602fb3`](https://github.com/liskeee/xtb-api-unofficial-python/commit/3602fb36d1e9fab7fe121435db40dfd7e27d6cee))

`_cas_error_for_code(code, message)` picks the most specific `CASError` subclass. Consumers can now
  `except InvalidCredentialsError` instead of inspecting `.code` strings. Parent `CASError` still
  catches every case.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>

- **auth**: Expose SessionSource so consumers can verify TGT reuse
  ([`246ed60`](https://github.com/liskeee/xtb-api-unofficial-python/commit/246ed60f4991e8a9aa249bf7f0326727260ad7ed))

Context: XTB emails the account owner on every fresh CAS login. The library already had the plumbing
  to avoid this (TGT session-file cache with 8h TTL, deterministic fingerprint, rememberMe=True in
  v2 login), but there was no way for consumers to *observe* whether a given run was actually
  reusing the cached TGT or silently falling back to a fresh login. The first signal of a regression
  was an inbox notification.

Add a typed SessionSource enum and expose it via AuthManager.session_source /
  XTBClient.session_source plus a session_expires_at timestamp. Log the chosen source at INFO on
  every get_tgt() call so operators can verify reuse from server logs.

validate_live.py now prints a session-state banner before connect (files present/missing) and a
  "REUSED …" / "FRESH login — XTB will email" line after connect. Running the validator twice within
  8h must produce `session: REUSED` on the second run — if it instead reports `FRESH CAS login`
  twice, remember-device has regressed.

No behavioral change to the auth flow itself. The existing rememberMe/fingerprint/TGT-cache path is
  untouched; this commit is pure observability.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>

- **client**: Map trade results to TradeOutcome (F16)
  ([`3af913c`](https://github.com/liskeee/xtb-api-unofficial-python/commit/3af913c6e36c0d0856bab3b2a9ada7ac3e3121db))

BREAKING: TradeResult now carries a typed status: TradeOutcome and an optional error_code. Consumers
  inspecting TradeResult.error text for insufficient-volume / RBAC / empty-response conditions
  should switch to result.status and result.error_code instead.

`_poll_fill_price` now returns `(price, error_code)`; error_code is "FILL_PRICE_UNKNOWN" when the
  position did not appear within the retry budget.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>

- **exceptions**: Add AmbiguousOutcomeError(TradeError)
  ([`5892778`](https://github.com/liskeee/xtb-api-unofficial-python/commit/5892778775627e4b40646307dffaa6898b80cea9))

Distinguishes "send succeeded but broker response didn't confirm" from generic trade failure.
  Consumers can now `except AmbiguousOutcomeError` instead of string-matching on message text.

Closes F01, F14.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>

- **exceptions**: Add InvalidCredentialsError, AccountBlockedError, RateLimitedError,
  TwoFactorRequiredError
  ([`e7e7b29`](https://github.com/liskeee/xtb-api-unofficial-python/commit/e7e7b2943f78c3f3faf20eac02f1cedbdabd4b68))

Four CASError subclasses let consumers branch on auth-failure kind with typed catches instead of
  inspecting `.code` strings.

Closes F18.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>

- **grpc**: Empty trade response raises AmbiguousOutcomeError (F01, F14)
  ([`99a668c`](https://github.com/liskeee/xtb-api-unofficial-python/commit/99a668c008ea7204165f6e7a6177e0e120f94311))

BREAKING: Empty trade responses previously raised ProtocolError with the message 'gRPC call returned
  empty response'. Consumers string-matching that message must switch to `except
  AmbiguousOutcomeError`. Empty auth responses continue to raise AuthenticationError.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>

- **public**: Export TradeOutcome, AmbiguousOutcomeError, CAS subclasses
  ([`7daa506`](https://github.com/liskeee/xtb-api-unofficial-python/commit/7daa50674c6654f5fac33f664a4828e638559f47))

Promote the new types from previous W1 tasks to the top-level `xtb_api` namespace so consumers can
  `from xtb_api import TradeOutcome` without reaching into `xtb_api.types.trading` /
  `xtb_api.exceptions`.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>

- **types**: Add TradeOutcome enum
  ([`3eb1ecf`](https://github.com/liskeee/xtb-api-unofficial-python/commit/3eb1ecf547c744e0a42d8b29648f1642ebb8d81f))

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>

- **types**: Add TradeResult.status + error_code, success now derived
  ([`f651bdf`](https://github.com/liskeee/xtb-api-unofficial-python/commit/f651bdf3b386bb7fe32c7334e126f41571d03357))

BREAKING: TradeResult.success is a @property, not a pydantic field. Consumers must construct
  TradeResult with status=TradeOutcome.* instead of success=bool.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>

### Refactoring

- **grpc**: Derive RBAC error label from grpc_status (not string match) (F13)
  ([`9146219`](https://github.com/liskeee/xtb-api-unofficial-python/commit/914621993525c391fb5b223b8b91a3da27a7ce4d))

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>

### Testing

- End-to-end match-statement shape for TradeOutcome
  ([`545122e`](https://github.com/liskeee/xtb-api-unofficial-python/commit/545122ebf615276e5daa3a1bc541ae28f5b0351f))

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>

- **client**: Assert error_code signals fill-price poll exhaustion (F15, F40)
  ([`be063a3`](https://github.com/liskeee/xtb-api-unofficial-python/commit/be063a3f49504779c12588c8dd334b499a0c4d1c))

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>


## v0.6.0 (2026-04-17)

### Chores

- Ignore .worktrees/ directory
  ([`9ae4365`](https://github.com/liskeee/xtb-api-unofficial-python/commit/9ae436584a85ee3e3707cb265704bf6a4c7dfad8))

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>

### Documentation

- Add audit and roadmap design (2026-04-17)
  ([`6f77f5b`](https://github.com/liskeee/xtb-api-unofficial-python/commit/6f77f5ba6d09376bd5aacb1a13b78d31ac73b4c1))

Deep audit of xtb-api-python keyed to real-world usage in xtb-investor-pro. Catalogs 40 findings (2
  P0, 20 P1, 18 P2) across stability, error classification, and external-user ergonomics, each cited
  to file:line. Groups fixes into five workstreams (W1 typed outcomes + idempotent retry, W2
  loop-safe client, W3 Playwright-minimized auth, W4 transport split + wire fixtures, W5 install UX
  polish); W1+W2+W3 bundle into one breaking v1.0, W4 and W5 ship additively. No implementation —
  each workstream enters its own design+plan loop next.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>

### Features

- **api**: Add user authentication endpoint plan
  ([`59d00e9`](https://github.com/liskeee/xtb-api-unofficial-python/commit/59d00e93689f2da094e1783eaf566e1359593607))


## v0.5.4 (2026-04-15)

### Bug Fixes

- **ws**: Revert get_positions to reqId-based send
  ([#9](https://github.com/liskeee/xtb-api-unofficial-python/pull/9),
  [`d197b08`](https://github.com/liskeee/xtb-api-unofficial-python/commit/d197b08350e57a46b82adee5dcb206b2d068b852))

v0.5.3's push-channel collection was based on a wrong diagnosis. Live API probing confirms the
  xStation5 CoreAPI echoes getPositions on the NORMAL reqId response channel (status=0,
  response=[...]), not as push events. The original implementation was correct.

The 30s timeouts observed on the original 0.5.2 bot were something else — probably container-level
  networking / first-call timing — not a protocol mismatch. The wrong fix in 0.5.3 made the problem
  worse because get_positions() started returning [] instantly, causing the downstream bot to
  auto-close positions it mistakenly thought were gone from the broker.

Reverts the get_positions implementation to: res = await self.send("getPositions",
  {"getAndSubscribeElement": {"eid": POSITIONS}}, timeout_ms=30000) return
  parse_positions(self._extract_elements(res))

Keeps `parse_position_trade` helper in parsers.py — harmless refactor. Removes
  tests/test_get_positions_push.py — tested wrong behavior.

Verified against real XTB account: all 5 open positions returned in ~1-2s via normal reqId response.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>


## v0.5.3 (2026-04-15)

### Bug Fixes

- **ws**: Consume POSITIONS push channel in get_positions
  ([`b0156bc`](https://github.com/liskeee/xtb-api-unofficial-python/commit/b0156bcc328630fb5e80952d87794780a8e30c73))

XTB's xStation5 CoreAPI does not echo a reqId-correlated response for the `getPositions` RPC;
  position data arrives exclusively via status=1 push events with eid=POSITIONS. The previous
  implementation awaited a regular reqId-matched response and timed out after 30s on every call
  against a live account.

Fix: subscribe and consume the push burst. Register a one-shot 'position' handler, fire the
  subscribe RPC (do not await its reply), and collect pushed events until either a quiet period (no
  new position for 500 ms) or a max-wait ceiling (5 s) closes the window. Dedup by positionId so a
  retriggered snapshot does not duplicate entries.

parse_positions is refactored around a new parse_position_trade(trade) helper so the push handler
  and the (still-supported) element-list path share the single source of truth for xcfdtrade →
  Position mapping.

Tests: 8 new tests cover parser extraction, burst collection, dedup, empty-on-timeout, listener
  cleanup, and the not-connected guard.

Fixes the downstream xtb-investor-pro bot's "get_positions failed" timeouts observed immediately
  after the broker abstraction merge.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- **ws**: Drop unused parse_positions import
  ([`63b3263`](https://github.com/liskeee/xtb-api-unofficial-python/commit/63b3263b64ef76ad7759b26a70e8d6ec26e6c9b3))

### Code Style

- Ruff format test_get_positions_push.py
  ([`6e376a8`](https://github.com/liskeee/xtb-api-unofficial-python/commit/6e376a8cc1578d388f8469da3b49b02dee021841))

### Documentation

- Add design spec for v0.5 docs refresh
  ([`c55d839`](https://github.com/liskeee/xtb-api-unofficial-python/commit/c55d839534ff39f5da55ec920fe6457eb82fb458))

Captures the README/CONTRIBUTING/SECURITY drift between v0.4.x docs and the v0.5.2 surface (XTBAuth,
  InstrumentRegistry, fill-price polling, volume guard, inlined publish jobs, supported-versions
  table).

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Add implementation plan for v0.5 docs refresh
  ([`0a4e3dd`](https://github.com/liskeee/xtb-api-unofficial-python/commit/0a4e3ddab03ad6cc87b4789cf39c772d85ca6d75))

Pairs with the design spec at docs/superpowers/specs/2026-04-15-docs-refresh-v0.5-design.md and
  tracks the four tasks executed in 97bbada.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Refresh README, CONTRIBUTING, SECURITY to v0.5 state
  ([`97bbada`](https://github.com/liskeee/xtb-api-unofficial-python/commit/97bbada41434dacbf3139af6e26b70ad8a632ba6))

- README: document XTBAuth alias, InstrumentRegistry, post-fill TradeResult.price, and the
  volume-validation guard added in v0.5.0; drop stale 11,888+ symbol count. - CONTRIBUTING: trim
  "before enabling on master" framing now that PSR is live; list both semantic-release.yml and
  release.yml as required Trusted Publishers (PyPI matches the OIDC token's workflow filename
  exactly, and v0.5.2 inlined the publish jobs into semantic-release.yml). - SECURITY: bump
  supported-versions table from 0.3.x to 0.5.x.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>


## v0.5.2 (2026-04-15)

### Bug Fixes

- **ci**: Inline publish jobs in Semantic Release instead of reusable call
  ([`46c4ca1`](https://github.com/liskeee/xtb-api-unofficial-python/commit/46c4ca1c0cc82d2c96559d265e17c604cf5d7e82))

PyPI's Trusted Publishing does not support reusable workflows — the gh-action-pypi-publish action
  warns "Reusable workflows are not currently supported by PyPI's Trusted Publishing" and rejects
  uploads from workflow_call contexts because the OIDC token Build Config URI points at the caller
  rather than the publishing workflow file.

Inline the build, publish-pypi, publish-testpypi, and attach-assets jobs directly into
  semantic-release.yml so the top-level workflow filename matches the PyPI Trusted Publisher.
  release.yml is retained for manual recovery (release:published event and workflow_dispatch).

Requires PyPI to trust semantic-release.yml as well as release.yml.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

### Continuous Integration

- Add workflow_dispatch trigger to Release for manual re-publishing
  ([`e03863d`](https://github.com/liskeee/xtb-api-unofficial-python/commit/e03863d8d5428c0af75273e8618ee1c7958be8df))

Allows manually re-triggering a build+publish for any existing tag from the Actions UI. Needed to
  recover v0.5.0 and v0.5.1, which were tagged but failed to publish to PyPI.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>


## v0.5.1 (2026-04-15)

### Bug Fixes

- **ci**: Chain Release workflow from Semantic Release via workflow_call
  ([`b0c2b7a`](https://github.com/liskeee/xtb-api-unofficial-python/commit/b0c2b7a364feae18655595c6c0ed93da604ead5f))

The Release workflow listens on release:published, but events triggered by GITHUB_TOKEN (used by
  python-semantic-release) do not fire downstream workflows. As a result, v0.5.0 was tagged and
  released but never built or published to PyPI.

Add workflow_call trigger to Release with a tag input, and invoke it as a dependent job from
  Semantic Release when psr reports released=true. The release:published trigger is kept for manual
  releases.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

### Chores

- Remove dangling reference-ts submodule gitlink
  ([`930a9b7`](https://github.com/liskeee/xtb-api-unofficial-python/commit/930a9b7497141bb169f4902c8612a20690873b9e))

The tree contained a gitlink at reference-ts with no matching entry in .gitmodules, which caused a
  `No url found for submodule path 'reference-ts'` warning in every workflow checkout cleanup step.
  The local reference-ts/ clone is retained on disk and now gitignored.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>


## v0.5.0 (2026-04-15)

### Chores

- Adopt python-semantic-release and commit-lint
  ([`be85a80`](https://github.com/liskeee/xtb-api-unofficial-python/commit/be85a8007b674bfaa16a994741617140df56045d))

Automates versioning and changelog generation from Conventional Commits: merges to master compute
  the next version, update pyproject.toml + CHANGELOG.md, tag, and publish to PyPI via Trusted
  Publishing.

- Add .github/workflows/commit-lint.yml — enforces Conventional Commit PR titles via
  amannn/action-semantic-pull-request - Add .github/workflows/semantic-release.yml — runs
  semantic-release after successful CI on master/next - Update release.yml and ci.yml to coordinate
  with the new flow - Add [tool.semantic_release] config to pyproject.toml - Rewrite CONTRIBUTING.md
  release section — no more hand-edited CHANGELOG, PR titles drive the release

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

### Code Style

- Apply ruff format and import sort
  ([`2f0d9b8`](https://github.com/liskeee/xtb-api-unofficial-python/commit/2f0d9b8c40b81d3349cee00067d11a9200e4d565))

Why: CI lint stage was failing on I001 (unsorted imports in src/xtb_api/__init__.py) and ruff format
  --check flagged several files after recent broker-adapter changes.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

### Documentation

- **plan**: Defer version/CHANGELOG to semantic-release
  ([`4e0b766`](https://github.com/liskeee/xtb-api-unofficial-python/commit/4e0b7667b9efb26d2e3097d503cbfc24507e95d6))

Repo uses python-semantic-release. Drop manual version bump and CHANGELOG edit from Task 1 —
  conventional-commit messages in the remaining tasks cause semantic-release to compute the minor
  bump (0.4.0 → 0.5.0) and write the CHANGELOG entry automatically on merge to master. Plan shrinks
  from 7 to 6 tasks.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- **plan**: V0.5 broker-adapter support
  ([`9047259`](https://github.com/liskeee/xtb-api-unofficial-python/commit/9047259b77b3313db7aca6c016379df1da84d138))

Implementation plan for the additive changes needed to unblock the xtb-investor-pro broker
  abstraction refactor: volume validation, TradeResult.price population, persistent
  InstrumentRegistry, XTBAuth alias. Minor bump 0.4.0 → 0.5.0.

Companion plan:
  /home/liske/Projects/xtb-investor-pro/docs/superpowers/plans/2026-04-15-broker-abstraction-refactor.md

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

### Features

- Expose AuthManager as XTBAuth for cleaner imports
  ([`e0b5dd3`](https://github.com/liskeee/xtb-api-unofficial-python/commit/e0b5dd39a9192cee1a3efecbb827f5b522883972))

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- **client**: Populate TradeResult.price via post-trade position poll
  ([`54053d6`](https://github.com/liskeee/xtb-api-unofficial-python/commit/54053d656f91e7e7ee8ccd52dd7c6eaba6f8add5))

Adds _poll_fill_price() which queries get_positions() up to 3 times after a successful trade to
  resolve the actual fill price. Failed trades short-circuit before polling. Returns None gracefully
  if the position does not appear within the retry window.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- **client**: Reject buy/sell with volume < 1 before touching gRPC
  ([`3cbd50f`](https://github.com/liskeee/xtb-api-unofficial-python/commit/3cbd50fc3475309dfd0150cd27434bc0399278bc))

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- **instruments**: Add persistent InstrumentRegistry module
  ([`f98a98b`](https://github.com/liskeee/xtb-api-unofficial-python/commit/f98a98b0f4908aaf2882fdd9953233810cabc1c2))

### Refactoring

- **client**: Clarify fill-price poll contract and stub coverage
  ([`51fa99d`](https://github.com/liskeee/xtb-api-unofficial-python/commit/51fa99d53202a860ce25515bdc71bbb2136dc0ff))

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- **client**: Simplify volume rounding and add boundary tests
  ([`f0647ca`](https://github.com/liskeee/xtb-api-unofficial-python/commit/f0647ca0fb6e9ae249d6901d480ae16875b5d255))

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- **instruments**: Tighten populate contract and _load validation
  ([`d2205a2`](https://github.com/liskeee/xtb-api-unofficial-python/commit/d2205a22fffd36725b541981e8bb83ffd14d67ef))

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

### Testing

- Smoke-check v0.5 public surface
  ([`3d0d5f9`](https://github.com/liskeee/xtb-api-unofficial-python/commit/3d0d5f98c02e4f3b477fd111883d76b9f4c12762))

- **instruments**: Assert populate returns only new matches
  ([`867f8c0`](https://github.com/liskeee/xtb-api-unofficial-python/commit/867f8c0e6c50638639e8a1c7b6893776da2dd4f6))


## v0.4.0 (2026-04-10)

### Bug Fixes

- Add BUY/SELL enum mismatch guard test and docstring warnings
  ([`5e1df38`](https://github.com/liskeee/xtb-api-unofficial-python/commit/5e1df385f1cb3915e0bfde08d85c00d734fdaeb2))

WebSocket (Xs6Side: BUY=0, SELL=1) and gRPC (SIDE_BUY=1, SIDE_SELL=2) use different side constants.
  Add guard test to prevent accidental conflation and docstring warnings on all trading methods.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- **auth**: Cast totp.now() return value for mypy
  ([`86d4388`](https://github.com/liskeee/xtb-api-unofficial-python/commit/86d4388cbd13d9515ead3bd0bc51e84b4d364cf5))

pyotp has no type stubs, so totp.now() is inferred as Any and propagates to the method return.
  Wrapping in str() makes the return type explicit.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- **auth**: Narrow session-file TGT to str for mypy 1.13 compatibility
  ([`75cae99`](https://github.com/liskeee/xtb-api-unofficial-python/commit/75cae99fd6d6bdcc5044eb6b0ff03c9ca12bbca0))

- **auth**: Prevent browser resource leak on auth error
  ([`1675411`](https://github.com/liskeee/xtb-api-unofficial-python/commit/167541158b2a60d3ee77bde7662ffac69e6e7471))

Wrap login() and submit_otp() in try/finally to ensure close() is called when an exception occurs
  mid-flow, preventing orphaned Chromium processes from playwright.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- **auth**: Use next TOTP window code near 30s boundary
  ([`65d244f`](https://github.com/liskeee/xtb-api-unofficial-python/commit/65d244f8a00214023e27603221830026e1128b02))

When fewer than 5 seconds remain in the current TOTP window, use the next window's code to avoid
  server rejection due to transit delay (~6.6% failure rate at window boundaries).

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- **auth**: Wait for next TOTP window instead of returning future code
  ([`9cf0dbf`](https://github.com/liskeee/xtb-api-unofficial-python/commit/9cf0dbfb7fbae38c325669ca80916a275fefc955))

The previous near-boundary fix returned the *next* window's code when <5s remained, which only works
  if the server tolerates +1 window drift. Switch to awaiting asyncio.sleep until the new window
  starts, so the generated code is guaranteed valid for its full lifetime regardless of server
  tolerance. Threshold lowered to 2s to match the empirical ~6.6% failure rate (2/30) instead of
  16.7% (5/30).

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- **browser-auth**: Type-annotate playwright attrs via TYPE_CHECKING
  ([`f8c5c6b`](https://github.com/liskeee/xtb-api-unofficial-python/commit/f8c5c6b751f627d564f89705b53806c4afc21453))

Adds a TYPE_CHECKING-guarded import of Browser/Page/Playwright/Response from playwright.async_api
  and class-level annotations for the three `_browser`, `_page`, `_playwright` attributes so mypy
  stops inferring them as None. Adds a `_on_response` parameter annotation and three `assert ... is
  not None` narrows in `login()` after the launch block.

Zero runtime cost — TYPE_CHECKING never evaluates to True at runtime, so playwright remains a lazy
  runtime import.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- **cas**: Narrow Optional types and annotate _browser_auth
  ([`ce23c6f`](https://github.com/liskeee/xtb-api-unofficial-python/commit/ce23c6f320148f29d5e5903d6abaa16556e270cb))

Three mypy fixes in cas_client.py: - Class-level annotation `_browser_auth: BrowserCASAuth | None =
  None` with a TYPE_CHECKING guard import (keeps browser_auth import lazy at runtime; from
  __future__ import annotations already stringifies it). - Narrow `cookie.value is not None` before
  assigning into the cookie dict in _save_cookies(). - Bind `now.utcoffset()` to a local before
  checking/using it so mypy can narrow timedelta | None across the two calls.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- **ci**: Anchor changelog section regex to avoid prefix match
  ([`52f925f`](https://github.com/liskeee/xtb-api-unofficial-python/commit/52f925f3a74da368a3b82fc56f499cfd4eb4c75a))

- **packaging**: Move dependencies back into [project] table
  ([`758fa00`](https://github.com/liskeee/xtb-api-unofficial-python/commit/758fa000eb1d01a929596829913ee8677f761ca7))

- **utils**: Cast price_to_decimal to satisfy mypy
  ([`22bb090`](https://github.com/liskeee/xtb-api-unofficial-python/commit/22bb09050f068718c960c2d26e7a92204074af85))

mypy was inferring Any from the scalar multiplication; an explicit float() cast on price.value gives
  it the concrete type it wants.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- **ws**: Prevent duplicate symbol downloads with asyncio.Lock
  ([`934dc9d`](https://github.com/liskeee/xtb-api-unofficial-python/commit/934dc9df92893d661d8c64b69a9b6418975110d2))

Two concurrent search_instrument() calls could both see _symbols_cache as None and download 11k+
  instruments twice. Add asyncio.Lock with double-checked locking to ensure only one download
  occurs.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- **ws**: Prevent tick subscription leak in get_quote on parse error
  ([`ed28fc9`](https://github.com/liskeee/xtb-api-unofficial-python/commit/ed28fc9bc46e4e1f3f52bac88d8297fe184e97e0))

Use try/finally to ensure unsubscribe_ticks is always called after subscribe_ticks in get_quote(),
  even if parse_quote raises. Prevents server from pushing ticks that nobody reads.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- **ws,client**: Cast trade side to Literal and narrow Optional types
  ([`0c325c1`](https://github.com/liskeee/xtb-api-unofficial-python/commit/0c325c110bd3d829e4a2bc02cdd27e7557e3b24d))

Final batch of mypy fixes to clear the baseline: - Four `side=cast("Literal['buy', 'sell']", side)`
  casts at the TradeResult construction sites in ws_client.py (3) and client.py (1). - Two explicit
  return-type casts for the dict/list accessors in ws_client.py that were returning Any from generic
  dict indexing. - Assert `self._ws is not None` before the main async-for loop so mypy narrows
  `ClientConnection | None` to `ClientConnection`.

After this commit, `mypy src/` is clean across all source files.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

### Chores

- Final polish from publish-ready sweep
  ([`b5e0c23`](https://github.com/liskeee/xtb-api-unofficial-python/commit/b5e0c230224d484efd5e2369e4c65d021b656438))

- Drop redundant string quotes from TYPE_CHECKING annotations in browser_auth (future annotations
  import makes them unnecessary, ruff UP037) - Wrap over-long TradeResult construction line in
  ws_client (ruff E501) - Combine nested with statements in chromium-missing test (ruff SIM117) -
  Apply ruff format to the two new test files (test_doctor, test_browser_auth_chromium_missing) -
  Drop unused pyotp.* wildcard from mypy overrides; keep the bare pyotp entry

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- **packaging**: Add author email, project URLs, 3.13 classifier, pyotp mypy override
  ([`2c5fd71`](https://github.com/liskeee/xtb-api-unofficial-python/commit/2c5fd71d4bd31a03f20a2dc1aaab09d334c9b65e))

- **pre-commit**: Add mypy and generic hygiene hooks
  ([`8ec88c5`](https://github.com/liskeee/xtb-api-unofficial-python/commit/8ec88c50c3db9ceca6749bc33eeb61124780d453))

- **pre-commit**: Add playwright to mypy hook deps
  ([`b7e536d`](https://github.com/liskeee/xtb-api-unofficial-python/commit/b7e536d91c37a963d7aa17635b24439297946957))

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

### Code Style

- Apply ruff format to _filter_cached_symbols
  ([`4608738`](https://github.com/liskeee/xtb-api-unofficial-python/commit/46087388325a000df733bbe9683614cd68d6f124))

The extracted helper had its filter condition split across 3 lines, but ruff's line-length config
  keeps it on one line. Reformat to match.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Fix ruff lint (unused vars in test_ws_client)
  ([`347e2d5`](https://github.com/liskeee/xtb-api-unofficial-python/commit/347e2d5937801bf1dccc0be484eec8de45b4810f))

### Continuous Integration

- Add tag-triggered release workflow with PyPI Trusted Publishing
  ([`dc2c355`](https://github.com/liskeee/xtb-api-unofficial-python/commit/dc2c355ca6d636aa9f72ead1a6651274f7eee4c5))

- Add typecheck + build jobs, Python 3.12/3.13 matrix, concurrency
  ([`5828634`](https://github.com/liskeee/xtb-api-unofficial-python/commit/582863403740908f90cef8977a01c4c30e1d310e))

### Documentation

- Add CONTRIBUTING.md with dev setup and release procedure
  ([`553eb5f`](https://github.com/liskeee/xtb-api-unofficial-python/commit/553eb5f400be880bca208fbbdbd48fe89a03c69b))

Covers development environment setup, running tests/lint/mypy, pull-request guidelines, the
  tag-driven release workflow with TestPyPI dry-runs, and the one-time Trusted Publisher setup on
  PyPI and TestPyPI.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Add MIT LICENSE file
  ([`732bddf`](https://github.com/liskeee/xtb-api-unofficial-python/commit/732bddf56ac72948de463e494dc16c2ea3b26173))

- Add SECURITY.md disclosure policy
  ([`7c0d7c0`](https://github.com/liskeee/xtb-api-unofficial-python/commit/7c0d7c081dc726e89d5c8e66b53a5d2bf103ff0d))

Responsible-disclosure contact, supported version table, and scope statement clarifying that XTB
  server-side issues are out of scope but credential/token handling in the client is in scope.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- **changelog**: Add 0.3.0 entry with Keep-a-Changelog format
  ([`2bd1d17`](https://github.com/liskeee/xtb-api-unofficial-python/commit/2bd1d17c99881c99b143e98fd64f8ed5713c769f))

Promotes the previous 0.2.0 (Unreleased) block to a dated release and adds the 0.3.0 entry
  summarising the publish-polish work.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- **contributing**: Clarify changelog flow in release procedure
  ([`618d11d`](https://github.com/liskeee/xtb-api-unofficial-python/commit/618d11de75d0031fb73dc451e73365a2cf67233e))

Release step 2 no longer assumes a `## Unreleased` staging heading exists — adding a new dated entry
  works either way.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- **plans**: Add publish-polish implementation plan (19 tasks)
  ([`5ee9b90`](https://github.com/liskeee/xtb-api-unofficial-python/commit/5ee9b900dea4f0e40ebcf44d2d029289325e9ee2))

Detailed bite-sized plan for the first PyPI release, covering metadata fixes, mypy cleanup of 25
  baseline errors, CI hardening, Trusted Publishing release workflow, and the xtb-api doctor CLI.
  Maps directly to docs/superpowers/specs/2026-04-10-publish-polish-design.md.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- **readme**: Add badges, requirements, and post-install Chromium callout
  ([`98f078c`](https://github.com/liskeee/xtb-api-unofficial-python/commit/98f078c425fea17bed99d8f2431c622139b9342f))

Adds PyPI/Python/CI/License badges at the top and replaces the Install section with a Requirements +
  Install + REQUIRED post-install callout block, making the mandatory `playwright install chromium`
  step impossible to miss.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- **specs**: Add publish-polish design for PyPI release
  ([`db9f042`](https://github.com/liskeee/xtb-api-unofficial-python/commit/db9f04279037acc70e5b63367516521056e1c353))

Brainstormed design covering metadata/licensing fixes, CI hardening, Trusted Publishing release
  workflow, and post-install Chromium UX (doctor command). Targets first public PyPI release as
  v0.3.0.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

### Features

- **auth**: Translate missing-Chromium error to CASError with install hint
  ([`2f79ae8`](https://github.com/liskeee/xtb-api-unofficial-python/commit/2f79ae89e92f66e21f58f3de2a0d3c05aa8d9b86))

Wraps the chromium.launch() call in a nested try/except inside the existing outer try so that
  playwright's "Executable doesn't exist" error becomes CASError("BROWSER_CHROMIUM_MISSING",
  <friendly message>) pointing the user at `playwright install chromium` and the README.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- **cli**: Add 'xtb-api doctor' command for install verification
  ([`f253f59`](https://github.com/liskeee/xtb-api-unofficial-python/commit/f253f59346623b946370637e1e5c2f82d484956b))

- **version**: Derive __version__ from importlib.metadata
  ([`0150dae`](https://github.com/liskeee/xtb-api-unofficial-python/commit/0150dae8aac0dede056492ff613433879cfb9c81))

pyproject.toml is the single source of truth; runtime lookup via importlib.metadata avoids version
  drift between package metadata and the __version__ attribute.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

### Refactoring

- **ws**: Extract _filter_cached_symbols helper
  ([`4436a5a`](https://github.com/liskeee/xtb-api-unofficial-python/commit/4436a5af75c06238f61426f85a383cd6b0a4b90f))

The substring-match list comprehension was duplicated 3 times in search_instrument after the
  cache-race fix. Extract into a single helper so future filter changes can't drift between call
  sites.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

### Testing

- **auth**: Cover browser login() cleanup on pre-2FA exception
  ([`f020ba0`](https://github.com/liskeee/xtb-api-unofficial-python/commit/f020ba07ba1d375da7cdd4b524aa4128279ac2d2))

The submit_otp() cleanup path was already tested. Add the symmetric test for login(): if
  chromium.launch raises before 2FA detection, the try/except BaseException block must call close()
  to release the playwright process.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>


## v0.3.0 (2026-04-10)

### Bug Fixes

- Add .env to .gitignore, remove personal email from pyproject.toml
  ([`2a97269`](https://github.com/liskeee/xtb-api-unofficial-python/commit/2a97269c578548418474d6531807f98d336860b5))

- Address all code review findings from PR #1
  ([`d70a541`](https://github.com/liskeee/xtb-api-unofficial-python/commit/d70a5418c7c5337cfbdd66d0ddd134cc69110fb0))

CRITICAL fixes: - Remove blind trade retry that could submit duplicate orders; only retry on RBAC
  auth errors - Forward stop_loss/take_profit params to gRPC protobuf (was silently ignored) -
  Secure session file with 0600 permissions to protect TGT - Reuse httpx.AsyncClient in CASClient
  instead of creating per-request

HIGH fixes: - Fix reconnection race: reset _reconnecting flag on failure so retries work - Replace
  all deprecated asyncio.get_event_loop() with get_running_loop() - Replace RuntimeError with
  XTBConnectionError in _cleanup pending futures

MEDIUM/LOW fixes: - Fix get_quote subscription leak (unsubscribe after getting quote) - Fix
  CASClient config mutation (model_copy instead of mutating caller's config) - Fix is_tgt_valid dead
  logic (identical branches) - Fix stale aiohttp comment in auth_manager - Fix f-string logger
  formatting to lazy % style - Fix all B904 (raise from) in browser_auth and cas_client - Fix E501
  line length in browser_auth - Fix E731 lambda assignments in tests - Clean up unused test imports
  and stale async-with mock patterns

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Address second round of code review findings
  ([`20e080e`](https://github.com/liskeee/xtb-api-unofficial-python/commit/20e080e44b5a0d379bc16b90653a79ff79322e59))

- Add invalidate_jwt() public method to GrpcClient (encapsulate internals) - Fix SL/TP merge to use
  `is not None` (preserve 0.0 values) - Add async callback support in ws_client._emit() via
  inspect.isawaitable() - Add max reconnect attempts (10) with ReconnectionError - Use
  _intentional_disconnect flag instead of mutating config - Add AuthManager.aclose() and call it
  from XTBClient.disconnect() - Move `import re` to module-level in cas_client.py - Bump version to
  0.2.0 - Add 73 new tests (156 total): decimal places, connect/disconnect, trade execution

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Address third round of code review findings
  ([`3bfa309`](https://github.com/liskeee/xtb-api-unofficial-python/commit/3bfa309cac35f8d844de09dfd07c34a783bffef2))

- Fix _schedule_reconnect to check attempt limit before rescheduling - Fix sync disconnect() race:
  capture ws ref before cleanup nulls it - Narrow _emit RuntimeError catch to only coroutine
  scheduling failures - Fix session file: actually chmod 0600 when permissions are too open - Fix
  _parse_trade_response: reject data frames with error trailers - Fix login_with_two_factor: use
  resp.cookies instead of parsing Set-Cookie - Add 10 AuthManager tests (session file, TGT cache,
  2FA, aclose)

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Correct 2FA auth flow — use v2/tickets with loginTicket payload
  ([`4f821fa`](https://github.com/liskeee/xtb-api-unofficial-python/commit/4f821fa31e614493e2f17cec5cdacc8a9863dfc1))

- 2FA sends to v2/tickets (same endpoint as login), NOT v2/tickets/two-factor - Payload: loginTicket
  + token + fingerprint + twoFactorAuthType - Time-Zone header: minutes format (e.g. '60') instead
  of ±HHMM - TGT extraction from JSON body + Set-Cookie CASTGT fallback - Backward compat:
  session_id kwarg still works as alias - Added .gitignore - All 62 tests pass

- Encode account_number as varint in CreateAccessToken protobuf
  ([`e386241`](https://github.com/liskeee/xtb-api-unofficial-python/commit/e386241bfcc2ee47c4b263f9e333cf8b49b187f5))

Account.number field is uint64 (wire type 0), not string. Encoding it as a length-delimited string
  caused 'Person does not have given account' error from the gRPC auth service.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Persistent device fingerprint + rememberMe=true
  ([`f9b3f9e`](https://github.com/liskeee/xtb-api-unofficial-python/commit/f9b3f9e00590e5fefe0702a8ce242818a521d5e9))

- Set rememberMe: true in CAS login to persist session - Inject consistent fingerprint into browser
  auth localStorage (matches REST CAS fingerprint) to avoid 'new device' emails - Both REST and
  browser auth paths now use same device identity

- Retry with target rediscovery on Worker scope shutdown
  ([`b92dc92`](https://github.com/liskeee/xtb-api-unofficial-python/commit/b92dc9298c3706caeccd815bd2ebfe639af89dd2))

- Update login form selectors for new xStation5 UI
  ([`f555312`](https://github.com/liskeee/xtb-api-unofficial-python/commit/f555312131877a5eab8537d062e9c3429ca9cb33))

The xStation5 web app was refactored — login form no longer uses named inputs (xslogin/xspass) or a
  specific button class. Now uses generic textbox roles and a 'Login' button.

Updated selectors in BrowserCASAuth.login(): - Email: input[name='xslogin'] →
  get_by_role('textbox').first - Password: input[name='xspass'] → get_by_role('textbox').nth(1) -
  Submit: input[type='button'].xs-btn-ok-login → get_by_role('button', name='Login')

2FA form (submit_otp) unchanged — placeholder 'Wprowadź kod tutaj' and button 'Weryfikacja' still
  match.

- Update Playwright Chromium path patterns for v1.58+ (chrome-linux64 layout)
  ([`5fc7572`](https://github.com/liskeee/xtb-api-unofficial-python/commit/5fc7572eda5d6e9f9ee7066eb71a85ccdfb7440c))

- Xs6side enum (BUY=0, SELL=1) + shadow-piercing OTP submit
  ([`89c0fd3`](https://github.com/liskeee/xtb-api-unofficial-python/commit/89c0fd3c6d2ab8691349902e17b281e0c7e179b9))

- Fix Xs6Side enum to match xStation6 WebSocket values (BUY=0, SELL=1) - Rewrite submit_otp with
  Playwright shadow-piercing selectors - Remove manual Shadow DOM JS traversal (70 lines → 5 lines)
  - Clean up __pycache__ from tracking

### Chores

- Add ruff, mypy, CI workflow, pre-commit config (Phase 0)
  ([`0b53730`](https://github.com/liskeee/xtb-api-unofficial-python/commit/0b53730b1331b7a442526eb2c58e1cf34545805a))

- Add ruff and mypy configuration to pyproject.toml - Create GitHub Actions CI workflow (lint +
  test) - Add pre-commit config with ruff hooks - Add py.typed PEP 561 marker - Fix import sorting
  (ruff I001) - Fix re-export patterns (F401) in __init__.py files - Migrate str+Enum to StrEnum
  (UP042)

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Gitignore uv.lock
  ([`11ceee4`](https://github.com/liskeee/xtb-api-unofficial-python/commit/11ceee40ad8beed941dc078f3c57f2f8120d00f8))

- Remove debug/live test scripts from repo
  ([`51b4d4a`](https://github.com/liskeee/xtb-api-unofficial-python/commit/51b4d4a064d7656e44e430d35d04d91fd26b86c0))

### Code Style

- Apply ruff format to pass CI lint check
  ([`d92eee5`](https://github.com/liskeee/xtb-api-unofficial-python/commit/d92eee55414e669270f83da712c1fafb1bf1bc93))

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

### Documentation

- Add refactoring design spec for public PyPI release
  ([`7fc121b`](https://github.com/liskeee/xtb-api-unofficial-python/commit/7fc121b5910a58db38d4deae45437c6541f93830))

Comprehensive design covering unified XTBClient API, exception hierarchy, auth session reuse,
  aiohttp→httpx migration, browser mode removal, and 9-phase execution plan.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

### Features

- Add get_orders() method for pending orders
  ([`c00f475`](https://github.com/liskeee/xtb-api-unofficial-python/commit/c00f4757b57063668486a702d1a7cfea0d0a3b63))

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Add semantic exception hierarchy (Phase 1)
  ([`471d18f`](https://github.com/liskeee/xtb-api-unofficial-python/commit/471d18f1603a2b5527130a31179aae53f55804be))

- Create xtb_api.exceptions with XTBError base and semantic subclasses: XTBConnectionError,
  AuthenticationError, CASError, ReconnectionError, TradeError, InstrumentNotFoundError,
  RateLimitError, XTBTimeoutError, ProtocolError - CASError now subclasses AuthenticationError
  (backward-compatible) - Replace all RuntimeError/TimeoutError raises in ws_client.py and
  grpc/client.py with specific exception types - Re-export CASError from types.websocket for
  backward compatibility - Add test_exceptions.py with hierarchy and backward-compat tests

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Authmanager — high-level auth with auto-TOTP and browser fallback
  ([`82ae273`](https://github.com/liskeee/xtb-api-unofficial-python/commit/82ae273287d25a2dca0228c0f419a1dc1d6cf2aa))

- New AuthManager class encapsulating full TGT auth chain - Cache → REST CAS → Playwright headless →
  auto-TOTP - Prefer browser OTP path when browser session active (WAF blocks REST 2FA) - Catch
  non-CASError exceptions from WAF (aiohttp ContentTypeError) - pyotp as optional dependency - 18
  new tests (83 total)

- Authmanager.create_authenticated_client() for one-line WS setup
  ([`efdce3c`](https://github.com/liskeee/xtb-api-unofficial-python/commit/efdce3ce486d2e62695c14d1c42f06a48349606b))

- Authmanager.execute_trade() + search_instruments() — full gRPC/WS trading API
  ([`31b1379`](https://github.com/liskeee/xtb-api-unofficial-python/commit/31b1379eafad5efcf85e1d0a5d1dfd1050a4eb44))

- Chromesession — headless Chrome for gRPC without manual browser
  ([`e2a5a4b`](https://github.com/liskeee/xtb-api-unofficial-python/commit/e2a5a4bca09b67f8106df8d43ff2b9d0cc41b5ff))

- Grpc-web trading module via Chrome CDP Worker
  ([`795d448`](https://github.com/liskeee/xtb-api-unofficial-python/commit/795d4485061e8f48ae790d49ca0405e98e67bbb2))

- GrpcClient: trading via ipax.xtb.com through Chrome Worker CDP - Proto encoder/decoder matching
  xStation5 HAR captures - JWT auth with TGT + Account scope (acn/acs) via CreateAccessToken -
  buy()/sell()/execute_order() async API - XTBClient.grpc() factory method - All 62 existing tests
  pass

Endpoints: NewMarketOrder, CreateAccessToken, SubscribeNewMarketOrderConfirmation

Tested: 5/5 live trades executed successfully (BUY + SELL CIG.PL)

- Initial Python port of xtb-api-unofficial
  ([`7fbaa33`](https://github.com/liskeee/xtb-api-unofficial-python/commit/7fbaa332fb75f0012edacc275338b453e410afaa))

- Native httpx transport for gRPC-web (no Chrome CDP needed)
  ([`052df1a`](https://github.com/liskeee/xtb-api-unofficial-python/commit/052df1af041827be2700a6e0fb0a1f618260d138))

- Add _grpc_call_native() using httpx as PRIMARY transport - CDP worker/page/isolated-world as
  fallback only - cdp_url=None enables native-only mode - get_jwt() accepts TGT directly (not
  service ticket) - Increase get_positions timeout to 30s - Add httpx>=0.27 to dependencies -
  ChromeSession refactored to subprocess.Popen

- **auth**: Persist CAS cookies between restarts
  ([#2](https://github.com/liskeee/xtb-api-unofficial-python/pull/2),
  [`56ead92`](https://github.com/liskeee/xtb-api-unofficial-python/commit/56ead9286d6283dd76479c2ea3c364ebcb71d14e))

* feat(auth): persist CAS cookies between restarts

Adds optional cookies_file support to CASClient and AuthManager so that CAS cookies (CASTGC + device
  fingerprint) survive process restarts. This prevents XTB from sending 'new device' login
  notification emails every time the bot reconnects.

Changes: - CASClientConfig: add cookies_file field - CASClient: load persisted cookies into
  httpx.AsyncClient on startup, save merged cookies (chmod 0600) after every successful login and
  service-ticket request - AuthManager: accept cookies_file parameter, auto-derive from session_file
  when not provided (e.g. data/xtb_session_cookies.json)

Backward compatible: cookies_file defaults to None (no persistence).

* fix(auth): detect event loop change in CASClient to prevent stale httpx client

get_tgt_sync() uses asyncio.run() which creates and closes an event loop. The httpx.AsyncClient
  created inside that loop becomes a zombie — is_closed returns False but any request raises
  RuntimeError('Event loop is closed').

Track the event loop in _ensure_http() and replace the client when the loop changes, preventing the
  'Event loop is closed' crash on reconnect.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

* fix(grpc): use frame-based parsing to prevent false-positive success on rejected trades

The old string-matching logic ('grpc-status: 0' in response_text) could match as a substring in
  base64 error details (e.g. grpc-status: 16 contains '0'), and 6-byte null-prefixed binary data
  could pass the has_data_frame check. This meant rejected trades could be reported as success=True.

Now parse actual gRPC frames (data flag=0x00, trailer flag=0x80), extract grpc-status as an integer
  from trailer headers, and only return success when trailer status is exactly 0.

* test(auth): add missing cookie persistence tests for commit 7c5d978

Adds 9 tests covering the cookie persistence feature that shipped without tests: - cookies saved
  after login with 0600 permissions - cookies loaded into httpx client on init - cookies_file
  auto-derived from session_file path - corrupt/empty/non-dict JSON handled gracefully - cookie
  merge preserves existing cookies on subsequent login - file permissions enforced at 0600 - cookies
  loaded even when TGT/session is expired

* style: fix ruff lint violations (import order, contextlib.suppress, unused var)

- cas_client.py: move third-party import before logger assignment; use contextlib.suppress for
  aclose fallback - grpc/client.py: use contextlib.suppress for grpc-status parse fallback -
  test_cas_cookies.py: remove unused original_init variable - auth_manager.py: reformat per ruff
  format

* chore: remove accidentally committed playwright-mcp log + gitignore

---------

Co-authored-by: Claude Opus 4.6 <noreply@anthropic.com>

### Refactoring

- Extract response parsers from ws_client.py (Phase 2)
  ([`6ee2edd`](https://github.com/liskeee/xtb-api-unofficial-python/commit/6ee2eddc8afa7c9487b15ed6d045bc71a7595412))

- Create ws/parsers.py with 5 pure functions: parse_balance, parse_positions, parse_orders,
  parse_instruments, parse_quote - Replace inline dict-navigation in ws_client.py with parser calls
  - Add comprehensive test_parsers.py (17 tests) - ws_client.py shrinks by ~85 lines

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
