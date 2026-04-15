# Docs Refresh to v0.5.2 State — Design

**Date:** 2026-04-15
**Scope:** User-facing docs only (`README.md`, `CONTRIBUTING.md`, `SECURITY.md`)
**Out of scope:** `CHANGELOG.md` (owned by semantic-release), `docs/superpowers/*`

## Motivation

The repo shipped v0.5.0–v0.5.2 between 2026-04-10 and 2026-04-15, adding three
public-surface changes (`XTBAuth` alias, `InstrumentRegistry`, `TradeResult.price`
post-fill population, volume-validated `buy`/`sell`) and migrating the release
pipeline to `python-semantic-release` with publish jobs inlined into
`semantic-release.yml` after a PyPI Trusted Publishing constraint surfaced.

The user-facing docs were not updated alongside these shipments and now drift
from the actual surface in three concrete ways:

1. **README.md** does not mention `XTBAuth`, `InstrumentRegistry`, fill-price
   population, or the volume guard.
2. **CONTRIBUTING.md** still frames semantic-release as a future enablement and
   names only `release.yml` as the workflow PyPI must trust — incorrect after
   the v0.5.2 inline-publish fix.
3. **SECURITY.md** lists `0.3.x` as the supported line; current is `0.5.2`.

A maintainer setting up a fork from these docs today would fail to publish to
PyPI, and a user reading the README would not discover `InstrumentRegistry` or
the new trade-result behavior.

## Architecture

Three files edited in place. No new files, no deletions, no code changes.
Each file's edits are independently reviewable and independently revertable.

## Changes

### README.md

**Features section** — append two bullets after the existing list:

- **Volume-Validated Orders** — `buy`/`sell` reject `volume < 1` before touching the wire
- **Persistent Instrument Cache** — `InstrumentRegistry` caches symbol→ID lookups to disk

**Features section** — drop the literal "11,888+ Instruments" bullet's
hardcoded count; reword to "Full Symbol Search — search and resolve all listed
instruments with caching" so it does not go stale on the next XTB catalog
change.

**Quick Start** — after the existing `search_instrument` line and before the
"Trading" block, insert a small `InstrumentRegistry` example:

```python
# Persistent instrument cache (avoids re-fetching the full symbol list)
from xtb_api import InstrumentRegistry
registry = InstrumentRegistry(client, cache_path="~/.xtb_instruments.json")
new_symbols = await registry.populate(["AAPL.US", "EURUSD"])
instrument = registry.get("AAPL.US")
```

**Trading section** — append a one-line note: "`TradeResult.price` is populated
by polling open positions immediately after fill; if the position cannot be
located within the poll window, `price` remains `None`."

**API Reference → `XTBClient` table** — no changes (methods are unchanged).

**API Reference** — add a new short subsection after the `XTBClient` table:

```
### `InstrumentRegistry`

Persistent symbol → instrument-id cache. Construct with an `XTBClient` and an
optional `cache_path`. Call `populate(symbols)` to fetch and cache any symbols
not already known; returns the list of newly-added symbols. Call `get(symbol)`
for synchronous lookup.
```

**API Reference** — add `XTBAuth` to the public exports list (one line under
the existing direct-access block).

**Advanced: Direct Access** — replace the `auth = client.auth` example with the
public `XTBAuth` alias to show the supported import path:

```python
from xtb_api import XTBAuth  # public alias for AuthManager
```

(Keep the `client.auth` accessor example too — both are valid.)

### CONTRIBUTING.md

**"Release procedure" section** — remove "Before enabling this on `master` the
first time —" framing from the local-preview paragraph. The pipeline is live;
the section should describe steady state.

**"One-time Trusted Publisher setup" section** — replace the single
`Workflow name: release.yml` line with two entries listing **both**
`semantic-release.yml` AND `release.yml`. Add one explanatory sentence:

> PyPI Trusted Publishing matches the OIDC token's source workflow filename
> exactly, so both publishing entry points (`semantic-release.yml` for the
> automated path, `release.yml` for manual `workflow_dispatch` recovery) must
> be registered as trusted publishers.

**"Previewing a release locally"** — keep the section, trim from ~10 lines to
~5. The `semantic-release --noop` commands stay; drop the redundant
"Neither command touches the working tree" line (implied by `--noop`).

### SECURITY.md

**Supported versions table** — replace:

```
| 0.3.x   | :white_check_mark: |
| < 0.3   | :x:                |
```

with:

```
| 0.5.x   | :white_check_mark: |
| < 0.5   | :x:                |
```

No other changes (reporting email, scope, and disclosure timeline are current).

## Testing

No automated tests. Verification is read-through:

1. Render `README.md` on GitHub (or preview locally) and confirm no broken
   links and that all `from xtb_api import …` lines resolve against the
   current [src/xtb_api/__init__.py](../../../src/xtb_api/__init__.py)
   `__all__`.
2. Diff `CONTRIBUTING.md` against the actual `.github/workflows/` filenames to
   confirm both `release.yml` and `semantic-release.yml` are referenced in the
   Trusted Publisher section.
3. Confirm `SECURITY.md` table entry matches `pyproject.toml` `version`
   (currently `0.5.2`, so `0.5.x`).

## Out-of-scope items flagged for follow-up

- **CHANGELOG.md repo-URL drift.** Commit links in v0.5.0–v0.5.2 entries point
  at `liskeee/xtb-api-unofficial-python` rather than `liskeee/xtb-api-python`.
  This is a `[tool.semantic_release.remote]` configuration issue, not a docs
  edit. Track separately if confirmed.
- **`docs/superpowers/plans/2026-04-15-v0.5-broker-adapter-support.md`** is
  fully shipped per `git log` (`feat(client)`, `feat(instruments)` commits all
  landed in #7 and were released as v0.5.0). Marking the plan checkboxes as
  complete is a separate sweep.

## Build sequence

1. Edit `README.md` (largest change, most surface to verify).
2. Edit `CONTRIBUTING.md`.
3. Edit `SECURITY.md`.
4. Render diff, sanity-check imports against `__init__.py`.
5. Single conventional commit: `docs: refresh README, CONTRIBUTING, SECURITY to v0.5 state`.
