# Changelog

## 0.2.0 (Unreleased)

Major refactoring for public PyPI release. The library now provides a dead-simple, single-client API that handles all auth lifecycle transparently.

### Breaking Changes

- **`XTBClient` constructor completely rewritten** — now takes flat kwargs (`email`, `password`, `account_number`) instead of `XTBClientConfig` with mode selection
- **Browser transport mode removed** — `XTBBrowserClient` and `BrowserClientConfig` deleted. Browser auth (Playwright for WAF bypass) is preserved
- **`ChromeSession` removed** — CDP-based session management deleted
- **`ClientMode` removed** — no more mode selection; single unified client
- **`aiohttp` replaced by `httpx`** — all HTTP calls now use httpx
- **`playwright` promoted to core dependency** — required for auth (WAF bypass)
- **Top-level exports reduced** — internal types moved to submodules. Old imports emit `DeprecationWarning`
- **Helper methods removed from `AuthManager`** — `create_authenticated_client()`, `execute_trade()`, `search_instruments()` removed in favor of `XTBClient` methods

### Added

- Unified `XTBClient` with flat constructor and automatic auth lifecycle
- `buy()`/`sell()` accept flat `stop_loss`/`take_profit` kwargs
- `subscribe_ticks(symbol)` with automatic symbol key resolution
- Lazy gRPC initialization (only on first trade call)
- Session reuse — single `AuthManager` shared by WebSocket and gRPC
- Automatic JWT refresh from shared TGT in `GrpcClient`
- WebSocket reconnection with fresh service tickets via `AuthManager`
- Semantic exception hierarchy (`XTBError`, `AuthenticationError`, `TradeError`, etc.)
- `CASError` now subclasses `AuthenticationError` (backward compatible)
- Pure parser functions in `ws/parsers.py` (extracted from `ws_client.py`)
- PEP 561 `py.typed` marker
- CI workflow (pytest + ruff)
- Pre-commit hooks (ruff)
- 142 tests (up from 83)
- Tests for protobuf encoding, gRPC client, exception hierarchy, parsers

### Changed

- All dataclasses converted to Pydantic `BaseModel`
- `StrEnum` used instead of `str, Enum` pattern
- All `RuntimeError`/`TimeoutError` raises replaced with specific exceptions
- Inline WebSocket response parsing extracted to testable functions

### Removed

- `aiohttp` dependency
- `aioresponses` dev dependency
- `XTBBrowserClient`, `BrowserClientConfig`
- `ChromeSession`
- CDP fallback in `GrpcClient` (native httpx only)
- `GrpcClientConfig` from `client.py` (now internal to `GrpcClient`)

## 0.1.0

Initial working version with WebSocket, Browser, and gRPC transport modes.
