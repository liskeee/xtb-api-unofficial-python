import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CDP_PORT = 18800


class ChromeSession:
    '''Manages a headless Chrome instance with xStation5 logged in.

    Launches Playwright Chromium with --remote-debugging-port so that
    gRPC-web executor can connect via CDP. Handles login + 2FA automatically.
    '''

    def __init__(self, email: str, password: str, totp_secret: str = '',
                 cdp_port: int = CDP_PORT, user_data_dir: str | None = None):
        self._email = email
        self._password = password
        self._totp_secret = totp_secret
        self._cdp_port = cdp_port
        self._user_data_dir = user_data_dir
        self._playwright = None
        self._browser = None
        self._page = None
        self._tgt = None

    @property
    def cdp_url(self) -> str:
        return f'http://localhost:{self._cdp_port}'

    @property
    def is_running(self) -> bool:
        return self._browser is not None and self._browser.is_connected()

    async def start(self) -> str:
        '''Launch Chrome, navigate to xStation5, login, return TGT.

        After this, gRPC executor can connect to localhost:{cdp_port}.
        '''
        if self.is_running:
            logger.info('Chrome session already running')
            return self._tgt or ''

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise RuntimeError(
                'Playwright required. Install: pip install playwright && playwright install chromium'
            )

        logger.info('Starting headless Chrome with CDP on port %d...', self._cdp_port)

        self._playwright = await async_playwright().start()

        # Launch with remote debugging port
        args = [
            '--disable-blink-features=AutomationControlled',
            '--no-sandbox',
            f'--remote-debugging-port={self._cdp_port}',
        ]

        launch_kwargs = {
            'headless': True,
            'args': args,
        }

        # Use persistent context if user_data_dir provided (preserves cookies)
        if self._user_data_dir:
            Path(self._user_data_dir).mkdir(parents=True, exist_ok=True)
            context = await self._playwright.chromium.launch_persistent_context(
                self._user_data_dir,
                **launch_kwargs,
                user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                locale='pl-PL',
                timezone_id='Europe/Warsaw',
            )
            self._browser = context.browser
            self._page = context.pages[0] if context.pages else await context.new_page()
        else:
            self._browser = await self._playwright.chromium.launch(**launch_kwargs)
            context = await self._browser.new_context(
                user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                locale='pl-PL',
                timezone_id='Europe/Warsaw',
            )
            # Inject stealth
            await context.add_init_script('''
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                window.chrome = { runtime: {} };
            ''')
            self._page = await context.new_page()

        # Navigate to xStation5 and login
        logger.info('Navigating to xStation5...')
        await self._page.goto('https://xstation5.xtb.com/', wait_until='domcontentloaded', timeout=30000)
        await self._page.wait_for_selector('input[name="xslogin"]', state='visible', timeout=30000)

        # Fill login
        await self._page.click('input[name="xslogin"]')
        await self._page.keyboard.type(self._email, delay=30)
        await self._page.click('input[name="xspass"]')
        await self._page.keyboard.type(self._password, delay=30)
        await self._page.wait_for_timeout(300)

        # Submit
        submit = self._page.locator('input[type="button"].xs-btn-ok-login')
        if await submit.is_visible(timeout=3000):
            await submit.click()
        else:
            await self._page.press('input[name="xspass"]', 'Enter')

        logger.info('Login submitted, waiting for 2FA or dashboard...')

        # Set up TGT interceptor
        tgt_event = asyncio.Event()
        captured_tgt = {'value': None}

        async def on_response(response):
            try:
                if 'v2/tickets' in response.url and 'serviceTicket' not in response.url:
                    ct = response.headers.get('content-type', '')
                    if 'json' in ct:
                        body = await response.json()
                        ticket = body.get('ticket')
                        if body.get('loginPhase') == 'TGT_CREATED' and ticket:
                            captured_tgt['value'] = ticket
                            tgt_event.set()
            except Exception:
                pass

        self._page.on('response', on_response)

        # Check for 2FA
        try:
            otp_input = self._page.get_by_placeholder('Wprowadź kod tutaj')
            await otp_input.wait_for(state='visible', timeout=10000)

            # 2FA needed - generate TOTP
            if not self._totp_secret:
                raise RuntimeError('2FA required but no totp_secret provided')

            import pyotp
            code = pyotp.TOTP(self._totp_secret).now()
            logger.info('Submitting TOTP code...')
            await otp_input.fill(code)

            submit_btn = self._page.get_by_role('button', name='Weryfikacja')
            await submit_btn.click()

            # Wait for TGT
            await asyncio.wait_for(tgt_event.wait(), timeout=30)
            self._tgt = captured_tgt['value']

        except Exception as e:
            if captured_tgt['value']:
                self._tgt = captured_tgt['value']
            elif 'Timeout' in type(e).__name__:
                # Maybe no 2FA, check if we're on dashboard
                logger.info('No 2FA detected, checking if logged in...')
                await self._page.wait_for_timeout(5000)
            else:
                raise

        # Wait for xStation to fully load (Service Worker needs to be ready for gRPC)
        logger.info('Waiting for xStation to initialize...')
        await self._page.wait_for_timeout(5000)

        logger.info('Chrome session ready on port %d', self._cdp_port)
        return self._tgt or ''

    async def stop(self):
        '''Stop the Chrome session.'''
        try:
            if self._browser:
                await self._browser.close()
        except Exception:
            pass
        try:
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass
        self._browser = None
        self._page = None
        self._playwright = None
        self._tgt = None

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *args):
        await self.stop()
