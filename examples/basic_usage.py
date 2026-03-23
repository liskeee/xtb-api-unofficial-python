"""Basic usage example for xtb-api-python."""

import asyncio
import os

from xtb_api import XTBClient, WSAuthOptions, WSCredentials


async def main():
    # Create client with WebSocket mode
    client = XTBClient.websocket(
        url=os.getenv("XTB_WS_URL", "wss://api5demoa.x-station.eu/v1/xstation"),
        account_number=int(os.getenv("XTB_ACCOUNT_NUMBER", "12345678")),
        auth=WSAuthOptions(
            credentials=WSCredentials(
                email=os.getenv("XTB_EMAIL", "your@email.com"),
                password=os.getenv("XTB_PASSWORD", "your-password"),
            )
        ),
    )

    try:
        # Connect and authenticate
        await client.connect()
        print("✅ Connected and authenticated!")

        # Get account info
        account_number = await client.get_account_number()
        print(f"📊 Account: #{account_number}")

        # Get balance
        balance = await client.get_balance()
        print(f"💰 Balance: {balance.balance:.2f} {balance.currency}")
        print(f"📈 Equity: {balance.equity:.2f} {balance.currency}")
        print(f"🆓 Free Margin: {balance.free_margin:.2f} {balance.currency}")

        # Search instruments
        results = await client.search_instrument("Apple")
        print(f"\n🔍 Search 'Apple' — {len(results)} results:")
        for r in results[:5]:
            print(f"  {r.symbol} — {r.description} (key: {r.symbol_key})")

        # Get quote
        quote = await client.get_quote("AAPL.US")
        if quote:
            print(f"\n📊 AAPL.US — Bid: {quote.bid}, Ask: {quote.ask}, Spread: {quote.spread:.4f}")

        # Get open positions
        positions = await client.get_positions()
        print(f"\n📋 Open positions: {len(positions)}")
        for pos in positions:
            print(f"  {pos.symbol} {pos.side.upper()} {pos.volume} @ {pos.open_price}")

        # ⚠️ Execute trade (UNCOMMENT WITH CAUTION — use demo account!)
        # from xtb_api import TradeOptions
        # result = await client.buy("CIG.PL", 100, TradeOptions(stop_loss=2.40, take_profit=2.80))
        # print(f"Trade: {'✅' if result.success else '❌'} {result}")

    finally:
        await client.disconnect()
        print("\n🔌 Disconnected.")


if __name__ == "__main__":
    asyncio.run(main())
