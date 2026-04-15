# CHANGELOG


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
