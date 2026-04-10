# xtb-api-python Publication Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring `xtb-api-python` from its current state to a polished, 1.0-ready public release on PyPI, installable via `pip install xtb-api-python` in a `requirements.txt`.

**Architecture:** Packaging + CI/CD changes. Add `LICENSE`, align metadata and version, harden CI with mypy and Python 3.12/3.13 matrix, automate PyPI releases via GitHub Actions Trusted Publishing on tag push, and improve post-install UX with a runtime error for missing Chromium plus a `python -m xtb_api doctor` CLI.

**Tech Stack:** hatchling (build backend), GitHub Actions, PyPI Trusted Publishing (OIDC), mypy, ruff, pytest, pre-commit, Python 3.12+.

**Spec:** [`docs/superpowers/specs/2026-04-10-publish-polish-design.md`](../specs/2026-04-10-publish-polish-design.md)

---

## Pre-flight notes (already verified)

- **PyPI name `xtb-api-python` is available** — `curl https://pypi.org/pypi/xtb-api-python/json` returns 404 as of 2026-04-10. If you run this plan later and the name has been taken, **stop** and escalate to the user.
- **Current mypy baseline** — `mypy src/` reports 25 errors across 6 files. Task 10 fixes them all before enabling the CI typecheck job.
- **Browser launch site** — `src/xtb_api/auth/browser_auth.py:80` (`self._browser = await self._playwright.chromium.launch(...)`). Task 13 wraps this.
- **Playwright error type** — `playwright.async_api.Error` (exported from `playwright._impl._errors.Error`). Missing-binary errors surface with message "Executable doesn't exist".

---

## File Structure

**New files:**

- `LICENSE` — MIT License text with copyright line
- `CONTRIBUTING.md` — dev setup, test commands, release procedure
- `SECURITY.md` — security disclosure policy and supported versions
- `.github/workflows/release.yml` — tag-triggered PyPI/TestPyPI publish workflow
- `src/xtb_api/__main__.py` — CLI dispatcher with `doctor` subcommand
- `tests/test_version.py` — assert `__version__` matches installed metadata
- `tests/test_doctor.py` — exercise the `doctor` CLI subcommand
- `tests/test_browser_auth_chromium_missing.py` — assert playwright Error → CASError translation

**Modified files:**

- `pyproject.toml` — author email, URLs, classifiers, wheel include/exclude, `[project.scripts]`
- `src/xtb_api/__init__.py` — `__version__` via `importlib.metadata`
- `src/xtb_api/auth/browser_auth.py` — catch `playwright.async_api.Error` around `chromium.launch`, re-raise as `CASError("BROWSER_CHROMIUM_MISSING", ...)`; fix mypy errors
- `src/xtb_api/auth/cas_client.py` — class-level `_browser_auth` annotation, fix narrow/None mypy errors
- `src/xtb_api/auth/auth_manager.py` — `pyotp` stub ignore; fix `Returning Any`
- `src/xtb_api/ws/ws_client.py` — fix `Literal['buy','sell']` + `Returning Any` + None-async-iter
- `src/xtb_api/client.py` — fix `Literal['buy','sell']` trade side
- `src/xtb_api/utils.py` — cast fix for `price_to_decimal`
- `CHANGELOG.md` — rename heading to `0.3.0 — 2026-04-10`, add 0.3.0 entry
- `README.md` — badges, post-install callout, requirements line
- `.github/workflows/ci.yml` — lint/typecheck/test-matrix/build jobs, concurrency, caches
- `.pre-commit-config.yaml` — add mypy, general hooks

---

## Task 1: Create LICENSE file

**Files:**
- Create: `LICENSE`

- [ ] **Step 1: Create LICENSE with full MIT text**

Write `LICENSE`:

```
MIT License

Copyright (c) 2025-2026 Łukasz Lis

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 2: Verify the file is present**

Run: `ls -la LICENSE && wc -l LICENSE`
Expected: file exists, ~21 lines.

- [ ] **Step 3: Commit**

```bash
git add LICENSE
git commit -m "docs: add MIT LICENSE file"
```

---

## Task 2: Update pyproject.toml metadata

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Update `[project]` section**

Replace the `authors`, add `[project.urls]`, expand `classifiers`, bump `Development Status`. Final state of the `[project]` section:

```toml
[project]
name = "xtb-api-python"
version = "0.3.0"
description = "Python port of unofficial XTB xStation5 API client"
readme = "README.md"
license = "MIT"
requires-python = ">=3.12"
authors = [
    { name = "Łukasz Lis", email = "ll.lukasz.lis@gmail.com" },
]
keywords = ["xtb", "xstation5", "trading", "websocket", "api"]
classifiers = [
    "Development Status :: 4 - Beta",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Operating System :: OS Independent",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Topic :: Office/Business :: Financial :: Investment",
    "Topic :: Software Development :: Libraries :: Python Modules",
    "Typing :: Typed",
    "Framework :: AsyncIO",
]

[project.urls]
Homepage = "https://github.com/liskeee/xtb-api-python"
Repository = "https://github.com/liskeee/xtb-api-python"
Issues = "https://github.com/liskeee/xtb-api-python/issues"
Changelog = "https://github.com/liskeee/xtb-api-python/blob/master/CHANGELOG.md"
```

- [ ] **Step 2: Add `[project.scripts]` entry point (for the doctor CLI added in Task 14)**

Insert immediately after `[project.urls]`:

```toml
[project.scripts]
xtb-api = "xtb_api.__main__:main"
```

- [ ] **Step 3: Tighten wheel build targets**

Replace `[tool.hatch.build.targets.wheel]` section with both include and exclude rules, and add an sdist section:

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/xtb_api"]

[tool.hatch.build.targets.sdist]
include = [
    "src/",
    "tests/",
    "examples/",
    "README.md",
    "LICENSE",
    "CHANGELOG.md",
    "pyproject.toml",
]
exclude = [
    "reference-ts/",
    ".venv/",
    "docs/",
    ".github/",
    ".pytest_cache/",
    ".ruff_cache/",
    "uv.lock",
]
```

- [ ] **Step 4: Add mypy `ignore_missing_imports` override for pyotp**

At the bottom of `pyproject.toml`, add:

```toml
[[tool.mypy.overrides]]
module = ["pyotp", "pyotp.*"]
ignore_missing_imports = true
```

