# Docs Refresh to v0.5.2 State — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update `README.md`, `CONTRIBUTING.md`, and `SECURITY.md` to match the v0.5.2 public surface (XTBAuth, InstrumentRegistry, fill-price polling, volume guard) and the inlined-publish CI pipeline.

**Architecture:** Three files edited in place. No code changes, no new files. One conventional commit at the end (`docs: ...`) which semantic-release will treat as silent (no version bump).

**Tech Stack:** Markdown only. No tests, no dependencies.

**Spec:** `docs/superpowers/specs/2026-04-15-docs-refresh-v0.5-design.md`

---

## File structure

Files modified:
- `README.md` — Features bullets, Quick Start, Trading note, API Reference (XTBAuth + InstrumentRegistry), Direct Access example.
- `CONTRIBUTING.md` — Release procedure framing, Trusted Publisher workflow names, Previewing trim.
- `SECURITY.md` — Supported versions table.

Files created: none.
Files deleted: none.

---

## Task 1: Update README.md

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update the Features bullets**

In `README.md`, locate the `## Features` section (around line 12). Replace the entire bullet list with:

```markdown
- **Single Client** — One `XTBClient` handles everything, no mode selection needed
- **Auto Auth** — Full CAS login flow with automatic TGT/JWT refresh
- **2FA Support** — Automatic TOTP handling when `totp_secret` is provided
- **Real-time Data** — Live quotes, positions, balance via WebSocket push events
- **Trading** — Buy/sell market orders with SL/TP via gRPC-web
- **Volume-Validated Orders** — `buy`/`sell` reject `volume < 1` before touching the wire
- **Persistent Instrument Cache** — `InstrumentRegistry` caches symbol → instrument-ID lookups to disk
- **Full Symbol Search** — Search and resolve all listed instruments with caching
- **Modern Python** — async/await, Pydantic models, strict typing, Python 3.12+
```

(Two new bullets added, "11,888+ Instruments" replaced with "Full Symbol Search".)

- [ ] **Step 2: Insert InstrumentRegistry example into Quick Start**

In `README.md`, locate the line `results = await client.search_instrument("Apple")` inside the `## Quick Start` block. Immediately after that line (before the blank line and the `# Trading (USE WITH CAUTION!)` comment), insert:

```python
    # Persistent instrument cache (avoids re-fetching the full symbol list)
    from xtb_api import InstrumentRegistry
    registry = InstrumentRegistry("~/.xtb_instruments.json")
    matched = await registry.populate(client, ["AAPL.US", "EURUSD"])
    instrument_id = registry.get("AAPL.US")  # int | None
```

Mind the four-space indentation — the example sits inside `async def main():`.

- [ ] **Step 3: Add fill-price note under Advanced Trade Options**

In `README.md`, locate the `### Advanced Trade Options` section. After the closing ``` of the second code block (the `TradeOptions` example), add a blank line then:

```markdown
> `TradeResult.price` is populated by polling open positions immediately after fill. If the position cannot be located within the poll window, `price` remains `None`.
```

- [ ] **Step 4: Add InstrumentRegistry subsection to API Reference**

In `README.md`, locate the `### Constructor Parameters` table. Immediately AFTER that table (before `### WebSocket URLs`), insert:

```markdown
### `InstrumentRegistry`

Persistent symbol → instrument-ID cache, stored as JSON.

| Method | Returns | Description |
|--------|---------|-------------|
| `InstrumentRegistry(path)` | — | Load (or create) the JSON cache at `path` |
| `get(symbol)` | `int \| None` | Cached instrument ID for `symbol`, or `None` |
| `set(symbol, id)` | `None` | Cache one mapping and persist immediately |
| `populate(client, symbols)` | `dict[str, int]` | Download the full symbol list via `client`, match requested `symbols` (case-insensitive, dot-less fallback), persist, return new matches |
| `ids` | `dict[str, int]` | Read-only copy of the full cache |

```

- [ ] **Step 5: Surface XTBAuth in Direct Access**

In `README.md`, locate the `### Advanced: Direct Access` section. Replace the existing code block with:

```python
# WebSocket client (always available)
ws = client.ws

# gRPC client (available after first trade)
grpc = client.grpc_client

# Auth manager (accessor, or import the public alias)
auth = client.auth
from xtb_api import XTBAuth  # public alias for the AuthManager class
tgt = await auth.get_tgt()
```

- [ ] **Step 6: Verify the README still parses cleanly**

Run:

```bash
python -c "import pathlib; t = pathlib.Path('README.md').read_text(); assert t.count('```') % 2 == 0, 'unbalanced code fences'; print('OK')"
```

Expected: `OK`

Then verify every `from xtb_api import …` line in the README references a real export:

```bash
python -c "from xtb_api import XTBClient, XTBAuth, InstrumentRegistry, TradeOptions; print('imports OK')"
```

Expected: `imports OK`

---

## Task 2: Update CONTRIBUTING.md

**Files:**
- Modify: `CONTRIBUTING.md`

- [ ] **Step 1: Replace the Release procedure intro paragraph**

In `CONTRIBUTING.md`, locate the `## Release procedure` section. The current first paragraph reads:

```markdown
Releases are **fully automated** by
[python-semantic-release](https://python-semantic-release.readthedocs.io/).
There is nothing to do by hand:
```

