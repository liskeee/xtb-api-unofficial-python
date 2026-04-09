# XTB API Python Client — Refactoring Design Spec

**Date:** 2026-04-09
**Status:** Draft
**Scope:** Full library refactoring for public PyPI release

---

## 1. Goals

Transform the existing working XTB trading API client (~4,446 lines) into a production-grade, publicly publishable Python package that:

- Provides a dead-simple, single-client API — no mode selection, no transport knowledge required
- Handles all auth lifecycle transparently (TGT, ST, JWT refresh, 2FA, WAF bypass)
- Is reliable enough for automated trading bots handling real money
- Follows Python packaging best practices (strict typing, semantic exceptions, clean exports)

## 2. Constraints & Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Python version | >= 3.12 | Modern syntax, trading users keep envs current |
| HTTP client | httpx (replaces aiohttp) | Single HTTP lib for REST auth + gRPC native |
| WebSocket client | websockets (keep) | Battle-tested, proven in production with real money |
| Browser auth | playwright (core dep) | WAF always blocks REST — Playwright is the primary auth path |
| REST auth | Keep as fast-path attempt | Falls back to Playwright if WAF blocks, zero cost if WAF lifts |
| Browser transport mode | Remove entirely | XTBBrowserClient/ChromeSession deleted |
| Data validation | pydantic (keep) | Already used, provides BaseModel, validation, JSON schema |
| Deprecation strategy | `__getattr__` + DeprecationWarning | Public package needs graceful migration path |

## 3. Architecture

### 3.1 User-Facing API

```python
from xtb_api import XTBClient

client = XTBClient(
    email="user@example.com",
    password="secret",
    account_number=51984891,
    totp_secret="BASE32SECRET",      # optional, auto-handles 2FA
    session_file="~/.xtb_session",   # optional, persists auth across restarts
)
await client.connect()

# Read operations (via WebSocket)
balance = await client.get_balance()
positions = await client.get_positions()
orders = await client.get_orders()
quote = await client.get_quote("EURUSD")
results = await client.search_instrument("bitcoin")

# Trading (via gRPC, lazy-initialized)
# SL/TP as flat kwargs for simple use
result = await client.buy("EURUSD", volume=1, stop_loss=1.0850, take_profit=1.0950)
# Or via TradeOptions for advanced options (trailing stop, amount-based sizing)
result = await client.sell("CIG.PL", volume=100, options=TradeOptions(trailing_stop=50))

# Real-time events
client.on("tick", lambda tick: print(tick))
client.on("position", lambda pos: print(pos))
await client.subscribe_ticks("EURUSD")

# Graceful shutdown
await client.disconnect()
```

Users never interact with AuthManager, CASClient, GrpcClient, or WebSocket internals directly.

**API design notes:**
- `buy()`/`sell()` accept `stop_loss`, `take_profit` as flat kwargs for the common case. For advanced options (trailing stop, amount-based sizing), pass a `TradeOptions` object.
- `subscribe_ticks()` accepts a symbol name like `"EURUSD"` — the client resolves it to the internal symbol key (`"9_EURUSD_6"`) automatically via the symbol cache.
- All methods that accept a symbol name perform resolution internally. Users never deal with symbol keys.

### 3.2 Component Diagram

```
XTBClient (public facade)
|
+-- _auth: AuthManager
|   +-- _cas: CASClient (httpx REST + playwright browser)
|   +-- TGT cache: memory + disk (session_file)
|   +-- get_tgt() -> always returns valid token
|   +-- get_service_ticket() -> derived from TGT
|
+-- _ws: XTBWebSocketClient (websockets lib)
|   +-- Owns: connection, ping loop, listen loop, event handlers
|   +-- Owns: symbol cache (11,888+ instruments)
|   +-- Uses: _auth reference for reconnection (fresh ST)
|   +-- Operations: get_balance, get_positions, get_orders,
|                   search_instrument, get_quote, subscribe_*
|
+-- _grpc: GrpcClient (httpx native, lazy-init on first trade)
|   +-- Uses: _auth.get_tgt() for JWT refresh
|   +-- JWT cache: 5-min TTL, auto-refresh from shared TGT
|   +-- Single long-lived httpx.AsyncClient instance
|   +-- Operations: buy, sell (NewMarketOrder)
|
+-- Event proxy: client.on("tick", ...) -> _ws.on("tick", ...)
```