- [ ] **Step 5: Validate pyproject.toml parses**

Run:
```bash
python -c "import tomllib, pathlib; tomllib.loads(pathlib.Path('pyproject.toml').read_text()); print('OK')"
```
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml
git commit -m "chore(packaging): add author email, project URLs, 3.13 classifier, pyotp mypy override"
```

---

## Task 3: Wire `__version__` through `importlib.metadata`

**Files:**
- Modify: `src/xtb_api/__init__.py`
- Create: `tests/test_version.py`

- [ ] **Step 1: Write the failing test first**

Create `tests/test_version.py`:

```python
"""Tests for the package version string."""

from __future__ import annotations

import re
from importlib.metadata import version as _pkg_version

import xtb_api


def test_version_is_string() -> None:
    assert isinstance(xtb_api.__version__, str)
    assert xtb_api.__version__  # non-empty


def test_version_matches_installed_metadata() -> None:
    """__version__ must match whatever pip sees for xtb-api-python."""
    installed = _pkg_version("xtb-api-python")
    assert xtb_api.__version__ == installed


def test_version_is_pep440_compatible() -> None:
    """Loose PEP 440 check — digits, dots, optional pre/dev suffix."""
    assert re.match(r"^\d+\.\d+(\.\d+)?([ab]\d+|rc\d+|\.dev\d+|\+[\w.]+)?$", xtb_api.__version__)
```

- [ ] **Step 2: Run the test to confirm it fails**

Run: `pytest tests/test_version.py -v`
Expected: `test_version_matches_installed_metadata` FAILS because `__init__.py` hard-codes `"0.2.0"` while `importlib.metadata.version("xtb-api-python")` reports `"0.3.0"`.

- [ ] **Step 3: Replace the hard-coded version in `src/xtb_api/__init__.py`**

Change the line `__version__ = "0.2.0"` to:

```python
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

try:
    __version__ = _pkg_version("xtb-api-python")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0+unknown"
```

Place these imports at the top of `src/xtb_api/__init__.py` (before the existing `from xtb_api.client import XTBClient` block), and remove the old `__version__ = "0.2.0"` line.

- [ ] **Step 4: Run the tests again to confirm they pass**

Run: `pytest tests/test_version.py -v`
Expected: all 3 tests PASS, reporting `__version__ == "0.3.0"`.

- [ ] **Step 5: Confirm no other tests broke**

Run: `pytest tests/ -q`
Expected: all tests pass (baseline 142 + 3 new).

- [ ] **Step 6: Commit**

```bash
git add src/xtb_api/__init__.py tests/test_version.py
git commit -m "feat(version): derive __version__ from importlib.metadata"
```

---

## Task 4: Update CHANGELOG.md for 0.3.0 release

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Rewrite the top of CHANGELOG.md**

Replace the line `## 0.2.0 (Unreleased)` with `## 0.3.0 — 2026-04-10` and insert a new summary block at the very top (before the `## 0.3.0` entry — no, above it with the new 0.3.0 content). Final structure of the top portion:

```markdown
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

(Keep the rest of the existing changelog below — the original "Breaking Changes",
"Added", "Changed", "Removed" blocks stay but live under their original heading.)
```

Then replace the old heading `## 0.2.0 (Unreleased)` **below** the new block with `## 0.2.0 — 2026-03-30` (pick any date that matches when 0.2.0 work actually merged — from git log, the `chore: bump version to 0.3.0` commit was `d171467`, so use the date of that commit's parent). Run `git log --format=%ad --date=short -1 d171467^` to get the date and substitute.

- [ ] **Step 2: Confirm CHANGELOG.md still renders cleanly as markdown**

Run: `python -c "import pathlib; print(pathlib.Path('CHANGELOG.md').read_text()[:500])"`
Expected: clean output, no syntax errors.

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): add 0.3.0 entry with Keep-a-Changelog format"
```

---

## Task 5: Update README.md — badges, post-install callout, requirements

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add badges block at the very top**

Insert **before** the existing `# xtb-api-python` heading:

```markdown
[![PyPI version](https://img.shields.io/pypi/v/xtb-api-python.svg)](https://pypi.org/project/xtb-api-python/)
[![Python versions](https://img.shields.io/pypi/pyversions/xtb-api-python.svg)](https://pypi.org/project/xtb-api-python/)
[![CI](https://github.com/liskeee/xtb-api-python/actions/workflows/ci.yml/badge.svg)](https://github.com/liskeee/xtb-api-python/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

```

(Badges on separate lines, then a blank line before the `#` heading.)

- [ ] **Step 2: Replace the "Install" section with an expanded version including a prominent post-install callout**

Find the existing `## Install` section and replace it wholesale with:

```markdown
## Requirements

- Python **3.12 or 3.13**
- Chromium browser (installed via playwright — see post-install step below)
- An XTB trading account

## Install

```bash
pip install xtb-api-python

# With automatic 2FA handling:
pip install "xtb-api-python[totp]"
```

### Post-install setup (REQUIRED)

This library uses [Playwright](https://playwright.dev/python/) to authenticate with
XTB's servers (the REST login path is blocked by a WAF). **After** `pip install`,
you must download the Chromium binary:

```bash
playwright install chromium
```

Without this step, the first call to `client.connect()` will fail with a
`CASError("BROWSER_CHROMIUM_MISSING", ...)` and a pointer back here.

To verify your install is complete, run:

```bash
python -m xtb_api doctor
```

### Development install

```bash
pip install -e ".[dev,totp]"
playwright install chromium
pre-commit install
```
```

- [ ] **Step 3: Visual check**

Run: `head -60 README.md`
Expected: badges visible, `## Requirements` then `## Install` then `### Post-install setup (REQUIRED)` callout present.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs(readme): add badges, requirements, and post-install Chromium callout"
```

---

## Task 6: Add CONTRIBUTING.md

**Files:**
- Create: `CONTRIBUTING.md`

- [ ] **Step 1: Write CONTRIBUTING.md**

```markdown
# Contributing to xtb-api-python

Thanks for your interest in improving this library. This document covers how
to set up a development environment, run the test suite, and cut a release.

## Development setup

