# xtb-api-python — Demo vs Real account mode

Status: draft for review
Author: brainstormed with Claude Opus 4.7
Date: 2026-04-21

---

## 1. Context & scope

XTB runs two parallel environments for every retail user: **real** (live
money) and **demo** (paper trading). They are identical at the protocol
level — same CAS login, same TGT/JWT flow, same gRPC-web + WebSocket
surfaces — and differ only in two values:

| | real | demo |
|---|---|---|
| WebSocket URL | `wss://api5reala.x-station.eu/v1/xstation` | `wss://api5demoa.x-station.eu/v1/xstation` |
| `account_server` (JWT `acs`) | `XS-real1` | `XS-demo1` |

This was verified by decoding a demo HAR capture (`demo.har`):
account `20864073` successfully traded `06N.PL` with JWT claim
`acs: "XS-demo1"` against the demo WebSocket endpoint. No other fields
of the wire protocol differ, and existing trade / balance / position code
paths work unchanged when both values are pointed at demo.

Today `XTBClient.__init__` hard-codes `ws_url` and `account_server` to
the real-account values as default kwargs. Switching to demo requires
every caller to remember **both** overrides, and passing only one
produces a subtle auth failure (WS URL for real, JWT claim for demo)
that is easy to misdiagnose.

**In scope**

- Let users pick real vs demo via env var (`XTB_ACCOUNT_TYPE`) or a new
  `account_type` kwarg, and have the library resolve `ws_url` +
  `account_server` atomically as a pair.
- Keep the per-field env vars (`XTB_WS_URL`, `XTB_ACCOUNT_SERVER`) as
  escape hatches for users on non-standard endpoints or future account
  servers.
- Update examples, `.env.example`, README, and CHANGELOG.

**Out of scope**

- Any behavioural difference between real and demo code paths. The
  library treats them identically — only the two resolved values change.
- Market-closed order handling / queued-order cancellation. That is a
  separate spec that needs its own HAR capture (deferred).
- Multi-account support, per-call account switching, or runtime
  environment switching on an existing client.
- Discovery / validation of account existence on the chosen environment
  — the library trusts what the user configured, as it does today.

---

## 2. Public API change

`XTBClient.__init__` gains one new kwarg and relaxes two existing ones
from required-with-default to optional:

```python
from typing import Literal

class XTBClient:
    def __init__(
        self,
        email: str,
        password: str,
        account_number: int,
        totp_secret: str = "",
        account_type: Literal["real", "demo"] | None = None,  # NEW
        ws_url: str | None = None,                              # was: str = "wss://api5reala..."
        account_server: str | None = None,                      # was: str = "XS-real1"
        session_file: Path | None = None,
        ...
    ) -> None:
```

At construction time the client calls the resolver (section 4) once and
stores the resolved `ws_url` and `account_server` on `self`. No other
code path changes — everything downstream already reads `self._ws_url`
and `self._account_server`.

**Precedence (highest to lowest):**

1. Explicit `ws_url=` / `account_server=` kwarg (per field).
2. Per-field env var: `XTB_WS_URL`, `XTB_ACCOUNT_SERVER`.
3. Preset from resolved `account_type` (`"real"` or `"demo"`).
4. `account_type` default: `"real"` (preserves today's behaviour for
   callers who pass nothing).

`account_type` itself resolves from: explicit kwarg → `XTB_ACCOUNT_TYPE`
env var → `"real"` default.

The fields mix independently: a caller can set
`account_type="demo"` and override just `ws_url=` to a staging endpoint;
the `account_server` still resolves to `"XS-demo1"` from the preset.

---

## 3. Error handling

Unknown `account_type` values (from kwarg OR env) raise `ValueError` at
construction time:

```
ValueError: Unknown account_type 'demp'. Expected 'real' or 'demo'.
```

Rationale: silent fallback to `"real"` on a typo would route a user's
demo credentials at the live endpoint, producing a confusing auth
failure far from the source of the mistake. A loud `ValueError` at
`__init__` stops the process with a pointer to the offending value.

Env parsing is case-insensitive and whitespace-trimmed (`"DEMO "`,
`"Demo"`, and `"demo"` all resolve to `"demo"`). Empty string and unset
are treated the same (fall through to default).

---

## 4. New module: `src/xtb_api/config.py`

A small module with the preset table and three pure resolver functions.
Separating this from `client.py` (currently 500+ LOC) keeps the logic
unit-testable without constructing a client.

