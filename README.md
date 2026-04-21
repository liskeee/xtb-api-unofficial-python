[![PyPI version](https://img.shields.io/pypi/v/xtb-api-python.svg)](https://pypi.org/project/xtb-api-python/)
[![Python versions](https://img.shields.io/pypi/pyversions/xtb-api-python.svg)](https://pypi.org/project/xtb-api-python/)
[![CI](https://github.com/liskeee/xtb-api-python/actions/workflows/ci.yml/badge.svg)](https://github.com/liskeee/xtb-api-python/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

# xtb-api-python

> **Unofficial** — Reverse-engineered from xStation5. Not affiliated with XTB. Use at your own risk.

Python client for the XTB xStation5 trading platform. Dead-simple API that handles all authentication, token refresh, and transport selection transparently.

## Features

- **Single Client** — One `XTBClient` handles everything, no mode selection needed
- **Auto Auth** — Full CAS login flow with automatic TGT/JWT refresh
- **2FA Support** — Automatic TOTP handling when `totp_secret` is provided
- **Real-time Data** — Live quotes, positions, balance via WebSocket push events
- **Trading** — Buy/sell market orders with SL/TP via gRPC-web
- **Volume-Validated Orders** — `buy`/`sell` reject `volume < 1` before touching the wire
- **Persistent Instrument Cache** — `InstrumentRegistry` caches symbol → instrument-ID lookups to disk
- **Full Symbol Search** — Search and resolve all listed instruments with caching
- **Modern Python** — async/await, Pydantic models, strict typing, Python 3.12+

## Requirements

- Python **3.12 or 3.13**
- Chromium browser (installed via playwright — see post-install step below)
- An XTB trading account

## Install

```bash
pip install xtb-api-python

# With automatic 2FA handling:
pip install "xtb-api-python[totp]"
```

### Post-install setup (REQUIRED)

This library uses [Playwright](https://playwright.dev/python/) to authenticate with
XTB's servers (the REST login path is blocked by a WAF). **After** `pip install`,
you must download the Chromium binary:

```bash
playwright install chromium
```

Without this step, the first call to `client.connect()` will fail with a
`CASError("BROWSER_CHROMIUM_MISSING", ...)` and a pointer back here.

To verify your install is complete, run:

```bash
python -m xtb_api doctor
```

### Development install

```bash
pip install -e ".[dev,totp]"
playwright install chromium
pre-commit install
```

## Quick Start

```python
import asyncio
from xtb_api import XTBClient

async def main():
    client = XTBClient(
        email="your@email.com",
        password="your-password",
        account_number=12345678,
        totp_secret="BASE32SECRET",      # optional, auto-handles 2FA
        session_file="~/.xtb_session",   # optional, persists auth across restarts
    )

    await client.connect()

    # Account data
    balance = await client.get_balance()
    print(f"Balance: {balance.balance} {balance.currency}")

    positions = await client.get_positions()
    orders = await client.get_orders()

    # Live quote
    quote = await client.get_quote("EURUSD")
    if quote:
        print(f"Bid: {quote.bid}, Ask: {quote.ask}")

    # Search instruments
    results = await client.search_instrument("Apple")

    # Persistent instrument cache (avoids re-fetching the full symbol list)
    from xtb_api import InstrumentRegistry
    registry = InstrumentRegistry("~/.xtb_instruments.json")
    matched = await registry.populate(client, ["AAPL.US", "EURUSD"])
    instrument_id = registry.get("AAPL.US")  # int | None

    # Trading (USE WITH CAUTION!)
    result = await client.buy("AAPL.US", volume=1, stop_loss=150.0, take_profit=200.0)
    print(f"Order: {result.order_id}")

    await client.disconnect()

asyncio.run(main())
```

### Real-time Events

```python
client.on("tick", lambda tick: print(f"{tick['symbol']}: {tick['bid']}/{tick['ask']}"))
client.on("position", lambda pos: print(f"Position update: {pos['symbol']}"))

await client.subscribe_ticks("EURUSD")
```

### Advanced Trade Options

```python
from xtb_api import TradeOptions

# Simple: flat kwargs
await client.buy("EURUSD", volume=1, stop_loss=1.0850, take_profit=1.0950)

# Advanced: TradeOptions object
await client.sell("CIG.PL", volume=100, options=TradeOptions(
    trailing_stop=50,
    amount=1000.0,  # amount-based sizing
))
```

### Queued orders (market closed)

When the instrument's market is closed, XTB accepts the order and queues
it until market open. The library surfaces this as `TradeOutcome.QUEUED`
rather than lying about a fill:

```python
result = await client.buy("AAPL.US", volume=1)

match result.status:
    case TradeOutcome.FILLED:
        print(f"Filled at {result.price}")
    case TradeOutcome.QUEUED:
        print(f"Queued {result.order_number}; cancelling...")
        cancel = await client.cancel_order(result.order_number)
        print(f"Cancel status: {cancel.status}")
    case _:
        print(f"Trade failed: {result.status} — {result.error}")
```

`TradeResult.order_number` is populated for both `FILLED` and `QUEUED`
outcomes. `cancel_order()` returns a typed `CancelResult` with
`CancelOutcome` values (`CANCELLED`, `REJECTED`, `AMBIGUOUS`).

> `TradeResult.price` is populated by polling open positions immediately after fill. If the position cannot be located within the poll window, `price` remains `None`.

## API Reference

### `XTBClient`

| Method | Returns | Description |
|--------|---------|-------------|
| `connect()` | `None` | Connect and authenticate |
| `disconnect()` | `None` | Disconnect and clean up |
| `get_balance()` | `AccountBalance` | Account balance, equity, free margin |
| `get_positions()` | `list[Position]` | Open trading positions |
| `get_orders()` | `list[PendingOrder]` | Pending limit/stop orders |
| `get_quote(symbol)` | `Quote \| None` | Current bid/ask for a symbol |
| `search_instrument(query)` | `list[InstrumentSearchResult]` | Search instruments |
| `buy(symbol, volume, ...)` | `TradeResult` | Execute BUY order |
| `sell(symbol, volume, ...)` | `TradeResult` | Execute SELL order |
| `cancel_order(order_number)` | `CancelResult` | Cancel a queued/pending order by its order number |
| `on(event, callback)` | `None` | Register event handler |
| `subscribe_ticks(symbol)` | `None` | Subscribe to real-time ticks |

### Constructor Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `email` | Yes | — | XTB account email |
| `password` | Yes | — | XTB account password |
| `account_number` | Yes | — | XTB account number |
| `totp_secret` | No | `""` | Base32 TOTP secret for auto 2FA |
| `session_file` | No | `None` | Path to persist auth session |
| `account_type` | No | `"real"` | `"real"` or `"demo"` — selects matching `ws_url` + `account_server` preset (see Demo vs Real) |
| `ws_url` | No | resolved from `account_type` | WebSocket endpoint URL |
| `endpoint` | No | `"meta1"` | Server endpoint name |
| `account_server` | No | resolved from `account_type` | gRPC account server |
| `auto_reconnect` | No | `True` | Auto-reconnect on disconnect |

### `InstrumentRegistry`

Persistent symbol → instrument-ID cache, stored as JSON.

| Method | Returns | Description |
|--------|---------|-------------|
| `InstrumentRegistry(path)` | — | Load (or create) the JSON cache at `path` |
| `get(symbol)` | `int \| None` | Cached instrument ID for `symbol`, or `None` |
| `set(symbol, id)` | `None` | Cache one mapping and persist immediately |
| `populate(client, symbols)` | `dict[str, int]` | Download the full symbol list via `client`, match requested `symbols` (case-insensitive, dot-less fallback), persist, return new matches |
| `ids` | `dict[str, int]` | Read-only copy of the full cache |

### Demo vs Real

Set `XTB_ACCOUNT_TYPE=demo` in your environment (or pass
`account_type="demo"` to `XTBClient`) to connect to XTB's paper-trading
environment instead of live. The library picks the correct WebSocket
endpoint and account server as a pair — you never need to set both
manually.

Defaults to `real` when unset, matching previous versions.

For non-standard endpoints or account servers, `XTB_WS_URL` and
`XTB_ACCOUNT_SERVER` env vars override each field individually and win
over the `account_type` preset — see `.env.example`.

### Advanced: Direct Access

For advanced use cases, access the underlying clients:

```python
# WebSocket client (always available)
ws = client.ws

# gRPC client (available after first trade)
grpc = client.grpc_client

# Auth manager (accessor, or import the public alias)
auth = client.auth
from xtb_api import XTBAuth  # public alias for the AuthManager class
tgt = await auth.get_tgt()
```

## Architecture

```
XTBClient (public facade)
|
+-- AuthManager (shared auth session)
|   +-- CASClient (REST + Playwright browser auth)
|   +-- TGT cache (memory + disk)
|
+-- XTBWebSocketClient (quotes, positions, balance)
|   +-- Auto-reconnect with fresh service tickets
|
+-- GrpcClient (trading, lazy-initialized)
    +-- JWT auto-refresh from shared TGT
```

## How Authentication Works

1. **Login** — REST CAS attempt, falls back to Playwright browser if WAF blocks
2. **TGT** — 8-hour token, cached in memory + optional session file
3. **Service Ticket** — Derived from TGT, used for WebSocket login
4. **JWT** — 5-minute token for gRPC trading, auto-refreshed from TGT
5. **2FA** — Automatic TOTP if `totp_secret` provided

All token refresh is transparent. If a TGT expires mid-session, the full auth chain re-runs automatically.

## Disclaimer

This is an **unofficial**, community-driven project. NOT affiliated with, endorsed by, or connected to XTB S.A.

- **Use at your own risk** — trading involves financial risk
- **No warranty** — provided "as is"
- **API stability** — XTB may change their internal APIs at any time
- **Always test on demo accounts first**

## License

MIT
