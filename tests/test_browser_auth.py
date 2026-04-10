"""Tests for BrowserCASAuth resource cleanup."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from xtb_api.auth.browser_auth import BrowserCASAuth


class TestBrowserSubmitOtpCleanup:
    """Ensure browser resources are cleaned up on errors in submit_otp."""

    @pytest.mark.asyncio
    async def test_close_called_on_submit_otp_error(self):
        """If an exception occurs in submit_otp, close() must be called."""
        auth = BrowserCASAuth()

        # Build a page mock where get_by_placeholder is sync (like real Playwright)
        # but the resulting locator's wait_for raises an error
        mock_page = MagicMock()
        mock_page.wait_for_timeout = AsyncMock()

        mock_locator = MagicMock()
        mock_locator.wait_for = AsyncMock(side_effect=Exception("OTP input not found"))
        mock_page.get_by_placeholder.return_value = mock_locator

        auth._page = mock_page
        auth._browser = AsyncMock()
        auth._playwright = AsyncMock()

        with patch.object(auth, "close", new_callable=AsyncMock) as mock_close:
            with pytest.raises(Exception, match="OTP input not found"):
                await auth.submit_otp("123456")

            mock_close.assert_awaited()


class TestBrowserCloseIdempotent:
    """Ensure close() can be called multiple times safely."""

    @pytest.mark.asyncio
    async def test_close_twice_no_error(self):
        auth = BrowserCASAuth()
        auth._browser = AsyncMock()
        auth._playwright = AsyncMock()

        await auth.close()
        # Second call should not raise (browser/playwright set to None after first close)
        await auth.close()

    @pytest.mark.asyncio
    async def test_close_with_no_browser(self):
        auth = BrowserCASAuth()
        # Should not raise even with no browser started
        await auth.close()
