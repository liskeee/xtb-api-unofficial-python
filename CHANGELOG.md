# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 0.3.0 — 2026-04-10

First public PyPI release.

### Added
- MIT `LICENSE` file, author email, and PyPI project URLs in package metadata
- Python 3.13 support and classifier
- `python -m xtb_api doctor` command to verify installation state (Python version,
  playwright package, Chromium binary, optional TOTP)
- `importlib.metadata`-based `__version__` that can no longer drift from `pyproject.toml`
- GitHub Actions release workflow with PyPI Trusted Publishing
- Separate `mypy` and `build` CI jobs; Python 3.12 + 3.13 test matrix
- `CONTRIBUTING.md` and `SECURITY.md`

### Fixed
- Prevent duplicate symbol downloads via `asyncio.Lock` in the WebSocket client
- Prevent tick-subscription leak in `get_quote` when parsing fails
- Prevent Playwright browser resource leak on auth error
- Use the next TOTP window code when close to the 30-second boundary
- Persist CAS cookies between restarts
- Clearer runtime error when the Chromium browser binary is missing
  (raises `CASError("BROWSER_CHROMIUM_MISSING", ...)` instead of a cryptic
  playwright internal error)
- All 25 mypy errors across `browser_auth`, `cas_client`, `auth_manager`,
  `ws_client`, `client`, and `utils` — mypy now runs in CI

### Changed
- Bumped `Development Status` classifier from `3 - Alpha` to `4 - Beta`

## 0.2.0 — 2026-04-10

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