### 3.3 Session Reuse Model

One `AuthManager`, one `XTBWebSocketClient`, one `GrpcClient` — all long-lived, all sharing the same auth session.

```
AuthManager (singleton per XTBClient)
|
|  TGT (8h, cached memory + disk, proactive 5-min margin refresh)
|
+--- get_service_ticket() ---> XTBWebSocketClient
|    (derived from TGT,         - connect() uses ST once
|     one-use)                  - reconnect() calls get_service_ticket() again
|                               - stays connected for hours
|
+--- get_tgt() --------------> GrpcClient
     (same cached TGT)          - get_jwt(tgt) caches JWT for 5min
                                 - JWT derived from shared TGT
                                 - reuses httpx.AsyncClient instance
                                 - lives for duration of XTBClient
```

No per-operation client creation. The current `AuthManager.execute_trade()`, `search_instruments()`, and `create_authenticated_client()` helpers that spin up throwaway clients are removed.

### 3.4 Token Lifecycle Guarantees

**TGT (8-hour lifetime):**
- `AuthManager.get_tgt()` always returns a valid token
- Proactive 5-min margin refresh (existing behavior, kept)
- On expiry: full re-auth chain (REST attempt -> Playwright -> TOTP) runs automatically
- Cached in memory + optional session file on disk

**Service Ticket (one-use, derived from TGT):**
- `AuthManager.get_service_ticket()` obtains fresh ST from TGT
- On `CAS_TGT_EXPIRED`: invalidates TGT, re-runs auth chain, retries (existing behavior, kept)

**JWT (5-minute cache):**
- `GrpcClient` holds reference to `AuthManager`
- `get_jwt()` calls `auth.get_tgt()` internally — if TGT expired, auth chain runs transparently
- JWT cache checked first, refreshed when stale

**WS Reconnection:**
- On connection drop: `_schedule_reconnect()` with exponential backoff
- Calls `auth.get_service_ticket()` for fresh ST (not the stale original)
- Full re-auth: `register_client_info()` + `login_with_service_ticket()`
- Re-subscribes to active subscriptions

**Token flow examples:**

After 6 hours (`buy()` call, TGT still valid):
```
client.buy("EURUSD", 1)
  -> _grpc.get_jwt()
    -> JWT cache expired (5min TTL)
    -> _auth.get_tgt()
      -> memory cache still valid (8h - 5min margin)
      -> returns cached TGT (no re-auth)
    -> gRPC CreateAccessToken(tgt) -> new JWT
  -> _grpc.execute_order(instrument_id, volume, SIDE_BUY)
```

After 8 hours (`buy()` call, TGT expired):
```
client.buy("EURUSD", 1)
  -> _grpc.get_jwt()
    -> JWT cache expired
    -> _auth.get_tgt()
      -> memory cache expired
      -> session file expired
      -> REST CAS login -> WAF blocks -> Playwright login -> TGT
      -> cache new TGT (memory + disk)
    -> gRPC CreateAccessToken(tgt) -> new JWT
  -> _grpc.execute_order(...)
```

## 4. Exception Hierarchy

```python
XTBError (base)
+-- XTBConnectionError        # WS connect failure, CDP unreachable
|   +-- AuthenticationError   # Invalid creds, expired TGT, 2FA failure
|   |   +-- CASError          # CAS-specific, keeps .code attribute (backward compat)
|   +-- ReconnectionError     # Exhausted reconnect attempts
+-- TradeError                # Order rejected, insufficient margin
|   +-- InstrumentNotFoundError  # Symbol can't be resolved
+-- RateLimitError            # Too many OTP attempts, throttled
+-- XTBTimeoutError           # Request timeout
+-- ProtocolError             # Malformed response, unexpected format
```

`CASError` stays backward-compatible: existing `except CASError` code keeps working because it now subclasses `AuthenticationError` -> `XTBConnectionError` -> `XTBError` -> `Exception`.

## 5. Public API Surface

### 5.1 Top-level exports (~20 symbols)