```bash
# Clone
git clone https://github.com/liskeee/xtb-api-python.git
cd xtb-api-python

# Create a virtualenv (Python 3.12+ required)
python -m venv .venv
source .venv/bin/activate

# Install in editable mode with dev + optional extras
pip install -e ".[dev,totp]"

# Download Chromium for playwright auth
playwright install chromium

# Install pre-commit hooks
pre-commit install
```

## Running checks

```bash
# Tests
pytest

# Lint
ruff check src/ tests/
ruff format --check src/ tests/

# Type check
mypy src/
```

All of the above run in CI on every push and pull request.

## Pull requests

- One logical change per PR. Keep diffs reviewable.
- Add or update tests alongside code changes.
- Update `CHANGELOG.md` under an `## Unreleased` heading (create one if it doesn't
  exist) for any user-visible change.
- Pre-commit must pass locally before pushing.

## Release procedure

The release workflow at `.github/workflows/release.yml` publishes to PyPI on
tag push using Trusted Publishing. To cut a new release:

1. Make sure `master` is green and your working tree is clean.
2. Update `CHANGELOG.md`: rename the `## Unreleased` heading to the new version
   and today's date (`## 0.4.0 — YYYY-MM-DD`).
3. Bump `version` in `pyproject.toml`.
4. Commit: `git commit -am "chore(release): 0.4.0"`
5. Tag and push:
   ```bash
   git tag v0.4.0
   git push origin master v0.4.0
   ```
6. The release workflow will build, publish to PyPI, and create a GitHub Release.

### Testing a release against TestPyPI

Any tag that is **not** a plain `v<major>.<minor>.<patch>` (e.g., `v0.4.0rc1`,
`v0.4.0.dev1`) publishes to TestPyPI instead of PyPI. Use this for dry-runs:

```bash
git tag v0.4.0rc1
git push origin v0.4.0rc1
```

Then in a fresh venv:

```bash
pip install --index-url https://test.pypi.org/simple/ \
            --extra-index-url https://pypi.org/simple/ \
            "xtb-api-python==0.4.0rc1"
python -m xtb_api doctor
```

### One-time Trusted Publisher setup

Before the first successful release, you (the maintainer) need to register the
repo as a Trusted Publisher on both PyPI and TestPyPI:

1. Create GitHub Environments named `pypi` and `testpypi` on the repo
   (Settings → Environments).
2. On PyPI, visit https://pypi.org/manage/account/publishing/ and add a
   **pending publisher**:
   - PyPI project name: `xtb-api-python`
   - Owner: `liskeee`
   - Repository name: `xtb-api-python`
   - Workflow name: `release.yml`
   - Environment name: `pypi`
3. Do the same on TestPyPI at https://test.pypi.org/manage/account/publishing/
   but with environment name `testpypi`.

After the first successful publish, the "pending" publisher becomes a normal
trusted publisher tied to the project.
```

- [ ] **Step 2: Verify the file is well-formed**

Run: `wc -l CONTRIBUTING.md`
Expected: ~100 lines.

- [ ] **Step 3: Commit**

```bash
git add CONTRIBUTING.md
git commit -m "docs: add CONTRIBUTING.md with dev setup and release procedure"
```

---

## Task 7: Add SECURITY.md

**Files:**
- Create: `SECURITY.md`

- [ ] **Step 1: Write SECURITY.md**

```markdown
# Security Policy

## Reporting a vulnerability

If you discover a security issue in xtb-api-python, **please do not open a
public GitHub issue.** Instead, email the maintainer at
**ll.lukasz.lis@gmail.com** with the details.

Please include:

- A description of the issue and its impact
- Steps to reproduce, if possible
- The version of xtb-api-python affected

You should receive an initial response within 7 days. Once the issue is
confirmed and a fix is prepared, the maintainer will coordinate disclosure
with you.

## Supported versions

Only the latest minor release line receives security fixes:

| Version | Supported          |
| ------- | ------------------ |
| 0.3.x   | :white_check_mark: |
| < 0.3   | :x:                |

## Scope

This project is an **unofficial** client for XTB's xStation5 platform. Bugs
in XTB's own infrastructure are out of scope — report those directly to XTB.

Credential handling, TGT/JWT persistence, and TOTP secret storage are in scope.
```

- [ ] **Step 2: Commit**

```bash
git add SECURITY.md
git commit -m "docs: add SECURITY.md disclosure policy"
```

---

## Task 8: Fix `utils.py` mypy error (`Returning Any`)

**Files:**
- Modify: `src/xtb_api/utils.py`

- [ ] **Step 1: Confirm the current error**

Run: `mypy src/xtb_api/utils.py`
Expected: `utils.py:22: error: Returning Any from function declared to return "float"`.

- [ ] **Step 2: Cast the multiplication result**

In `src/xtb_api/utils.py:20-22`, replace:

```python
def price_to_decimal(price: IPrice) -> float:
    """Convert IPrice to decimal: price_to_decimal(IPrice(value=262, scale=2)) → 2.62"""
    return price.value * (10 ** (-price.scale))
```

with:

```python
def price_to_decimal(price: IPrice) -> float:
    """Convert IPrice to decimal: price_to_decimal(IPrice(value=262, scale=2)) → 2.62"""
    return float(price.value) * (10 ** (-price.scale))
