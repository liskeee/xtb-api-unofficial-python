import asyncio
import glob
import json
import logging
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

CDP_PORT = 18800


class ChromeSession:
    '''Manages a long-running headless Chrome with xStation5 for gRPC trading.

    Chrome runs as a background subprocess. The session stays alive between trades.
    Call ensure_ready() before each trade — it checks health and restarts if needed.
    Call stop() when shutting down the bot.
    '''

    def __init__(self, email: str, password: str, totp_secret: str = '',
                 cdp_port: int = CDP_PORT, user_data_dir: str | None = None,
                 startup_timeout: int = 60):
        self._email = email
        self._password = password
        self._totp_secret = totp_secret
        self._cdp_port = cdp_port
        self._user_data_dir = user_data_dir
        self._startup_timeout = startup_timeout
        self._proc: subprocess.Popen | None = None
        self._started_at: float | None = None
        self._tgt: str | None = None
        self._session_max_age = 7 * 3600  # restart Chrome every 7h (TGT lasts 8h)

    @property
    def cdp_url(self) -> str:
        return f'http://localhost:{self._cdp_port}'

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    async def start(self) -> str:
        '''Start Chrome and login. Returns TGT.'''
        if self.is_running:
            return self._tgt or ''
        await self._launch_chrome()
        await self._login()
        await self._wait_for_service_worker()
        self._started_at = time.time()
        logger.info('Chrome session ready on port %d', self._cdp_port)
        return self._tgt or ''

    async def ensure_ready(self) -> str:
        '''Ensure Chrome is running and session is fresh. Restart if needed.'''
        if not self.is_running:
            logger.info('Chrome not running, starting...')
            return await self.start()

        if self._started_at and (time.time() - self._started_at) > self._session_max_age:
            logger.info('Chrome session expired (>7h), restarting...')
            await self.stop()
            return await self.start()

        try:
            urllib.request.urlopen(f'{self.cdp_url}/json/version', timeout=2)
            return self._tgt or ''
        except Exception:
            logger.warning('Chrome CDP not responding, restarting...')
            await self.stop()
            return await self.start()

    async def stop(self):
        '''Stop Chrome subprocess.'''
        if self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=3)
            self._proc = None
        self._started_at = None
        self._tgt = None
        # Clean up temp profile
        if hasattr(self, '_temp_dir') and self._temp_dir:
            import shutil
            shutil.rmtree(self._temp_dir, ignore_errors=True)
            self._temp_dir = None

    async def _launch_chrome(self):
        '''Launch Chrome subprocess with CDP port.'''
        chromium = self._find_chromium()
        # Always use a fresh temp profile to avoid stale session state
        import tempfile
        self._temp_dir = tempfile.mkdtemp(prefix='xtb-chrome-')
        user_data = self._temp_dir

        logger.info('Starting headless Chrome with CDP on port %d...', self._cdp_port)
        self._proc = subprocess.Popen(
            [
                chromium,
                '--headless=new',
                '--no-sandbox',
                '--disable-gpu',
                '--disable-dev-shm-usage',
                f'--remote-debugging-port={self._cdp_port}',
                f'--user-data-dir={user_data}',
                '--window-size=1280,720',
                'about:blank',
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        await self._wait_for_cdp()

    async def _login(self):
        '''Login via Playwright connect_over_cdp — then disconnect Playwright.'''
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise RuntimeError(
                'Playwright required. Install: pip install playwright && playwright install chromium'
            )

        pw = await async_playwright().start()
        try:
            browser = await pw.chromium.connect_over_cdp(self.cdp_url)
            ctx = browser.contexts[0]
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()

            await page.goto(
                'https://xstation5.xtb.com/',
                wait_until='domcontentloaded',
                timeout=30000,
            )

            # Check if already logged in (persistent profile)
            if 'loggedIn' in page.url:
                logger.info('Already logged in (persistent session)')
                self._tgt = 'persistent'
            else:
                await self._fill_login(page)

            # Disconnect Playwright WITHOUT closing Chrome
            await browser.close()
        finally:
            await pw.stop()

    async def _fill_login(self, page):
        '''Fill login form, handle 2FA, wait for login to complete.'''
        await page.wait_for_selector(
            'input[name="xslogin"]', state='visible', timeout=15000
        )
        await page.click('input[name="xslogin"]')
        await page.keyboard.type(self._email, delay=30)
        await page.click('input[name="xspass"]')
        await page.keyboard.type(self._password, delay=30)
        await page.wait_for_timeout(300)

        submit = page.locator('input[type="button"].xs-btn-ok-login')
        if await submit.is_visible(timeout=3000):
            await submit.click()
        else:
            await page.press('input[name="xspass"]', 'Enter')

        logger.info('Login submitted, waiting for 2FA or dashboard...')

        # Handle 2FA
        try:
            otp_input = page.get_by_placeholder('Wprowadź kod tutaj')
            await otp_input.wait_for(state='visible', timeout=10000)

            if not self._totp_secret:
                raise RuntimeError('2FA required but no totp_secret provided')

            import pyotp
            code = pyotp.TOTP(self._totp_secret).now()
            await otp_input.fill(code)
            submit_btn = page.get_by_role('button', name='Weryfikacja')
            await submit_btn.click()
            logger.info('TOTP submitted')
        except Exception:
            logger.info('No 2FA prompt detected')

        # Wait for login to complete
        for i in range(30):
            await page.wait_for_timeout(1000)
            if 'loggedIn' in page.url:
                logger.info('Login complete after %ds', i + 1)
                break

    async def _wait_for_cdp(self):
        '''Poll until CDP responds.'''
        for i in range(self._startup_timeout):
            await asyncio.sleep(1)
            try:
                urllib.request.urlopen(f'{self.cdp_url}/json/version', timeout=2)
                logger.info('Chrome CDP ready after %ds', i + 1)
                return
            except Exception:
                pass
        raise RuntimeError(f'Chrome CDP not ready after {self._startup_timeout}s')

    async def _wait_for_service_worker(self):
        '''Wait for xStation Service Worker to register.'''
        for i in range(30):
            await asyncio.sleep(1)
            try:
                resp = urllib.request.urlopen(
                    f'{self.cdp_url}/json/list', timeout=2
                )
                tabs = json.loads(resp.read())
                workers = [
                    t for t in tabs
                    if t.get('type') in ('service_worker', 'worker')
                ]
                if workers:
                    await asyncio.sleep(5)
                    logger.info('Service Worker ready after %ds', i + 1)
                    return
            except Exception:
                pass
        logger.warning('Service Worker not found after 30s')

    def _find_chromium(self) -> str:
        '''Find Chromium binary.'''
        for name in ['google-chrome', 'chromium-browser', 'chromium', 'chrome']:
            path = shutil.which(name)
            if path:
                return path

        # Playwright bundled Chromium
        for pattern in [
            str(Path.home() / '.cache/ms-playwright/chromium-*/chrome-linux/chrome'),
            str(Path.home() / '.cache/ms-playwright/chromium-*/chrome-linux/headless_shell'),
        ]:
            matches = glob.glob(pattern)
            if matches:
                return sorted(matches)[-1]

        raise RuntimeError('No Chromium browser found')

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *args):
        await self.stop()