```python
# The client
XTBClient

# Data models
Position, PendingOrder, AccountBalance, TradeResult, TradeOptions,
Quote, InstrumentSearchResult

# Enums
Xs6Side, TradeCommand, SocketStatus, XTBEnvironment

# Exceptions
XTBError, XTBConnectionError, AuthenticationError, CASError,
ReconnectionError, TradeError, InstrumentNotFoundError,
RateLimitError, XTBTimeoutError, ProtocolError

# Version
__version__
```

### 5.2 Advanced use (via submodules, not top-level)

```python
from xtb_api.ws import XTBWebSocketClient
from xtb_api.grpc import GrpcClient
from xtb_api.auth import AuthManager, CASClient
```

### 5.3 Internal protocol types (via xtb_api.types.*)

`CoreAPIPayload`, `WSPushEventRow`, `WSPushEvent`, `WSPushMessage`, `CoreAPICommand`, `WSRequest`, `WSResponse`, `ClientInfo`, `XLoginResult`, `IPrice`, `IVolume`, etc.

Removed from top-level `__all__`. Importing from `xtb_api` directly emits `DeprecationWarning`.

### 5.4 I-prefixed type aliases

Python-style aliases added: `Price = IPrice`, `Volume = IVolume`, `Size = ISize`, etc. I-prefixed names deprecated for one minor version.

## 6. Files Plan

### 6.1 New files

| File | Purpose |
|------|---------|
| `src/xtb_api/exceptions.py` | Exception hierarchy |
| `src/xtb_api/ws/parsers.py` | Pure parser functions from ws_client.py |
| `src/xtb_api/transport.py` | `TransportBackend` Protocol (internal/testing) |
| `.github/workflows/ci.yml` | pytest + ruff + mypy |
| `.pre-commit-config.yaml` | Pre-commit hooks |
| `src/xtb_api/py.typed` | PEP 561 marker |
| `tests/test_exceptions.py` | Exception hierarchy tests |
| `tests/test_parsers.py` | Parser unit tests |
| `tests/test_proto.py` | Protobuf encode/decode tests |
| `tests/test_grpc_client.py` | gRPC client with mocked httpx |
| `tests/test_browser_auth.py` | Browser auth with mocked Playwright |
| `CHANGELOG.md` | Release notes |

### 6.2 Files to delete

| File | Reason |
|------|--------|
| `src/xtb_api/browser/__init__.py` | Browser transport removed |
| `src/xtb_api/browser/browser_client.py` | Browser transport removed |
| `src/xtb_api/auth/chrome_session.py` | CDP session manager removed |

### 6.3 Heavy modifications

| File | Changes |
|------|---------|
| `src/xtb_api/client.py` | Rewrite: flat kwargs constructor, owns AuthManager/WS/gRPC, event proxy, lazy gRPC |
| `src/xtb_api/__init__.py` | Shrink to ~20 exports, `__getattr__` deprecation |
| `src/xtb_api/ws/ws_client.py` | Accept AuthManager for reconnect, extract parsers, custom exceptions |
| `src/xtb_api/grpc/client.py` | Accept AuthManager for JWT refresh, remove CDP fallback, long-lived httpx client, custom exceptions |
| `src/xtb_api/auth/auth_manager.py` | Remove execute_trade/search_instruments/create_authenticated_client helpers |
| `src/xtb_api/auth/cas_client.py` | aiohttp -> httpx, dataclass -> BaseModel |
| `src/xtb_api/types/websocket.py` | CASError inherits AuthenticationError |
| `src/xtb_api/types/trading.py` | Python-style aliases, deprecate I-prefixed |
| `pyproject.toml` | Remove aiohttp, playwright to core, add ruff/mypy |

### 6.4 Light modifications

| File | Changes |
|------|---------|
| `src/xtb_api/grpc/types.py` | dataclass -> BaseModel, add GrpcClientConfig |
| `src/xtb_api/utils.py` | ParsedSymbolKey dataclass -> BaseModel |
| `tests/conftest.py` | Add mocked transport fixtures |
| `tests/test_auth.py` | aiohttp mocks -> httpx mocks |
| `tests/test_auth_manager.py` | Update for removed helpers |
| `tests/test_client.py` | Rewrite for new constructor API |
| `tests/test_ws_client.py` | Update for AuthManager integration |
| `README.md` | New unified API examples |

## 7. Phased Execution Plan

### Phase 0: Tooling & CI
- Add ruff, mypy config to pyproject.toml
- Create CI workflow, pre-commit config, py.typed
- Fix existing lint issues
- **Verify:** CI green, all 83 tests pass

