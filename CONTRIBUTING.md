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
- **Use a Conventional Commits PR title** (e.g. `feat(auth): add TOTP support`,
  `fix(ws): reconnect on idle timeout`). The title becomes the squashed commit
  subject on `master` and drives the automated version bump. A `Commit Lint` CI
  check enforces this.
- Do **not** hand-edit `CHANGELOG.md`. It is regenerated from commit history on
  every release.
- Pre-commit must pass locally before pushing.

Allowed commit types: `feat`, `fix`, `perf`, `refactor`, `docs`, `style`, `test`,
`ci`, `build`, `chore`, `revert`. Only `feat` (minor) and `fix`/`perf` (patch)
trigger a release; the rest are silent.

## Release procedure

Releases are **fully automated** by
[python-semantic-release](https://python-semantic-release.readthedocs.io/).
There is nothing to do by hand:

1. Merge a PR with a conventional commit title to `master`.
2. CI runs. On success, the `Semantic Release` workflow fires, analyzes commits
   since the last tag, bumps `version` in `pyproject.toml`, regenerates
   `CHANGELOG.md`, commits as `chore(release): X.Y.Z`, tags `vX.Y.Z`, pushes
   back to `master`, and creates a GitHub Release.
3. The GitHub Release triggers the `Release` workflow, which builds the wheel
   and sdist, publishes to PyPI via Trusted Publishing, and attaches the
   artifacts to the release.

If no releasable commits are present (e.g. only `chore:` / `docs:`), PSR exits
without cutting a release. No action needed.

### Release candidates (TestPyPI)

For pre-releases, work on the `next` branch:

```bash
git checkout -b next origin/next    # one-time
git merge --ff-only master          # bring next up to date
# land features/fixes on next via PRs targeting `next`
```

Merges to `next` produce `vX.Y.Zrc1` tags, which publish to TestPyPI instead
of PyPI. Install in a fresh venv to verify:

```bash
pip install --index-url https://test.pypi.org/simple/ \
            --extra-index-url https://pypi.org/simple/ \
            "xtb-api-python==X.Y.ZrcN"
python -m xtb_api doctor
```

When an rc is ready for promotion, fast-forward merge `next` back into
`master` and the next PSR run on master will cut a stable release.

### Previewing a release locally

Before enabling this on `master` the first time — or to sanity-check what
PSR will do — run PSR in no-op mode locally:

```bash
pip install "python-semantic-release>=9"
semantic-release --noop version       # prints the next version
semantic-release --noop changelog     # prints the regenerated CHANGELOG
```

Neither command touches the working tree.

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
