---
title: xtb-api-python — publication polish & PyPI release design
date: 2026-04-10
status: approved
---

# xtb-api-python — publication polish design

## Goal

Bring the library from its current "works locally" state to a polished, 1.0-ready
public release on PyPI, installable via `pip install xtb-api-python` and
listable in a `requirements.txt` like any other dependency.

## Non-goals

- Writing a Sphinx/MkDocs documentation site (README is sufficient for now).
- Refactoring the library surface area. Public API stays as-is.
- Removing the playwright dependency. Playwright is **required** for auth because
  XTB's WAF blocks all non-browser login paths; it is not a fallback.
- Setting up a CODE_OF_CONDUCT.md.
- Implementing a test matrix beyond Python 3.12 and 3.13.

## Context

Current state (2026-04-10):

- **Build backend**: hatchling
- **Version drift**: `pyproject.toml` = `0.3.0`, `src/xtb_api/__init__.py` = `0.2.0`,
  `CHANGELOG.md` still labels the latest section `0.2.0 (Unreleased)`
- **Missing `LICENSE` file** (MIT is declared in `pyproject.toml`, but no text file)
- **No author email** in pyproject metadata
- **No `[project.urls]`** (no homepage, repository, issues, changelog links)
- **Classifiers** list only Python 3.12; no `Typed`, no `OS Independent`
- **CI** runs ruff + pytest on Python 3.12 only; `[tool.mypy]` config exists but
  mypy is not wired into CI
- **No release workflow** to publish to PyPI
- **No badges** in README
- **No `CONTRIBUTING.md` / `SECURITY.md`**
- **`playwright` is a core dependency** but the Chromium binary requires a manual
  `playwright install chromium` post-install step; failure mode is a cryptic
  playwright internal error
- **Tests**: 142 tests, all mocked, no real Chromium needed in CI
- **`py.typed` marker**: already present — good

## Approach

**Single "publish-ready" branch.** All changes land on one branch, merge to master,
then a `v0.3.0` tag is pushed to trigger the release workflow. No phased PRs, no
TestPyPI dry-run for this first release (but TestPyPI is wired in for future use).

## Pre-flight check (must pass before any implementation)

1. **Verify PyPI name availability**: attempt `pip index versions xtb-api-python`
   or visit `https://pypi.org/project/xtb-api-python/`. If the name is taken by
   another package, **stop** and escalate to the user to pick a new name before
   proceeding. Every decision in this spec assumes the name is available.

## Design

### Section 1 — Metadata, licensing & version alignment

**Add `LICENSE` file at the repo root** containing the full MIT License text with
a copyright line: `Copyright (c) 2025-2026 Łukasz Lis`. Hatchling will
automatically include `LICENSE` in both sdist and wheel.

**`pyproject.toml` updates**:

- Set `authors = [{ name = "Łukasz Lis", email = "ll.lukasz.lis@gmail.com" }]`
- Add `[project.urls]`:
  - `Homepage = "https://github.com/liskeee/xtb-api-python"`
  - `Repository = "https://github.com/liskeee/xtb-api-python"`
  - `Issues = "https://github.com/liskeee/xtb-api-python/issues"`
  - `Changelog = "https://github.com/liskeee/xtb-api-python/blob/master/CHANGELOG.md"`
- Add classifiers:
  - `"Programming Language :: Python :: 3.13"`
  - `"Operating System :: OS Independent"`
  - `"Typing :: Typed"`
  - `"Framework :: AsyncIO"`
- Bump `Development Status` classifier from `3 - Alpha` to `4 - Beta` (the lib has
  142 tests and a stable public API — Alpha understates maturity).
- Keep `requires-python = ">=3.12"`
- Tighten `[tool.hatch.build.targets.wheel]` to include only `src/xtb_api`
  (exclude `reference-ts/`, `examples/`, `docs/`, `tests/`, `.venv/`).
- Confirm `[tool.hatch.build.targets.sdist]` ships `src/`, `tests/`, `examples/`,
  `README.md`, `LICENSE`, `CHANGELOG.md`, `pyproject.toml` (sdist is the
  "reproducible source" tarball; tests + examples are welcome there).

