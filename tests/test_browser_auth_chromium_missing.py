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