```

- [ ] **Step 3: Verify mypy passes for this file**

Run: `mypy src/xtb_api/utils.py`
Expected: `Success: no issues found in 1 source file`.

- [ ] **Step 4: Run pytest to confirm no behavior change**

Run: `pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/xtb_api/utils.py
git commit -m "fix(utils): cast price_to_decimal to satisfy mypy"
```

---

## Task 9: Fix `auth_manager.py` mypy errors

**Files:**
- Modify: `src/xtb_api/auth/auth_manager.py`

- [ ] **Step 1: Look at the two errors**

The errors are:
```
auth_manager.py:224: error: Cannot find implementation or library stub for module named "pyotp"
auth_manager.py:236: error: Returning Any from function declared to return "str"
```

The `pyotp` error is already handled by the `[[tool.mypy.overrides]]` you added in Task 2. Verify:

Run: `mypy src/xtb_api/auth/auth_manager.py 2>&1 | grep -E "pyotp|Returning"`
Expected: only the `Returning Any` error should remain. If `pyotp` is still flagged, the pyproject override wasn't picked up — double-check Task 2 Step 4.

- [ ] **Step 2: Read the offending function**

Run: `sed -n '230,240p' src/xtb_api/auth/auth_manager.py`

The function returns `totp.now()` which is untyped `Any`. Cast it.

- [ ] **Step 3: Fix the return**

Replace the `return` line at `auth_manager.py:236` (the one that returns `totp.now()`, possibly after a `.strip()`) with an explicit `str(...)` cast:

```python
return str(totp.now())
```

- [ ] **Step 4: Verify mypy is clean for this file**

Run: `mypy src/xtb_api/auth/auth_manager.py`
Expected: `Success: no issues found`.

- [ ] **Step 5: Run related tests**

Run: `pytest tests/test_auth_manager.py tests/test_auth.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/xtb_api/auth/auth_manager.py
git commit -m "fix(auth): cast totp.now() return value for mypy"
```

---

## Task 10: Fix `cas_client.py` mypy errors

**Files:**
- Modify: `src/xtb_api/auth/cas_client.py`

- [ ] **Step 1: Review the three errors**

```
cas_client.py:479: error: Incompatible types in assignment (expression has type "None", variable has type "BrowserCASAuth")
cas_client.py:502: error: Incompatible types in assignment (expression has type "str | None", target has type "str")
cas_client.py:529: error: Item "None" of "timedelta | None" has no attribute "total_seconds"
```

- [ ] **Step 2: Add class-level `_browser_auth` annotation**

In the `CASClient.__init__` (or wherever the class is defined), add a class-level type annotation so mypy knows `_browser_auth` is `BrowserCASAuth | None`. First check how the class is structured:

Run: `grep -n "class CASClient\|self._browser_auth\|_browser_auth:" src/xtb_api/auth/cas_client.py`

Then, **inside the class body but before `__init__`**, add:

```python
    _browser_auth: "BrowserCASAuth | None" = None
```

(The string-quoted forward reference avoids needing to hoist the `BrowserCASAuth` import to module level, since it's currently imported lazily inside `login_with_browser()`.)

- [ ] **Step 3: Fix the str-None narrow at line 502**

The offending line is `existing[cookie.name] = cookie.value` inside `_save_cookies()`. The `cookie.value` is typed `str | None` by httpx. Narrow it:

```python
for cookie in client.cookies.jar:
    if cookie.value is not None:
        existing[cookie.name] = cookie.value
```

- [ ] **Step 4: Fix the `total_seconds()` on Optional timedelta at line 529**

The offending line is:
```python
offset_seconds = now.utcoffset().total_seconds() if now.utcoffset() else 0
```

mypy doesn't narrow across two separate calls. Rewrite as:
```python
offset = now.utcoffset()
offset_seconds = offset.total_seconds() if offset is not None else 0
```

- [ ] **Step 5: Verify mypy is clean for this file**

Run: `mypy src/xtb_api/auth/cas_client.py`
Expected: `Success: no issues found`.

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_cas_cookies.py tests/test_auth.py -v`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/xtb_api/auth/cas_client.py
git commit -m "fix(cas): narrow Optional types and annotate _browser_auth"
```

---

## Task 11: Fix `browser_auth.py` mypy errors (attribute types)

**Files:**
- Modify: `src/xtb_api/auth/browser_auth.py`

- [ ] **Step 1: Review the 12 errors**

All stem from `self._browser`, `self._page`, `self._playwright` being assigned `None` in `__init__` with no explicit type hint — mypy infers their type as `None`.

- [ ] **Step 2: Add explicit class-level annotations**

At the top of `src/xtb_api/auth/browser_auth.py`, add a lazy import block (guarded under `TYPE_CHECKING` to avoid the runtime import):

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Browser, Page, Playwright
```

Then, in the `BrowserCASAuth` class (currently at line 44), replace the `__init__` body's implicit attribute types with explicit class-level annotations:

```python
class BrowserCASAuth:
    """Browser-based CAS authentication using Playwright.
    ...
    """

    _browser: "Browser | None"
    _page: "Page | None"
    _playwright: "Playwright | None"

    def __init__(self, *, headless: bool = True) -> None:
        self._headless = headless
        self._tgt: str | None = None
        self._tgt_event = asyncio.Event()
        self._two_factor_detected = asyncio.Event()
        self._browser = None
        self._page = None
        self._playwright = None
        self._login_ticket: str | None = None
        self._two_factor_info: dict | None = None
```

- [ ] **Step 3: Fix the `_on_response` missing annotation at line 244**

Run: `sed -n '242,250p' src/xtb_api/auth/browser_auth.py`

Add a type hint to the `response` parameter and return type:

```python
async def _on_response(self, response: "Response") -> None:
```

Add `Response` to the `TYPE_CHECKING` import block:

```python
if TYPE_CHECKING:
    from playwright.async_api import Browser, Page, Playwright, Response
```

- [ ] **Step 4: Add `assert` narrowing where self._page/self._browser are used after launch**

mypy will still complain that methods like `self._page.goto(...)` dereference an `Optional`. The simplest fix inside the `login()` method, after `self._browser = await self._playwright.chromium.launch(...)` and `self._page = await context.new_page()`, add:

```python
            assert self._browser is not None
            assert self._page is not None
            assert self._playwright is not None
```

These are `assert`, not runtime protection — they exist to narrow types for mypy. Place them immediately after `self._page = await context.new_page()` (around line 96).

- [ ] **Step 5: Verify mypy is clean for this file**