```python
from __future__ import annotations

import os
from typing import Literal, TypedDict

AccountType = Literal["real", "demo"]


class _Preset(TypedDict):
    ws_url: str
    account_server: str


PRESETS: dict[AccountType, _Preset] = {
    "real": {
        "ws_url": "wss://api5reala.x-station.eu/v1/xstation",
        "account_server": "XS-real1",
    },
    "demo": {
        "ws_url": "wss://api5demoa.x-station.eu/v1/xstation",
        "account_server": "XS-demo1",
    },
}


def resolve_account_type(explicit: AccountType | None) -> AccountType:
    """Resolve account type from explicit kwarg → env → default 'real'.

    Validates both the kwarg and the env var against PRESETS so a typo
    in either path raises ValueError instead of silently falling through.
    """
    if explicit is not None:
        raw = str(explicit).strip().lower()
    else:
        raw = os.environ.get("XTB_ACCOUNT_TYPE", "").strip().lower()
    if not raw:
        return "real"
    if raw not in PRESETS:
        raise ValueError(
            f"Unknown account_type {raw!r}. Expected 'real' or 'demo'."
        )
    return raw  # type: ignore[return-value]


def resolve_ws_url(explicit: str | None, account_type: AccountType) -> str:
    """Resolve ws_url from explicit kwarg → XTB_WS_URL env → preset."""
    if explicit is not None:
        return explicit
    env = os.environ.get("XTB_WS_URL", "").strip()
    if env:
        return env
    return PRESETS[account_type]["ws_url"]


def resolve_account_server(explicit: str | None, account_type: AccountType) -> str:
    """Resolve account_server from explicit kwarg → XTB_ACCOUNT_SERVER env → preset."""
    if explicit is not None:
        return explicit
    env = os.environ.get("XTB_ACCOUNT_SERVER", "").strip()
    if env:
        return env
    return PRESETS[account_type]["account_server"]
```

`XTBClient.__init__` calls these three resolvers once and stores the
results. The explicit `account_type` kwarg is validated by
`resolve_account_type` on the same path as the env var, so kwarg typos
(`account_type="demp"`) get the same `ValueError`.

---

## 5. `.env.example` update

Current file has a commented `XTB_WS_URL` as the only environment knob.
Replace with a primary `XTB_ACCOUNT_TYPE` switch and keep the per-field
vars below it as commented escape hatches:

```dotenv
# XTB Credentials
XTB_USER_ID=
XTB_EMAIL=
XTB_PASSWORD=
#
XTB_TOTP_SECRET=
#
# Which XTB environment to connect to. One of: real, demo.
# Defaults to 'real' when unset.
XTB_ACCOUNT_TYPE=demo
#
# Escape hatches (optional). Set these only if your XTB account lives on
# a non-default endpoint or account server. If set, they override the
# preset chosen by XTB_ACCOUNT_TYPE.
#XTB_WS_URL=wss://api5reala.x-station.eu/v1/xstation
#XTB_ACCOUNT_SERVER=XS-real1
```

The shipped default in `.env.example` is `demo` because that's the safe
choice for someone copying the example file and running it for the first
time.

---

## 6. Examples update

Both examples currently pass `ws_url=os.environ.get("XTB_WS_URL", "wss://api5reala...")`
explicitly, which forces the caller to hard-code the real URL as a
fallback. With the library now reading env directly, the example can
drop that line entirely:

**`examples/basic_usage.py`** — remove the `ws_url=` kwarg at line 33,
update the docstring to mention `XTB_ACCOUNT_TYPE` instead of `XTB_WS_URL`:

```python
# Optional:
#   XTB_TOTP_SECRET    — Base32 TOTP secret for auto-2FA
#   XTB_ACCOUNT_TYPE   — 'real' (default) or 'demo'
```

**`examples/grpc_trade.py`** — same change at line 61. Update the safety
banner in the docstring to point at `XTB_ACCOUNT_TYPE=demo` as the
recommended way to avoid placing real orders, instead of the hard-coded
demo URL:

```
WARNING: this example places a real order. Set XTB_ACCOUNT_TYPE=demo
in your environment unless you deliberately want a live order.
```

No change to the `XTB_EXAMPLE_TRADE=1` gate — that stays.

---

## 7. README update

The current `WebSocket URLs` section (roughly lines 183–188 of README.md)
lists the two URLs as something the user must manually choose. Replace
with a `Demo vs Real` subsection under Configuration that matches the
new API:

```markdown
### Demo vs Real

Set `XTB_ACCOUNT_TYPE=demo` in your environment (or pass
`account_type="demo"` to `XTBClient`) to connect to XTB's paper-trading
environment instead of live. The library picks the correct WebSocket
endpoint and account server as a pair — you never need to set both
manually.

Defaults to `real` when unset, matching previous versions.
```

The section does not document `XTB_WS_URL` / `XTB_ACCOUNT_SERVER` as
public API — they remain an intentionally-undocumented escape hatch
visible only in `.env.example`.

---

## 8. Tests: `tests/test_config.py`

New file. All tests target the pure resolver functions in
`xtb_api.config` using `monkeypatch.setenv` / `monkeypatch.delenv` so
they don't leak between tests. One integration test round-trips through
`XTBClient.__init__`.

Cases:

1. `resolve_account_type(None)` with no env → `"real"`.
2. `resolve_account_type("demo")` → `"demo"` (kwarg path).
3. `resolve_account_type(None)` with `XTB_ACCOUNT_TYPE=demo` → `"demo"`.
4. Kwarg beats env: `resolve_account_type("real")` with env `demo` → `"real"`.
5. `XTB_ACCOUNT_TYPE=DEMO ` (caps + whitespace) → `"demo"`.
6. Empty `XTB_ACCOUNT_TYPE=""` → `"real"` (same as unset).
7. `XTB_ACCOUNT_TYPE=bogus` → `ValueError`, message names the offending value.
8. `account_type="bogus"` kwarg → same `ValueError`.
9. `resolve_ws_url(None, "demo")` with no env → demo preset URL.
10. `resolve_ws_url(None, "demo")` with `XTB_WS_URL=wss://staging/...` →
    env value (env beats preset).
11. `resolve_ws_url("wss://x/", "demo")` with env set → kwarg value
    (kwarg beats env).
12. Same three precedence cases for `resolve_account_server`.
13. **Integration**: `XTBClient(..., account_type="demo")` then assert
    `client._ws_url` / `client._account_server` match the demo preset.
    No network call.
14. **Integration**: with `XTB_ACCOUNT_TYPE=demo` in env and no kwargs,
    same result.

All tests are pure and fast; no HTTP, no WebSocket.

---

## 9. Backwards compatibility

- Callers who pass nothing (or just `ws_url=` and `account_server=`)
  continue to work unchanged. The real-URL default is preserved by
  falling through to the `"real"` account type when `account_type` is
  unset.
- The existing kwargs are kept — callers that explicitly pass
  `ws_url="wss://api5reala.x-station.eu/v1/xstation"` continue to work
  identically. The signature change is from
  `ws_url: str = "..."` to `ws_url: str | None = None`; any code that
  passes a string literal is unaffected.
- No module is renamed, deleted, or moved. `xtb_api.config` is additive.
- Environment variable `XTB_WS_URL` keeps working with identical
  semantics, so users who already have it set in their shell see no
  regression.

Minor version bump is sufficient (e.g. 0.7.2 → 0.8.0).

---

## 10. CHANGELOG bullet

Under a new `## [0.8.0]` section (or whatever the next version is):

```markdown
### Added

- `XTB_ACCOUNT_TYPE` environment variable and `account_type` kwarg on
  `XTBClient` to select demo or real XTB environment. Library resolves
  `ws_url` and `account_server` as a pair, so demo users no longer have
  to remember both overrides. `XTB_WS_URL` and new `XTB_ACCOUNT_SERVER`
  are kept as per-field escape hatches.
```

No `### Changed` / `### Fixed` entries — nothing existing breaks.

---

## Decision log

- **Separate `config.py` module vs inline in `client.py`** — chose
  separate module. `client.py` is already 500+ LOC; isolating the
  resolver as pure functions makes it unit-testable without touching
  any network code.
- **Loud `ValueError` on unknown `account_type` vs silent fallback** —
  chose loud error. Silent fallback would route demo credentials at
  the real endpoint on a typo (`XTB_ACCOUNT_TYPE=demp`) and produce a
  confusing auth failure far from the source.
- **Keep per-field env escape hatches vs drop them** — kept. Future
  XTB account-server migrations (e.g. `XS-real2`) would otherwise
  require a library release to support; the escape hatch lets users
  self-mitigate. Documented only in `.env.example`, not README.
