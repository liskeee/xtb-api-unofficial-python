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