### Phase 1: Exception hierarchy
- Create `exceptions.py`, make `CASError` subclass `AuthenticationError`
- Replace all `RuntimeError`/`TimeoutError` across codebase
- Export from `__init__.py`
- **Verify:** all 83 tests pass + new exception tests

### Phase 2: Response parser extraction
- Create `ws/parsers.py` with 5 pure functions
- Replace inline parsing in `ws_client.py`
- **Verify:** all tests pass, ws_client.py shrinks ~80-100 lines

### Phase 3: aiohttp -> httpx migration
- Migrate `CASClient` REST calls from aiohttp to httpx
- Update test mocks
- Remove aiohttp from pyproject.toml
- **Verify:** all tests pass, auth flow works

### Phase 4: Remove browser transport mode
- Delete browser_client.py, chrome_session.py
- Remove from __init__.py with deprecation warnings
- **Verify:** all tests pass

### Phase 5: Unified XTBClient + session reuse
- Rewrite client.py: flat constructor, owns AuthManager/WS/gRPC
- GrpcClient accepts AuthManager, auto-refreshes JWT
- WS client uses AuthManager for reconnect with fresh ST
- Lazy gRPC init, symbol resolution in buy/sell
- Long-lived httpx.AsyncClient in GrpcClient
- Remove CDP fallback from GrpcClient (native httpx only)
- Remove helper methods from AuthManager
- Event proxy
- **Verify:** all tests pass, full flow works

### Phase 6: Config consistency + public API surface
- Convert remaining dataclasses to BaseModel
- Shrink __init__.py to ~20 exports
- Add Python-style type aliases
- Playwright to core dependency
- **Verify:** all tests pass, deprecated imports warn

### Phase 7: Test coverage expansion
- test_proto.py (100% of proto.py)
- test_grpc_client.py (mocked httpx)
- test_browser_auth.py (mocked Playwright)
- Target: 83 -> ~150+ tests
- **Verify:** full suite green

### Phase 8: Documentation & polish
- Google-style docstrings throughout
- Rewrite README.md
- Create CHANGELOG.md
- **Verify:** clean lint, full test suite

### Phase dependencies

```
Phase 0 --> Phase 1 --+--> Phase 2
                      +--> Phase 3 --> Phase 4 --> Phase 5
                      +--> (Phase 6 after Phase 5)
Phases 1-6 --> Phase 7
Phases 0-7 --> Phase 8
```

Phases 2 and 3 are independent and can run in parallel.

## 8. Dependency Changes

### Before
```
dependencies = [
    "websockets>=13.0",
    "aiohttp>=3.9",
    "pydantic>=2.5",
    "httpx>=0.27",
]
[project.optional-dependencies]
browser = ["playwright>=1.40"]
totp = ["pyotp>=2.9.0"]
```

### After
```
dependencies = [
    "websockets>=13.0",
    "pydantic>=2.5",
    "httpx>=0.27",
    "playwright>=1.40",
]
[project.optional-dependencies]
totp = ["pyotp>=2.9.0"]
```

Removed: `aiohttp` (replaced by httpx)
Promoted: `playwright` from optional to core (WAF requires it)
Kept optional: `pyotp` (only needed if 2FA is enabled)

## 9. Breaking Changes

| Change | Migration |
|--------|-----------|
| `XTBClient` constructor takes kwargs, not `XTBClientConfig` | `XTBClient(email=..., password=..., account_number=...)` |
| No more `ClientMode` / mode selection | Single unified client handles everything |
| `BrowserClientConfig`, `XTBBrowserClient`, `ChromeSession` removed | Use `XTBClient` directly |
| ~40 symbols removed from top-level `__init__.py` | Import from submodules, DeprecationWarning for one version |
| `RuntimeError` no longer raised (replaced with `XTBError` subclasses) | `except XTBError` catches everything |
| `GrpcClientConfig.account_number` no longer has default | Must be provided explicitly |
| `AuthManager.execute_trade()`, `.search_instruments()`, `.create_authenticated_client()` removed | Use `XTBClient.buy()`, `.search_instrument()`, `.connect()` |
| `IPrice`, `IVolume`, etc. deprecated | Use `Price`, `Volume`, etc. |
