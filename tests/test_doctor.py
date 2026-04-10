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
        captured = capsys.readouterr()
        assert "doctor" in (captured.out + captured.err)

    def test_main_dispatches_doctor_subcommand(self) -> None:
        with (
            patch.object(sys, "argv", ["xtb-api", "doctor"]),
            patch("xtb_api.__main__.run_doctor", return_value=0) as mock_run,
        ):
            exit_code = main()
        assert exit_code == 0
        mock_run.assert_called_once()
