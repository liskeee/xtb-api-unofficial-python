# xtb-api-python

> ⚠️ **Unofficial** — Reverse-engineered from xStation5. Not affiliated with XTB. Use at your own risk.

Python port of the unofficial XTB xStation5 trading platform client.

## Features

- 🔌 **WebSocket Mode** — Direct CoreAPI protocol, no browser needed
- 🌐 **Browser Mode** — Controls xStation5 via Chrome DevTools Protocol (Playwright)
- 🔐 **CAS Authentication** — Full login flow (credentials → TGT → ST → session)
- 📊 **Real-time Data** — Live quotes, positions, balance via push events
- 💹 **Trading** — Buy/sell market orders with SL/TP
- 🔍 **Instrument Search** — Access to 11,888+ instruments
- 🐍 **Modern Python** — async/await, Pydantic models, type hints, Python 3.12+

## Install

```bash
pip install -e .

# With browser mode support:
pip install -e ".[browser]"

# With dev dependencies:
pip install -e ".[dev]"
```

## Quick Start

### WebSocket Mode (recommended)

```python
import asyncio
from xtb_api import XTBClient, WSAuthOptions, WSCredentials

async def main():
    client = XTBClient.websocket(
        url="wss://api5demoa.x-station.eu/v1/xstation",  # or api5reala for real
        account_number=12345678,
        auth=WSAuthOptions(
            credentials=WSCredentials(
                email="your@email.com",
                password="your-password",
            )
        ),
    )

    await client.connect()

    # Account balance
    balance = await client.get_balance()
    print(f"Balance: {balance.balance} {balance.currency}")

    # Live quote
    quote = await client.get_quote("CIG.PL")
    if quote:
        print(f"Bid: {quote.bid}, Ask: {quote.ask}")

    # Open positions
    positions = await client.get_positions()

    # Search instruments
    results = await client.search_instrument("Apple")

    # Execute trade (USE WITH CAUTION!)
    # from xtb_api import TradeOptions
    # await client.buy("AAPL.US", 1, TradeOptions(stop_loss=150))

    await client.disconnect()

asyncio.run(main())
```

### Browser Mode

Requires Chrome with xStation5 open and remote debugging enabled:

```bash
google-chrome --remote-debugging-port=9222 https://xstation5.xtb.com
```

```python
import asyncio
from xtb_api import XTBClient

async def main():
    client = XTBClient.browser("ws://127.0.0.1:9222")
    await client.connect()
    # Same API as WebSocket mode
    await client.disconnect()

asyncio.run(main())
```

### Push Events (WebSocket mode)

```python
ws = client.ws

ws.on("tick", lambda tick: print(f"{tick['symbol']}: {tick['bid']}/{tick['ask']}"))
ws.on("position", lambda pos: print(f"Position update: {pos['symbol']}"))
ws.on("authenticated", lambda info: print(f"Logged in: {info}"))
```

## API Reference

### `XTBClient`

| Method | Returns | Description |
|--------|---------|-------------|
| `connect()` | `None` | Connect and authenticate |
| `disconnect()` | `None` | Disconnect |
| `get_balance()` | `AccountBalance` | Account balance, equity, free margin |
| `get_positions()` | `list[Position]` | Open positions |
| `get_quote(symbol)` | `Quote \| None` | Current bid/ask for a symbol |
| `search_instrument(query)` | `list[InstrumentSearchResult]` | Search instruments |
| `buy(symbol, volume, opts?)` | `TradeResult` | Execute buy order |
| `sell(symbol, volume, opts?)` | `TradeResult` | Execute sell order |

### Symbol Key Format

Symbols use the format `{assetClassId}_{symbolName}_{groupId}`:
- `9_CIG.PL_6` — CI Games on Warsaw Stock Exchange
- `9_AAPL.US_6` — Apple on NASDAQ

### WebSocket URLs

| Environment | URL |
|-------------|-----|
| Real | `wss://api5reala.x-station.eu/v1/xstation` |
| Demo | `wss://api5demoa.x-station.eu/v1/xstation` |

## Architecture

```
src/xtb_api/
  auth/          CAS authentication (TGT → Service Ticket)
  browser/       Chrome DevTools Protocol client (Playwright)
  ws/            WebSocket CoreAPI client
  types/         Pydantic models & enums
  client.py      Unified high-level client
  utils.py       Price/volume conversion helpers
```

## How Authentication Works

xStation5 uses a CAS (Central Authentication Service) flow:

1. **Login** → POST credentials to CAS → receive TGT (Ticket Granting Ticket)
2. **Service Ticket** → POST TGT to CAS with `service=xapi5` → receive ST
3. **WebSocket** → Connect → `registerClientInfo` → `loginWithServiceTicket(ST)`
4. **Session** → Receive account list, start subscribing to data

## ⚠️ Disclaimer

This is an **unofficial**, community-driven project. It is NOT affiliated with, endorsed by, or connected to XTB S.A. in any way.

- **Use at your own risk** — trading involves financial risk
- **No warranty** — this software is provided "as is"
- **API stability** — XTB may change their internal APIs at any time
- **Terms of Service** — users are responsible for compliance with XTB's terms
- **Not for production** without thorough testing on a demo account first

## License

MIT