Leave that paragraph as-is. Then locate the `### Previewing a release locally` section. Replace its full body (from the `### Previewing` heading down to the line `Neither command touches the working tree.` inclusive) with:

```markdown
### Previewing a release locally

To sanity-check what semantic-release will do without touching the working tree:

```bash
pip install "python-semantic-release>=9"
semantic-release --noop version       # prints the next version
semantic-release --noop changelog     # prints the regenerated CHANGELOG
```
```

(The trimmed section drops the "Before enabling this on `master` the first time" framing — the pipeline is live as of v0.5.0.)

- [ ] **Step 2: Fix the Trusted Publisher workflow names**

In `CONTRIBUTING.md`, locate the `### One-time Trusted Publisher setup` section. Replace step 2 (the `On PyPI, visit ...` block) and step 3 (the TestPyPI block) with:

```markdown
2. On PyPI, visit https://pypi.org/manage/account/publishing/ and add **two
   pending publishers** for the same project (PyPI Trusted Publishing matches
   the OIDC token's source workflow filename exactly, so both publishing
   entry points must be registered):

   Publisher A — automated path:
   - PyPI project name: `xtb-api-python`
   - Owner: `liskeee`
   - Repository name: `xtb-api-python`
   - Workflow name: `semantic-release.yml`
   - Environment name: `pypi`

   Publisher B — manual recovery via `workflow_dispatch`:
   - PyPI project name: `xtb-api-python`
   - Owner: `liskeee`
   - Repository name: `xtb-api-python`
   - Workflow name: `release.yml`
   - Environment name: `pypi`

3. Do the same on TestPyPI at https://test.pypi.org/manage/account/publishing/
   for both workflows, but with environment name `testpypi`.
```

- [ ] **Step 3: Verify no broken markdown**

Run:

```bash
python -c "import pathlib; t = pathlib.Path('CONTRIBUTING.md').read_text(); assert t.count('```') % 2 == 0, 'unbalanced code fences'; print('OK')"
```

Expected: `OK`

Then confirm both workflow filenames appear:

```bash
grep -c "semantic-release.yml" CONTRIBUTING.md
grep -c "release.yml" CONTRIBUTING.md
```

Expected: `semantic-release.yml` count ≥ 1; `release.yml` count ≥ 2 (the new entry plus the existing reference).

---

## Task 3: Update SECURITY.md

**Files:**
- Modify: `SECURITY.md`

- [ ] **Step 1: Replace the supported-versions table**

In `SECURITY.md`, locate:

```markdown
| Version | Supported          |
| ------- | ------------------ |
| 0.3.x   | :white_check_mark: |
| < 0.3   | :x:                |
```

Replace with:

```markdown
| Version | Supported          |
| ------- | ------------------ |
| 0.5.x   | :white_check_mark: |
| < 0.5   | :x:                |
```

- [ ] **Step 2: Verify the table matches `pyproject.toml` version**

Run:

```bash
grep '^version' pyproject.toml
grep -E '^\| 0\.' SECURITY.md
```

Expected: `pyproject.toml` shows `version = "0.5.2"`; `SECURITY.md` shows `| 0.5.x` as supported. Major.minor must agree.

---

## Task 4: Final verification and commit

**Files:** none modified — verification only, then commit.

- [ ] **Step 1: Run the project's lint/format checks**

The repo uses `ruff` and `mypy`, but neither covers Markdown. Confirm no Python files were touched:

```bash
git status --porcelain | grep -v '\.md$' || echo "Markdown-only changes confirmed"
```

Expected: `Markdown-only changes confirmed`

- [ ] **Step 2: Re-run the import smoke check**

```bash
python -c "from xtb_api import XTBClient, XTBAuth, InstrumentRegistry, TradeOptions, TradeResult; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Stage and commit**

```bash
git add README.md CONTRIBUTING.md SECURITY.md
git commit -m "$(cat <<'EOF'
docs: refresh README, CONTRIBUTING, SECURITY to v0.5 state

- README: document XTBAuth alias, InstrumentRegistry, post-fill TradeResult.price,
  and the volume-validation guard added in v0.5.0; drop stale 11,888+ symbol count.
- CONTRIBUTING: trim "before enabling on master" framing now that PSR is live;
  list both semantic-release.yml and release.yml as required Trusted Publishers
  (PyPI matches the OIDC token's workflow filename exactly, and v0.5.2 inlined
  the publish jobs into semantic-release.yml).
- SECURITY: bump supported-versions table from 0.3.x to 0.5.x.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 4: Confirm the commit landed and the tree is clean**

Run:

```bash
git log -1 --oneline
git status
```

Expected: top commit subject is `docs: refresh README, CONTRIBUTING, SECURITY to v0.5 state`; working tree clean.

---

## Self-Review Checklist (for the implementer)

Before reporting the plan complete, confirm:

1. **README** mentions `XTBAuth`, `InstrumentRegistry`, fill-price polling, and the volume guard. The "11,888+" literal is gone.
2. **CONTRIBUTING** Trusted Publisher section names BOTH `semantic-release.yml` and `release.yml`.
3. **SECURITY** supported-versions table shows `0.5.x` and matches `pyproject.toml`.
4. Single conventional commit (`docs: …`). No version bump (PSR ignores `docs:`).
