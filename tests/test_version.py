"""Ensure __version__ is sourced from package metadata."""

from __future__ import annotations

import re
from importlib.metadata import version as pkg_version

import xtb_api


def test_version_is_string() -> None:
    assert isinstance(xtb_api.__version__, str)
    assert xtb_api.__version__  # non-empty


def test_version_matches_metadata() -> None:
    assert xtb_api.__version__ == pkg_version("xtb-api-python")


def test_version_is_pep440_compatible() -> None:
    # Basic PEP 440 shape: N(.N)*(optional pre/post/dev/local)
    pattern = r"^\d+(\.\d+)*((a|b|rc)\d+)?(\.post\d+)?(\.dev\d+)?(\+[a-zA-Z0-9.]+)?$"
    assert re.match(pattern, xtb_api.__version__), f"Not PEP 440: {xtb_api.__version__}"


class TestPublicCancelReExports:
    def test_cancel_symbols_importable_from_package_root(self):
        from xtb_api import CancelOutcome, CancelResult, TradeOutcome

        assert CancelOutcome.CANCELLED.value == "CANCELLED"
        assert CancelResult is not None
        # QUEUED was added alongside cancel — same gate.
        assert TradeOutcome.QUEUED.value == "QUEUED"
