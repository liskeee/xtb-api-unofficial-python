"""Browser automation client for xStation5.

Connects to an existing Chrome instance via CDP and executes trades by
manipulating AngularJS services directly in the browser context.
"""

from __future__ import annotations

from dataclasses import dataclass

from xtb_api.types.instrument import InstrumentSearchResult, Quote
from xtb_api.types.trading import AccountBalance, Position, TradeOptions, TradeResult


@dataclass
class BrowserClientConfig:
    """Browser client configuration."""
    cdp_url: str
    timeout: int = 15000


class XTBBrowserClient:
    """Browser automation client for xStation5.

    Connects to an existing Chrome instance via CDP and executes trades by
    manipulating AngularJS services directly in the browser context.

    Requirements:
    - Chrome with remote debugging enabled: --remote-debugging-port=9222
    - xStation5 logged in and loaded at https://xstation5.xtb.com
    - playwright installed: pip install xtb-api-python[browser]
    """

    def __init__(self, config: BrowserClientConfig) -> None:
        self._config = config
        self._browser = None
        self._page = None

    async def connect(self) -> None:
        """Connect to Chrome running xStation5.

        Establishes CDP connection and finds the xStation5 tab.

        Raises:
            ImportError: If playwright is not installed
            RuntimeError: If connection fails or xStation5 tab not found
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise ImportError(
                "playwright is required for browser mode. "
                "Install with: pip install xtb-api-python[browser]"
            )

        self._playwright = await async_playwright().start()

        try:
            self._browser = await self._playwright.chromium.connect_over_cdp(
                self._config.cdp_url
            )
        except Exception as e:
            raise RuntimeError(
                f"Failed to connect to Chrome CDP at {self._config.cdp_url}. "
                f"Make sure Chrome is running with --remote-debugging-port. {e}"
            )

        # Find xStation5 tab
        for ctx in self._browser.contexts:
            for page in ctx.pages:
                if "xstation5.xtb.com" in page.url:
                    self._page = page
                    break
            if self._page:
                break

        if not self._page:
            raise RuntimeError(
                "No xStation5 tab found. Make sure xstation5.xtb.com is open and logged in."
            )

        # Verify AngularJS is available
        is_ready = await self.is_ready()
        if not is_ready:
            raise RuntimeError(
                "xStation5 AngularJS services are not available. "
                "Make sure the page is fully loaded and you are logged in."
            )

    async def disconnect(self) -> None:
        """Disconnect from Chrome."""
        if self._browser:
            await self._browser.close()
            self._browser = None
            self._page = None
        if hasattr(self, "_playwright") and self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def is_ready(self) -> bool:
        """Check if connected and xStation5 AngularJS is ready."""
        if not self._page:
            return False
        try:
            return await self._page.evaluate("""() => {
                try {
                    return !!window.angular?.element(document.querySelector('.ng-scope'))?.scope();
                } catch {
                    return false;
                }
            }""")
        except Exception:
            return False

    async def get_balance(self) -> AccountBalance:
        """Get account balance and equity using AngularJS services."""
        self._ensure_page()
        result = await self._page.evaluate("""() => {
            try {
                const angular = window.angular;
                if (!angular) throw new Error('AngularJS not available');
                const $injector = angular.element(document.body).injector();
                if (!$injector) throw new Error('AngularJS injector not available');
                const balanceSvc = $injector.get('api:forexTotalBalanceService');
                if (!balanceSvc) throw new Error('forexTotalBalanceService not available');
                return new Promise((resolve, reject) => {
                    balanceSvc.loadAndSubscribeBalance((eventType, data) => {
                        if (data) {
                            resolve({
                                balance: Number(data.balance || 0),
                                equity: Number(data.equity || 0),
                                free_margin: Number(data.freeMargin || 0),
                                currency: String(data.currency || 'PLN'),
                                account_number: Number(data.aid?.accountNo || 0),
                            });
                        }
                    }, 'python_balance');
                    setTimeout(() => reject(new Error('Balance service timeout')), 5000);
                });
            } catch (error) {
                throw new Error(`Failed to get balance: ${error}`);
            }
        }""")
        return AccountBalance(**result)

    async def get_positions(self) -> list[Position]:
        """Get all open positions using AngularJS services."""
        self._ensure_page()
        result = await self._page.evaluate("""() => {
            try {
                const angular = window.angular;
                if (!angular) throw new Error('AngularJS not available');
                const $injector = angular.element(document.body).injector();
                if (!$injector) throw new Error('AngularJS injector not available');
                const tradeSvc = $injector.get('api:forexTradeRecordService');
                if (!tradeSvc) throw new Error('forexTradeRecordService not available');
                return new Promise((resolve, reject) => {
                    tradeSvc.loadAndSubscribeOpenTrade((eventType, data) => {
                        if (data && Array.isArray(data)) {
                            const positions = data.map(p => ({
                                symbol: String(p.symbol || ''),
                                instrument_id: p.idQuote != null ? Number(p.idQuote) : null,
                                volume: Number(p.volume || 0),
                                current_price: 0,
                                open_price: Number(p.openPrice || 0),
                                stop_loss: p.sl !== 0 ? Number(p.sl) : null,
                                take_profit: p.tp !== 0 ? Number(p.tp) : null,
                                profit_percent: 0,
                                profit_net: Number(p.profit || 0),
                                swap: Number(p.swap || 0),
                                side: p.side === 0 ? 'buy' : 'sell',
                                order_id: String(p.order),
                                open_time: Number(p.openTime || 0)
                            }));
                            resolve(positions);
                        } else {
                            resolve([]);
                        }
                    }, 'python_positions');
                    setTimeout(() => reject(new Error('Position service timeout')), 5000);
                });
            } catch (error) {
                throw new Error(`Failed to get positions: ${error}`);
            }
        }""")
        return [Position(**p) for p in result]

    async def get_quote(self, symbol_name: str) -> Quote | None:
        """Get current quote (bid/ask prices) for a symbol."""
        self._ensure_page()
        result = await self._page.evaluate("""(sym) => {
            try {
                const angular = window.angular;
                if (!angular) throw new Error('AngularJS not available');
                const $injector = angular.element(document.body).injector();
                if (!$injector) throw new Error('AngularJS injector not available');
                const quoteSvc = $injector.get('api:forexQuoteService');
                if (!quoteSvc) throw new Error('forexQuoteService not available');
                return new Promise((resolve, reject) => {
                    try {
                        const allQuotes = quoteSvc.getAllQuotesLight();
                        const symbolData = allQuotes.find(q => q.symbol?.name === sym || q.name === sym);
                        const key = symbolData?.key || sym;
                        quoteSvc.loadAndSubscribeQuotes([key], (eventType, quote) => {
                            if (quote && quote.tick) {
                                const t = quote.tick;
                                resolve({
                                    symbol: sym,
                                    ask: Number(t.ask || 0),
                                    bid: Number(t.bid || 0),
                                    spread: Number(t.ask || 0) - Number(t.bid || 0),
                                    high: Number(t.high || 0),
                                    low: Number(t.low || 0),
                                    time: Number(t.timestamp || 0)
                                });
                            }
                        }, 'python_quote_' + sym);
                        setTimeout(() => resolve(null), 5000);
                    } catch (error) {
                        reject(new Error(`Failed to subscribe to quotes for ${sym}: ${error}`));
                    }
                });
            } catch (error) {
                throw new Error(`Failed to get quote for ${sym}: ${error}`);
            }
        }""", symbol_name)
        if result is None:
            return None
        return Quote(**result)

    async def buy(
        self, symbol: str, volume: int, options: TradeOptions | None = None
    ) -> TradeResult:
        """Execute a BUY order.

        ⚠️ WARNING: This executes real trades.
        """
        return await self._execute_trade_service(symbol, volume, 0, options)

    async def sell(
        self, symbol: str, volume: int, options: TradeOptions | None = None
    ) -> TradeResult:
        """Execute a SELL order.

        ⚠️ WARNING: This executes real trades.
        """
        return await self._execute_trade_service(symbol, volume, 1, options)

    async def search_instrument(self, query: str) -> list[InstrumentSearchResult]:
        """Search for financial instruments by name."""
        self._ensure_page()
        result = await self._page.evaluate("""(q) => {
            try {
                const angular = window.angular;
                if (!angular) throw new Error('AngularJS not available');
                const rootScope = angular.element(document.querySelector('.ng-scope') || document.body).scope().$root;
                if (!rootScope) throw new Error('AngularJS root scope not available');
                const visited = new Set();
                let symbolsArray = null;
                function findSymbols(scope) {
                    if (!scope || visited.has(scope.$id)) return;
                    visited.add(scope.$id);
                    if (scope.symbols?.length > 1000) { symbolsArray = scope.symbols; return; }
                    let child = scope.$$childHead;
                    while (child) { findSymbols(child); if (symbolsArray) return; child = child.$$nextSibling; }
                }
                findSymbols(rootScope);
                if (!symbolsArray) throw new Error('Symbols data not found');
                const ql = q.toLowerCase();
                return symbolsArray
                    .filter(s => {
                        const n = (s.symbol?.name || '').toLowerCase();
                        const d = (s.symbol?.description || '').toLowerCase();
                        return n.includes(ql) || d.includes(ql);
                    })
                    .slice(0, 20)
                    .map(s => ({
                        symbol: s.symbol.name,
                        instrument_id: s.symbol.instrumentId,
                        name: s.symbol.displayName || s.symbol.name,
                        description: s.symbol.description || '',
                        asset_class: s.symbol.searchGroup || '',
                        symbol_key: s.key || `${s.symbol.idAssetClass}_${s.symbol.name}_${s.symbol.groupId}`,
                    }));
            } catch (error) {
                throw new Error(`Failed to search instruments: ${error}`);
            }
        }""", query)
        return [InstrumentSearchResult(**r) for r in result]

    async def get_account_number(self) -> int:
        """Get the account number from the current session."""
        self._ensure_page()
        return await self._page.evaluate("""() => {
            const match = document.body.textContent?.match(/#(\\d{5,})/);
            return match ? parseInt(match[1], 10) : 0;
        }""")

    async def _execute_trade_service(
        self, symbol: str, volume: int, side: int, options: TradeOptions | None = None
    ) -> TradeResult:
        """Execute trade using AngularJS order service."""
        self._ensure_page()

        opts_dict = {
            "stop_loss": options.stop_loss if options else 0,
            "take_profit": options.take_profit if options else 0,
        }

        result = await self._page.evaluate("""async ({sym, vol, side, opts}) => {
            try {
                const angular = window.angular;
                if (!angular) throw new Error('AngularJS not available');
                const $injector = angular.element(document.body).injector();
                if (!$injector) throw new Error('AngularJS injector not available');
                const orderSvc = $injector.get('api:forexOrderService');
                if (!orderSvc) throw new Error('forexOrderService not available');
                const quoteSvc = $injector.get('api:forexQuoteService');
                if (!quoteSvc) throw new Error('forexQuoteService not available');
                const allQuotes = quoteSvc.getAllQuotesLight();
                const symbolData = allQuotes.find(q => q.symbol?.name === sym || q.name === sym);
                if (!symbolData) throw new Error(`Symbol not found: ${sym}`);
                return new Promise((resolve, reject) => {
                    const callback = (res) => {
                        if (res && res.status === 'SUCCESS') {
                            resolve({
                                success: true, symbol: sym,
                                side: side === 0 ? 'buy' : 'sell',
                                volume: vol, order_id: res.orderId
                            });
                        } else {
                            resolve({
                                success: false, symbol: sym,
                                side: side === 0 ? 'buy' : 'sell',
                                error: res?.exception?.message || 'Trade failed'
                            });
                        }
                    };
                    try {
                        if (side === 0) {
                            orderSvc.newOpenTradeBuy(symbolData, vol, opts.stop_loss || 0, opts.take_profit || 0, callback);
                        } else {
                            orderSvc.newOpenTradeSell(symbolData, vol, opts.stop_loss || 0, opts.take_profit || 0, callback);
                        }
                    } catch (error) { reject(new Error(`Failed to execute trade: ${error}`)); }
                    setTimeout(() => reject(new Error('Trade execution timeout')), 30000);
                });
            } catch (error) { throw new Error(`Trade execution failed: ${error}`); }
        }""", {"sym": symbol, "vol": volume, "side": side, "opts": opts_dict})
        return TradeResult(**result)

    def _ensure_page(self) -> None:
        """Ensure page connection is available."""
        if not self._page:
            raise RuntimeError(
                "Not connected to xStation5. Call connect() first."
            )
