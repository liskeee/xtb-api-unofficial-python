# xtb-api-python

> **Unofficial** — Reverse-engineered from xStation5. Not affiliated with XTB. Use at your own risk.

Python client for the XTB xStation5 trading platform. Dead-simple API that handles all authentication, token refresh, and transport selection transparently.

## Features

- **Single Client** — One `XTBClient` handles everything, no mode selection needed
- **Auto Auth** — Full CAS login flow with automatic TGT/JWT refresh
- **2FA Support** — Automatic TOTP handling when `totp_secret` is provided
- **Real-time Data** — Live quotes, positions, balance via WebSocket push events
- **Trading** — Buy/sell market orders with SL/TP via gRPC-web
- **11,888+ Instruments** — Full symbol search with caching
- **Modern Python** — async/await, Pydantic models, strict typing, Python 3.12+

## Install

```bash
pip install xtb-api-python

# With 2FA auto-handling:
pip install "xtb-api-python[totp]"

# Development:
pip install -e ".[dev]"

# Install Playwright browser (required for auth):
playwright install chromium
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
| `ws_url` | No | Real server | WebSocket endpoint URL |
| `endpoint` | No | `"meta1"` | Server endpoint name |
| `account_server` | No | `"XS-real1"` | gRPC account server |
| `auto_reconnect` | No | `True` | Auto-reconnect on disconnect |

### WebSocket URLs

| Environment | URL |
|-------------|-----|
| Real | `wss://api5reala.x-station.eu/v1/xstation` (default) |
| Demo | `wss://api5demoa.x-station.eu/v1/xstation` |

### Advanced: Direct Access

For advanced use cases, access the underlying clients:

```python
# WebSocket client (always available)
ws = client.ws

# gRPC client (available after first trade)
grpc = client.grpc_client

# Auth manager
auth = client.auth
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
