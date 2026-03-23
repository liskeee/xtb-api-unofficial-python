"""Live quotes streaming example for xtb-api-python."""

import asyncio
import os

from xtb_api import XTBClient, WSAuthOptions, WSCredentials


async def main():
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
        await client.connect()
        print("✅ Connected!")

        ws = client.ws
        if not ws:
            print("❌ WebSocket client not available")
            return

        # Register tick handler
        def on_tick(tick):
            symbol = tick.get("symbol", "?")
            bid = tick.get("bid", 0)
            ask = tick.get("ask", 0)
            print(f"📊 {symbol}: Bid={bid:.4f} Ask={ask:.4f} Spread={ask-bid:.4f}")

        def on_position(pos):
            symbol = pos.get("symbol", "?")
            side = "BUY" if pos.get("side") == 1 else "SELL"
            volume = pos.get("volume", 0)
            print(f"📋 Position update: {symbol} {side} {volume}")

        ws.on("tick", on_tick)
        ws.on("position", on_position)

        # Subscribe to some symbols
        symbols = ["9_CIG.PL_6", "9_AAPL.US_6", "1_EURUSD_1"]
        for sym_key in symbols:
            try:
                await ws.subscribe_ticks(sym_key)
                print(f"✅ Subscribed to {sym_key}")
            except Exception as e:
                print(f"⚠️ Failed to subscribe to {sym_key}: {e}")

        # Stream for 60 seconds
        print("\n📡 Streaming live quotes for 60 seconds...")
        await asyncio.sleep(60)

        # Unsubscribe
        for sym_key in symbols:
            try:
                await ws.unsubscribe_ticks(sym_key)
            except Exception:
                pass

    finally:
        await client.disconnect()
        print("\n🔌 Disconnected.")


if __name__ == "__main__":
    asyncio.run(main())