**`src/xtb_api/__init__.py`**:

Replace the hard-coded `__version__ = "0.2.0"` line with:

```python
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

try:
    __version__ = _pkg_version("xtb-api-python")
except PackageNotFoundError:  # pragma: no cover — editable install edge case
    __version__ = "0.0.0+unknown"
```

This reads the version from the installed package metadata so it can never drift
from `pyproject.toml` again.

**Version for this release**: `0.3.0`. `pyproject.toml` is already there; nothing
to bump, just align `__init__.py` (via the metadata read above) and CHANGELOG.

### Section 2 — CHANGELOG, README & community files

**`CHANGELOG.md`**:

- Rename the `## 0.2.0 (Unreleased)` heading to `## 0.3.0 — 2026-04-10`
- Add a new section summarizing post-refactor fixes landing in 0.3.0 (drawn from
  recent commits): duplicate symbol-download lock, tick subscription leak in
  `get_quote`, browser resource leak on auth error, TOTP window-edge fix, CAS
  cookie persistence
- Adopt [Keep a Changelog](https://keepachangelog.com/) headings going forward:
  `### Added`, `### Changed`, `### Fixed`, `### Removed`

**`README.md`**:

- Add badges at top (PyPI version, supported Python versions, CI status, License)
- Promote `playwright install chromium` into a **prominent post-install callout**
  with its own heading (currently it's one line at the bottom of the install
  block, trivially missed)
- Add a "Requirements" subsection: Python 3.12+, Chromium (installed via
  playwright), an XTB trading account
- Leave the disclaimer block intact

**New file: `CONTRIBUTING.md`** — short. Covers:

- Dev env setup: `uv sync --all-extras` or `pip install -e ".[dev,totp]"`
- Post-install: `playwright install chromium`
- Run tests: `pytest`
- Run lint: `ruff check src/ tests/` and `ruff format --check src/ tests/`
- Run type check: `mypy src/`
- Pre-commit setup: `pre-commit install`
- Release procedure (documented so future-you can follow it)
- PR conventions: one logical change per PR, keep diffs reviewable

**New file: `SECURITY.md`** — short. Covers:

- How to report a security issue (email `ll.lukasz.lis@gmail.com`, do not open a
  public issue)
- Supported versions table (`0.3.x` supported; older versions unsupported)
- Disclosure timeline expectation (e.g., initial response within 7 days)

### Section 3 — CI hardening

**`.github/workflows/ci.yml` rewrite**:

```yaml
name: CI

on:
  push:
    branches: [master]
  pull_request:
    branches: [master]

concurrency:
  group: ci-${{ github.ref }}
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
      - run: pip install ruff
      - run: ruff check src/ tests/
      - run: ruff format --check src/ tests/

  typecheck:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: pip install -e ".[dev,totp]" mypy
      - run: mypy src/

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
      - run: pip install -e ".[dev,totp]"
      - run: pytest --tb=short -q

  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: pip install build twine
      - run: python -m build
      - run: twine check dist/*
      - uses: actions/upload-artifact@v4
        with:
          name: dist
          path: dist/
          retention-days: 7
```

**Rationale**:
- Separate `typecheck` job runs mypy (previously configured but never executed).
- `test` job runs a Python 3.12 + 3.13 matrix.
- `build` job runs `python -m build` and `twine check dist/*` so README rendering
  and metadata problems fail CI before tag time.
- `concurrency` group cancels stale runs.
- `cache: pip` speeds up jobs without adding a new action.
- CI **does not** install a Chromium binary; all tests are mocked.

**`.pre-commit-config.yaml` updates**:

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

### Section 4 — Release automation

**New workflow: `.github/workflows/release.yml`**:

```yaml
name: Release

on:
  push:
    tags:
      - "v*"

jobs:
  build:
    runs-on: ubuntu-latest
    outputs:
      is_prerelease: ${{ steps.classify.outputs.is_prerelease }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: pip install build twine
      - run: python -m build
      - run: twine check dist/*
      - id: classify
        run: |
          TAG="${GITHUB_REF_NAME}"
          if [[ "$TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
            echo "is_prerelease=false" >> "$GITHUB_OUTPUT"
          else
            echo "is_prerelease=true" >> "$GITHUB_OUTPUT"
          fi
      - uses: actions/upload-artifact@v4
        with:
          name: dist
          path: dist/

  publish-testpypi:
    needs: build
    if: ${{ needs.build.outputs.is_prerelease == 'true' }}
    runs-on: ubuntu-latest
    environment: testpypi
    permissions:
      id-token: write
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist/
      - uses: pypa/gh-action-pypi-publish@release/v1
        with:
          repository-url: https://test.pypi.org/legacy/

  publish-pypi:
    needs: build
    if: ${{ needs.build.outputs.is_prerelease == 'false' }}
    runs-on: ubuntu-latest
    environment: pypi
    permissions:
      id-token: write
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist/
      - uses: pypa/gh-action-pypi-publish@release/v1

  github-release:
    needs: [build, publish-pypi]
    if: ${{ needs.build.outputs.is_prerelease == 'false' }}
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4
      - uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist/
      - name: Create GitHub Release
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          gh release create "$GITHUB_REF_NAME" \
            --title "$GITHUB_REF_NAME" \
            --notes-from-tag \
            dist/*
```

**Classification rule**: tags matching `v[0-9]+.[0-9]+.[0-9]+` (e.g., `v0.3.0`)
publish to PyPI + create a GitHub Release. Tags with any suffix (`v0.3.0rc1`,
`v0.3.0.dev1`, `v0.4.0a1`) publish to **TestPyPI** only.

**Manual one-time setup (user, not implementation)**:

1. Create a GitHub Environment named `pypi` on the repo. Optionally require
   reviewers for extra safety.
2. Create a GitHub Environment named `testpypi` on the repo.
3. On PyPI (`https://pypi.org/manage/account/publishing/`), add a pending
   trusted publisher:
   - PyPI project name: `xtb-api-python`
   - Owner: `liskeee`
   - Repository: `xtb-api-python`
   - Workflow: `release.yml`
   - Environment: `pypi`
4. On TestPyPI (`https://test.pypi.org/manage/account/publishing/`), same but
   with environment `testpypi`.

**Release procedure (documented in CONTRIBUTING.md)**:

1. Update `CHANGELOG.md`: set the version heading date
2. Commit, push, wait for CI to go green
3. `git tag v0.3.0 && git push origin v0.3.0`
4. Release workflow builds, publishes to PyPI, creates GitHub Release

### Section 5 — Post-install UX for Chromium

**Problem**: `pip install xtb-api-python` installs the playwright Python package
but not the Chromium binary. Without running `playwright install chromium`, the
first auth attempt fails deep inside playwright with an unhelpful error.

**Design**:

**1. Wrap Chromium launch in the browser auth module.**
Wherever the code calls `p.chromium.launch(...)` (inside the browser auth path),
catch `playwright.async_api.Error` (or the specific "executable doesn't exist"
variant) and re-raise as an `AuthenticationError` with an actionable message:

```
Chromium browser not found. The xtb-api-python library requires a Chromium
install for XTB authentication. Run:

    playwright install chromium

See https://github.com/liskeee/xtb-api-python#post-install-setup for details.
```

The implementation will find the exact launch site via `grep` (likely in
`src/xtb_api/auth/browser_auth.py` or similar). Exact catch type will be
determined by reading playwright's error module at implementation time.

**2. Add `python -m xtb_api doctor` command.**

Create `src/xtb_api/__main__.py` with a minimal CLI dispatcher (no `click` /
`typer` dependency — stdlib `argparse` is enough). Supports one subcommand:
`doctor`.

`xtb_api doctor` prints a checklist:

- `[OK] Python 3.12.x` (or FAIL with required version)
- `[OK] xtb-api-python 0.3.0` (reads via `importlib.metadata`)
- `[OK] playwright Python package installed` (or FAIL)
- `[OK] Chromium binary available` (attempts a lightweight `chromium.executable_path`
  check without launching)
- `[OK] pyotp installed (optional)` or `[--] pyotp not installed — 2FA auto-handling
  unavailable`

Exit 0 if all required checks pass, non-zero otherwise. Add
`[project.scripts] xtb-api = "xtb_api.__main__:main"` so users can also run
`xtb-api doctor`.

**3. Prominent README callout** (covered in Section 2).

## Data flow / boundaries

This is a packaging-and-infrastructure change, not an architectural one. The
public API is unchanged. The only new runtime code paths are:

- The `importlib.metadata` version lookup in `__init__.py`
- The `ImportError`/`playwright.Error` → `AuthenticationError` translation in
  browser auth
- The `python -m xtb_api doctor` CLI in `__main__.py`

Everything else is static files (LICENSE, CONTRIBUTING.md, SECURITY.md),
configuration updates (`pyproject.toml`, `.pre-commit-config.yaml`), and CI
workflow changes.

## Testing strategy

- **Existing 142 tests** must stay green on both Python 3.12 and 3.13
- **New tests**:
  - `test_version.py` — asserts `xtb_api.__version__` is a valid semver string
    and matches `importlib.metadata.version("xtb-api-python")`
  - `test_doctor.py` — invokes the doctor CLI in-process (via `runpy` or direct
    call), asserts it reports the correct status for a known-good and
    known-missing state (mock `importlib.util.find_spec` / playwright
    availability)
  - `test_browser_auth_chromium_missing.py` — mocks the playwright launch to
    raise the expected error, asserts the translation to `AuthenticationError`
    with the install-instructions message
- **CI build job** — `python -m build && twine check dist/*` catches metadata,
  README rendering, and manifest problems
- **Manual smoke test before tagging** — in a fresh venv:
  `pip install dist/xtb_api_python-0.3.0-py3-none-any.whl` and then
  `python -c "import xtb_api; print(xtb_api.__version__)"` — confirms the built
  wheel imports cleanly

## Risks

1. **PyPI name taken.** If `xtb-api-python` is already registered by someone
   else, the entire plan stops. The pre-flight check catches this.
2. **Trusted publisher misconfiguration.** If the GitHub Environment name, repo
   owner, or workflow filename doesn't match the PyPI trusted publisher
   config, the publish step fails with a cryptic OIDC error. Mitigation: the
   CONTRIBUTING.md release procedure lists the exact names, and a TestPyPI
   trial run with `v0.3.0rc1` is recommended but not required for the first
   stable release.
3. **mypy failures on enabled.** `[tool.mypy]` currently sets
   `disallow_untyped_defs = true` and `warn_return_any = true`. Adding mypy to
   CI may surface type errors that have been silently ignored. Mitigation: run
   `mypy src/` locally first, fix what's found, and only then wire it into CI.
   If the fixes are nontrivial, we may need a targeted "mypy cleanup" commit
   before enabling the CI job — the plan should schedule this.
4. **Python 3.13 incompatibility.** The matrix addition may reveal 3.13-specific
   issues (e.g., deprecated asyncio APIs). Mitigation: run the test suite on
   3.13 locally first; if broken, either fix or drop 3.13 from the matrix and
   revisit.
5. **Hatchling version discovery.** `importlib.metadata.version("xtb-api-python")`
   only works after the package is installed (even editable). For an
   uninstalled checkout (`python src/xtb_api/__init__.py`), the fallback
   `"0.0.0+unknown"` handles it. This is acceptable.
6. **Browser error class.** The exact playwright exception type for "chromium
   binary missing" needs to be verified at implementation time; catching too
   broadly (bare `Exception`) hides real bugs.

## Implementation order (for the plan)

1. Pre-flight: verify PyPI name availability
2. Metadata + LICENSE + version (`__init__.py` via `importlib.metadata`)
3. CHANGELOG rename + README badges + callout
4. CONTRIBUTING.md + SECURITY.md
5. Run mypy locally; fix any errors surfaced
6. CI workflow rewrite (lint/typecheck/test matrix/build jobs)
7. Pre-commit updates
8. Browser auth error translation + test
9. `python -m xtb_api doctor` command + test
10. Release workflow + docs for manual PyPI trusted publisher setup
11. Manual smoke test: build wheel locally, install in a clean venv, import
12. Merge to master, tag `v0.3.0`, push tag, verify publish