Run: `mypy src/xtb_api/auth/browser_auth.py`
Expected: `Success: no issues found`.

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_browser_auth.py -v`
Expected: all pass (the mocked tests still work because the attribute mocks still satisfy the asserts).

- [ ] **Step 7: Commit**

```bash
git add src/xtb_api/auth/browser_auth.py
git commit -m "fix(browser-auth): type-annotate playwright attrs via TYPE_CHECKING"
```

---

## Task 12: Fix `ws_client.py` and `client.py` mypy errors (Literal trade side)

**Files:**
- Modify: `src/xtb_api/ws/ws_client.py`
- Modify: `src/xtb_api/client.py`

- [ ] **Step 1: Review the errors**

```
ws_client.py:671: Argument "side" to "TradeResult" has incompatible type "str"; expected "Literal['buy', 'sell']"
ws_client.py:718: (same)
ws_client.py:726: (same)
ws_client.py:739: Returning Any from function declared to return "dict[str, Any] | None"
ws_client.py:752: Returning Any from function declared to return "list[dict[str, Any]]"
ws_client.py:828: Item "None" of "ClientConnection | None" has no attribute "__aiter__"
client.py:376: Argument "side" to "TradeResult" has incompatible type "str"; expected "Literal['buy', 'sell']"
```

- [ ] **Step 2: Inspect the `TradeResult` model to understand the `side` field**

Run: `grep -n "side" src/xtb_api/types/trading.py`

If `side` is typed as `Literal["buy", "sell"]`, the call sites need to pass a literal or cast. The cleanest fix without touching the public model is a `cast`.

- [ ] **Step 3: Add a typing.cast at each trade-side call site**

In `src/xtb_api/ws/ws_client.py`, at lines 671, 718, 726 — replace the `side=side` (where `side` is a plain `str`) argument with `side=cast("Literal['buy', 'sell']", side)` and add `from typing import cast` at the top of the file (if not already imported). Note: because `cast`'s first argument is a plain string literal, `Literal` itself does **not** need to be imported — mypy parses the type from the string.

Before making the change, inspect exactly how `side` is passed at each line:
Run: `sed -n '668,674p;715,728p' src/xtb_api/ws/ws_client.py`

For each site, the pattern will be something like:
```python
return TradeResult(
    ...
    side=side,
    ...
)
```
Change to:
```python
return TradeResult(
    ...
    side=cast("Literal['buy', 'sell']", side),
    ...
)
```

Repeat the same cast in `src/xtb_api/client.py:376`.

- [ ] **Step 4: Fix the `Returning Any` errors at ws_client.py:739 and :752**

Inspect:
Run: `sed -n '735,755p' src/xtb_api/ws/ws_client.py`

Both return values are typed `Any` because of dict/list indexing. Add explicit `cast` calls using the same `from typing import cast`:

For line 739 (returning `dict[str, Any] | None`):
```python
return cast("dict[str, Any] | None", value)
```

For line 752 (returning `list[dict[str, Any]]`):
```python
return cast("list[dict[str, Any]]", value)
```

(Replace `value` with whatever local name the code uses.)

- [ ] **Step 5: Fix the None async-iter at ws_client.py:828**

Inspect:
Run: `sed -n '820,835p' src/xtb_api/ws/ws_client.py`

The code iterates `self._ws` which is `ClientConnection | None`. Narrow it with an assert before the loop:

```python
assert self._ws is not None
async for message in self._ws:
    ...
```

- [ ] **Step 6: Verify mypy passes for both files**

Run: `mypy src/xtb_api/ws/ws_client.py src/xtb_api/client.py`
Expected: `Success: no issues found in 2 source files`.

- [ ] **Step 7: Run tests**

Run: `pytest tests/test_ws_client.py tests/test_client.py -v`
Expected: all pass.

- [ ] **Step 8: Full mypy sweep**

Run: `mypy src/`
Expected: `Success: no issues found in 20 source files`.

- [ ] **Step 9: Commit**

```bash
git add src/xtb_api/ws/ws_client.py src/xtb_api/client.py
git commit -m "fix(ws,client): cast trade side to Literal and narrow Optional types"
```

---

## Task 13: Browser auth — translate missing-Chromium error

**Files:**
- Modify: `src/xtb_api/auth/browser_auth.py`
- Create: `tests/test_browser_auth_chromium_missing.py`

- [ ] **Step 1: Write the failing test first**

Create `tests/test_browser_auth_chromium_missing.py`:

```python
"""Ensure a clear error is raised when Chromium binary is missing."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from xtb_api.auth.browser_auth import BrowserCASAuth
from xtb_api.exceptions import CASError


class TestChromiumMissing:
    @pytest.mark.asyncio
    async def test_missing_chromium_raises_cas_error_with_install_hint(self) -> None:
        """If playwright raises 'Executable doesn't exist', translate to CASError."""
        from playwright.async_api import Error as PlaywrightError

        auth = BrowserCASAuth()

        # Simulate playwright raising its typical missing-binary error
        chromium_mock = MagicMock()
        chromium_mock.launch = AsyncMock(
            side_effect=PlaywrightError(
                "BrowserType.launch: Executable doesn't exist at "
                "/home/user/.cache/ms-playwright/chromium-1234/chrome-linux/chrome"
            )
        )

        pw_mock = MagicMock()
        pw_mock.chromium = chromium_mock

        pw_factory_call = MagicMock()
        pw_factory_call.start = AsyncMock(return_value=pw_mock)
        pw_factory = MagicMock(return_value=pw_factory_call)

        with (
            patch("playwright.async_api.async_playwright", pw_factory),
            patch.object(auth, "close", new_callable=AsyncMock),
        ):
            with pytest.raises(CASError) as exc_info:
                await auth.login("user@test.com", "pw")

        assert exc_info.value.code == "BROWSER_CHROMIUM_MISSING"
        assert "playwright install chromium" in str(exc_info.value)
```

- [ ] **Step 2: Run the test to confirm it fails**

Run: `pytest tests/test_browser_auth_chromium_missing.py -v`
Expected: FAIL — the generic `playwright.async_api.Error` currently propagates un-wrapped.

- [ ] **Step 3: Add the error translation in `browser_auth.py`**

In `src/xtb_api/auth/browser_auth.py`, the `login()` method currently has:

```python
        self._playwright = await async_playwright().start()
        try:
            self._browser = await self._playwright.chromium.launch(
                headless=self._headless,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
```

**Note about imports**: `CASError` is already usable in `browser_auth.py` via the existing `from xtb_api.types.websocket import (..., CASError, ...)` at the top of the file — `types/websocket.py` re-exports it from `xtb_api.exceptions` (`from xtb_api.exceptions import CASError as CASError`). No new import is needed.

**Note about the existing outer try**: at line 79 of `browser_auth.py` there is already an `outer` `try:` block that wraps the entire auth flow for cleanup purposes (`finally: if needs_cleanup: await self.close()`). Do NOT replace or restructure that outer try. The change is to add a **nested** `try/except` strictly around the `chromium.launch(...)` call inside that existing outer try.

Replace lines 79-83 of `browser_auth.py`:

```python
        try:
            self._browser = await self._playwright.chromium.launch(
                headless=self._headless,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
```

with:

```python
        try:
            from playwright.async_api import Error as _PlaywrightError

            try:
                self._browser = await self._playwright.chromium.launch(
                    headless=self._headless,
                    args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
                )
            except _PlaywrightError as e:
                msg = str(e)
                if "Executable doesn't exist" in msg:
                    raise CASError(
                        "BROWSER_CHROMIUM_MISSING",
                        "Chromium browser not found. The xtb-api-python library requires a "
                        "Chromium install for XTB authentication.\n\n"
                        "Run:\n    playwright install chromium\n\n"
                        "See https://github.com/liskeee/xtb-api-python#post-install-setup "
                        "for details.",
                    ) from e
                raise
```

Leave the rest of the outer try-body (starting with `context = await self._browser.new_context(...)` at line 84) unchanged.

- [ ] **Step 4: Run the new test**

Run: `pytest tests/test_browser_auth_chromium_missing.py -v`
Expected: PASS.

- [ ] **Step 5: Run all browser-auth tests**

Run: `pytest tests/test_browser_auth.py tests/test_browser_auth_chromium_missing.py -v`
Expected: all pass.

- [ ] **Step 6: Run mypy on the changed file**

Run: `mypy src/xtb_api/auth/browser_auth.py`
Expected: `Success: no issues found`.

- [ ] **Step 7: Commit**

```bash
git add src/xtb_api/auth/browser_auth.py tests/test_browser_auth_chromium_missing.py
git commit -m "feat(auth): translate missing-Chromium error to CASError with install hint"
```

---

## Task 14: Add `python -m xtb_api doctor` CLI

**Files:**
- Create: `src/xtb_api/__main__.py`
- Create: `tests/test_doctor.py`

- [ ] **Step 1: Write the failing test first**

Create `tests/test_doctor.py`:

```python
"""Tests for the `xtb_api doctor` CLI command."""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

from xtb_api.__main__ import main, run_doctor


class TestDoctorCommand:
    def test_doctor_runs_and_returns_zero_on_happy_path(self, capsys: pytest.CaptureFixture[str]) -> None:
        """With playwright + chromium present, doctor exits 0."""
        with patch("xtb_api.__main__._check_chromium_binary", return_value=(True, "/fake/chrome")):
            exit_code = run_doctor()
        out = capsys.readouterr().out
        assert exit_code == 0
        assert "xtb-api-python" in out
        assert "[OK]" in out

    def test_doctor_returns_nonzero_when_chromium_missing(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """With Chromium binary missing, doctor exits 1 and prints install hint."""
        with patch(
            "xtb_api.__main__._check_chromium_binary",
            return_value=(False, "not found"),
        ):
            exit_code = run_doctor()
        out = capsys.readouterr().out
        assert exit_code == 1
        assert "[FAIL]" in out
        assert "playwright install chromium" in out

    def test_main_with_no_args_prints_help_and_exits_nonzero(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch.object(sys, "argv", ["xtb-api"]):
            exit_code = main()
        assert exit_code != 0
        assert "doctor" in (capsys.readouterr().out + capsys.readouterr().err)

    def test_main_dispatches_doctor_subcommand(self) -> None:
        with (
            patch.object(sys, "argv", ["xtb-api", "doctor"]),
            patch("xtb_api.__main__.run_doctor", return_value=0) as mock_run,
        ):
            exit_code = main()
        assert exit_code == 0
        mock_run.assert_called_once()
```

- [ ] **Step 2: Run the test to confirm it fails with an ImportError**

Run: `pytest tests/test_doctor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'xtb_api.__main__'`.

- [ ] **Step 3: Create `src/xtb_api/__main__.py`**

```python
"""CLI entry point for xtb-api-python.

Usage:
    python -m xtb_api doctor   # Verify installation state
    xtb-api doctor             # Same, if the entry point script is on PATH
"""

from __future__ import annotations

import argparse
import importlib.util
import platform
import sys
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version


def _ok(label: str, detail: str = "") -> str:
    return f"  [OK]   {label}" + (f" — {detail}" if detail else "")


def _fail(label: str, detail: str = "") -> str:
    return f"  [FAIL] {label}" + (f" — {detail}" if detail else "")


def _info(label: str, detail: str = "") -> str:
    return f"  [--]   {label}" + (f" — {detail}" if detail else "")


def _check_python_version() -> tuple[bool, str]:
    major, minor = sys.version_info[:2]
    version_str = f"{major}.{minor}.{sys.version_info[2]}"
    ok = (major, minor) >= (3, 12)
    return ok, version_str


def _check_package_version() -> tuple[bool, str]:
    try:
        return True, _pkg_version("xtb-api-python")
    except PackageNotFoundError:
        return False, "not installed (are you running from a non-installed checkout?)"


def _check_playwright_package() -> tuple[bool, str]:
    spec = importlib.util.find_spec("playwright")
    if spec is None:
        return False, "playwright Python package not installed"
    try:
        ver = _pkg_version("playwright")
    except PackageNotFoundError:
        ver = "unknown"
    return True, f"playwright {ver}"


def _check_chromium_binary() -> tuple[bool, str]:
    """Attempt to locate the Chromium executable without launching it."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False, "playwright not importable"

    try:
        with sync_playwright() as p:
            exe = p.chromium.executable_path
            # executable_path is a property that returns a string path; does not
            # guarantee the file exists. Probe it.
            from pathlib import Path

            if exe and Path(exe).exists():
                return True, exe
            return False, f"expected binary at {exe!r} not found"
    except Exception as e:  # noqa: BLE001
        return False, f"playwright check failed: {e}"


def _check_pyotp_optional() -> tuple[bool, str]:
    spec = importlib.util.find_spec("pyotp")
    if spec is None:
        return False, "pyotp not installed (install 'xtb-api-python[totp]' for auto-2FA)"
    try:
        ver = _pkg_version("pyotp")
    except PackageNotFoundError:
        ver = "unknown"
    return True, f"pyotp {ver}"


def run_doctor() -> int:
    """Run environment checks and print a status report. Returns 0 on success."""
    print(f"xtb-api-python doctor — {platform.platform()}")
    print()

    all_ok = True

    # Required checks
    ok, detail = _check_python_version()
    print(_ok("Python >= 3.12", detail) if ok else _fail("Python >= 3.12", detail))
    all_ok &= ok

    ok, detail = _check_package_version()
    print(_ok("xtb-api-python", detail) if ok else _fail("xtb-api-python", detail))
    all_ok &= ok

    ok, detail = _check_playwright_package()
    print(_ok("playwright package", detail) if ok else _fail("playwright package", detail))
    all_ok &= ok

    ok, detail = _check_chromium_binary()
    if ok:
        print(_ok("Chromium binary", detail))
    else:
        print(_fail("Chromium binary", detail))
        print()
        print("  To install Chromium, run:")
        print("      playwright install chromium")
        print()
        all_ok = False

    # Optional checks
    ok, detail = _check_pyotp_optional()
    print(_ok("pyotp (optional 2FA)", detail) if ok else _info("pyotp (optional 2FA)", detail))

    print()
    if all_ok:
        print("All required checks passed.")
        return 0
    print("Some required checks failed. See above for fix instructions.")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="xtb-api",
        description="xtb-api-python CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor", help="Verify the library's installation state")

    args = parser.parse_args()

    if args.command == "doctor":
        return run_doctor()
    return 2


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the test**

Run: `pytest tests/test_doctor.py -v`
Expected: all 4 tests PASS.

- [ ] **Step 5: Smoke-run the CLI directly**

Run: `python -m xtb_api doctor`
Expected: prints a checklist. It may FAIL the Chromium-binary check if the venv doesn't have Chromium installed — that's expected for a dev machine. The exit code reflects that.

- [ ] **Step 6: Run mypy on the new file**

Run: `mypy src/xtb_api/__main__.py`
Expected: `Success: no issues found`.

- [ ] **Step 7: Run all tests**

Run: `pytest tests/ -q`
Expected: all pass (baseline + 4 new doctor tests + 1 new chromium-missing test + 3 version tests = original 142 + 8).

- [ ] **Step 8: Commit**

```bash
git add src/xtb_api/__main__.py tests/test_doctor.py
git commit -m "feat(cli): add 'xtb-api doctor' command for install verification"
```

---

## Task 15: Rewrite CI workflow

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Replace the entire file**

Overwrite `.github/workflows/ci.yml` with:

```yaml
name: CI

on:
  push:
    branches: [master]
  pull_request:
    branches: [master]

concurrency:
  group: ci-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - name: Install ruff
        run: pip install ruff
      - name: Lint
        run: |
          ruff check src/ tests/
          ruff format --check src/ tests/

  typecheck:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - name: Install with dev and totp extras
        run: pip install -e ".[dev,totp]" mypy
      - name: Run mypy
        run: mypy src/

  test:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
          cache: pip
      - name: Install
        run: pip install -e ".[dev,totp]"
      - name: Run tests
        run: pytest --tb=short -q

  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - name: Install build tooling
        run: pip install build twine
      - name: Build sdist and wheel
        run: python -m build
      - name: Validate distribution metadata
        run: twine check dist/*
      - name: Upload dist artifacts
        uses: actions/upload-artifact@v4
        with:
          name: dist
          path: dist/
          retention-days: 7
```

- [ ] **Step 2: Validate the YAML parses**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml')); print('OK')"`
Expected: `OK`. If `yaml` module is not installed, skip this step.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add typecheck + build jobs, Python 3.12/3.13 matrix, concurrency"
```

---

## Task 16: Update pre-commit config

**Files:**
- Modify: `.pre-commit-config.yaml`

- [ ] **Step 1: Replace the file**

Overwrite `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.8.6
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format

  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v5.0.0
    hooks:
      - id: check-yaml
      - id: end-of-file-fixer
      - id: trailing-whitespace
      - id: check-toml
      - id: check-merge-conflict

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.13.0
    hooks:
      - id: mypy
        files: ^src/
        additional_dependencies:
          - pydantic>=2.5
          - httpx>=0.27
          - websockets>=13.0
```

- [ ] **Step 2: Verify the config is valid**

Run: `pre-commit validate-config`
Expected: no errors (if pre-commit is installed locally).

- [ ] **Step 3: Commit**

```bash
git add .pre-commit-config.yaml
git commit -m "chore(pre-commit): add mypy and generic hygiene hooks"
```

---

## Task 17: Add release workflow with Trusted Publishing

**Files:**
- Create: `.github/workflows/release.yml`

- [ ] **Step 1: Create the workflow**

```yaml
name: Release

on:
  push:
    tags:
      - "v*"

permissions:
  contents: read

jobs:
  build:
    runs-on: ubuntu-latest
    outputs:
      is_stable: ${{ steps.classify.outputs.is_stable }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - name: Install build tooling
        run: pip install build twine
      - name: Build sdist and wheel
        run: python -m build
      - name: Validate metadata
        run: twine check dist/*
      - name: Classify tag
        id: classify
        run: |
          TAG="${GITHUB_REF_NAME}"
          if [[ "$TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
            echo "is_stable=true" >> "$GITHUB_OUTPUT"
          else
            echo "is_stable=false" >> "$GITHUB_OUTPUT"
          fi
      - uses: actions/upload-artifact@v4
        with:
          name: dist
          path: dist/

  publish-testpypi:
    needs: build
    if: ${{ needs.build.outputs.is_stable == 'false' }}
    runs-on: ubuntu-latest
    environment:
      name: testpypi
      url: https://test.pypi.org/p/xtb-api-python
    permissions:
      id-token: write
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist/
      - name: Publish to TestPyPI
        uses: pypa/gh-action-pypi-publish@release/v1
        with:
          repository-url: https://test.pypi.org/legacy/

  publish-pypi:
    needs: build
    if: ${{ needs.build.outputs.is_stable == 'true' }}
    runs-on: ubuntu-latest
    environment:
      name: pypi
      url: https://pypi.org/p/xtb-api-python
    permissions:
      id-token: write
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist/
      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@release/v1

  github-release:
    needs: [build, publish-pypi]
    if: ${{ needs.build.outputs.is_stable == 'true' }}
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4
      - uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist/
      - name: Extract changelog section for this version
        id: changelog
        run: |
          # Strip leading 'v' from the tag: v0.3.0 -> 0.3.0
          VERSION="${GITHUB_REF_NAME#v}"
          # Extract the section from CHANGELOG.md between "## <VERSION>" and the
          # next "## " heading. Preserves blank lines and sub-headings.
          awk -v ver="$VERSION" '
            $0 ~ "^## " ver {found=1; next}
            found && /^## / {exit}
            found {print}
          ' CHANGELOG.md > release_notes.md
          # Fallback: if extraction produced nothing, use a minimal message
          if [ ! -s release_notes.md ]; then
            echo "Release $GITHUB_REF_NAME" > release_notes.md
          fi
          echo "Generated release notes:"
          cat release_notes.md
      - name: Create GitHub Release
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          gh release create "$GITHUB_REF_NAME" \
            --title "$GITHUB_REF_NAME" \
            --notes-file release_notes.md \
            dist/*
```

- [ ] **Step 2: Validate YAML**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml')); print('OK')"`
Expected: `OK` (skip if yaml missing).

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "ci: add tag-triggered release workflow with PyPI Trusted Publishing"
```

---

## Task 18: Final mypy + test sweep and manual wheel smoke test

**Files:** (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `pytest tests/ -q`
Expected: all tests pass (baseline 142 + 3 version + 4 doctor + 1 chromium-missing = **150**).

- [ ] **Step 2: Run mypy across the whole source tree**

Run: `mypy src/`
Expected: `Success: no issues found in 21 source files` (20 baseline + 1 new `__main__.py`).

- [ ] **Step 3: Run ruff**

Run: `ruff check src/ tests/ && ruff format --check src/ tests/`
Expected: no errors.

- [ ] **Step 4: Build the distribution locally**

Run:
```bash
pip install build twine
python -m build
twine check dist/*
```
Expected: sdist + wheel produced, `twine check` reports `PASSED` for both.

- [ ] **Step 5: List the wheel contents to verify file layout**

Run: `python -m zipfile -l dist/xtb_api_python-0.3.0-py3-none-any.whl | head -40`
Expected output includes:
- `xtb_api/__init__.py`
- `xtb_api/__main__.py`
- `xtb_api/py.typed`
- `xtb_api/auth/browser_auth.py`
- `xtb_api_python-0.3.0.dist-info/METADATA`
- `xtb_api_python-0.3.0.dist-info/licenses/LICENSE` (or similar — hatchling varies)

Confirm there's **no** `reference-ts/` or `.venv/` content inside the wheel.

- [ ] **Step 6: Install the wheel in a throwaway venv**

Run:
```bash
python -m venv /tmp/xtb-smoke
/tmp/xtb-smoke/bin/pip install dist/xtb_api_python-0.3.0-py3-none-any.whl
/tmp/xtb-smoke/bin/python -c "import xtb_api; print('version:', xtb_api.__version__); print('client:', xtb_api.XTBClient)"
```
Expected: prints `version: 0.3.0` and the `XTBClient` class object.

- [ ] **Step 7: Run the doctor command from the smoke venv**

Run: `/tmp/xtb-smoke/bin/python -m xtb_api doctor`
Expected: prints the checklist. Chromium-binary check will likely FAIL because `playwright install chromium` hasn't been run in the smoke venv — that's the whole point: **confirm the failure message is clear and mentions `playwright install chromium`**.

- [ ] **Step 8: Clean up the smoke venv**

Run: `rm -rf /tmp/xtb-smoke`

- [ ] **Step 9: Commit** (if any accidental fixes happened during the sweep)

If Steps 1-7 produced no changes to tracked files, skip the commit. Otherwise:

```bash
git add <affected files>
git commit -m "chore: final polish from publish-ready sweep"
```

---

## Task 19: Merge and release

**Files:** (workflow and manual steps, not code)

- [ ] **Step 1: Push the feature branch and open a PR**

Assuming the current branch is the publish-polish branch:

```bash
git push -u origin HEAD
gh pr create \
  --title "Publish-ready polish — first PyPI release (v0.3.0)" \
  --body "Implements docs/superpowers/plans/2026-04-10-publish-polish.md. Closes the gap to a polished, pip-installable PyPI release. See the plan doc for the full task list."
```

- [ ] **Step 2: Verify CI is green on the PR**

Run: `gh pr checks --watch`
Expected: lint, typecheck, test (3.12 + 3.13), build all pass.

- [ ] **Step 3: Merge the PR to master**

Only the user should approve + merge — do not merge from the implementation agent. Pause here and hand back to the user with:

> "PR #N is green. Ready for you to merge and then register the PyPI Trusted Publisher (see CONTRIBUTING.md Release Procedure). After you've done the Trusted Publisher setup, I can cut the v0.3.0 tag."

- [ ] **Step 4 (user): Register Trusted Publishers on PyPI and TestPyPI**

This is a **manual, one-time user action**. The agent must not attempt to automate this — it requires interactive web UI access.

Instructions (documented in CONTRIBUTING.md Task 6 step 1):
1. Create GitHub Environments `pypi` and `testpypi` on the repo.
2. On PyPI `/manage/account/publishing/`, add a pending publisher:
   - Project: `xtb-api-python`
   - Owner: `liskeee`
   - Repo: `xtb-api-python`
   - Workflow: `release.yml`
   - Environment: `pypi`
3. Same on TestPyPI with environment `testpypi`.

- [ ] **Step 5 (user): Tag and release**

After merge and Trusted Publisher setup:

```bash
git checkout master
git pull
git tag v0.3.0
git push origin v0.3.0
```

The release workflow will:
1. Build sdist + wheel
2. Classify `v0.3.0` as stable
3. Publish to PyPI via OIDC
4. Create a GitHub Release with auto-generated notes and the dist files attached

- [ ] **Step 6 (user): Verify the release**

```bash
# Wait ~2 minutes for PyPI to index
pip install xtb-api-python
python -c "import xtb_api; print(xtb_api.__version__)"
```

Expected: prints `0.3.0`. Also verify at https://pypi.org/project/xtb-api-python/.

---

## Spec coverage map

For the self-reviewer: each spec section maps to these tasks.

| Spec section | Tasks |
|---|---|
| Pre-flight PyPI name check | Done in plan pre-flight notes |
| Section 1 — Metadata, licensing, version | 1, 2, 3 |
| Section 2 — CHANGELOG, README, community | 4, 5, 6, 7 |
| Section 3 — CI hardening (matrix + mypy + build + pre-commit) | 8, 9, 10, 11, 12, 15, 16 |
| Section 4 — Release automation | 17, 19 |
| Section 5 — Post-install UX (Chromium error + doctor) | 13, 14 |
| Testing strategy | tests added in tasks 3, 13, 14; final sweep in 18 |
| Manual smoke test | 18 |
