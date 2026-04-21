"""Live quotes streaming example for xtb-api-python.

Subscribes to tick data for a handful of symbols via the WebSocket push
channel and prints each update for 60 seconds.

Symbols are passed as plain ticker names — ``XTBClient.subscribe_ticks``
resolves them to the internal symbol-key format automatically.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from pathlib import Path
from typing import Any

from xtb_api import XTBClient

SYMBOLS = ["CIG.PL", "AAPL.US", "EURUSD"]
STREAM_SECONDS = 60


async def main() -> None:
    client = XTBClient(
        email=os.environ["XTB_EMAIL"],
        password=os.environ["XTB_PASSWORD"],
        account_number=int(os.environ["XTB_ACCOUNT_NUMBER"]),
        totp_secret=os.environ.get("XTB_TOTP_SECRET", ""),
        session_file=Path.home() / ".xtb_session",
    )

    def on_tick(tick: dict[str, Any]) -> None:
        symbol = tick.get("symbol", "?")
        bid = tick.get("bid", 0.0)
        ask = tick.get("ask", 0.0)
        print(f"tick  {symbol:<10} bid={bid:<10.4f} ask={ask:<10.4f} spread={ask - bid:.4f}")

    def on_position(pos: dict[str, Any]) -> None:
        side = "BUY" if pos.get("side") == 1 else "SELL"
        print(f"pos   {pos.get('symbol', '?'):<10} {side} vol={pos.get('volume', 0)}")

    client.on("tick", on_tick)
    client.on("position", on_position)

    try:
        await client.connect()
        print(f"Connected ({client.session_source.value}). Subscribing to {len(SYMBOLS)} symbols.")

        for symbol in SYMBOLS:
            try:
                await client.subscribe_ticks(symbol)
                print(f"  subscribed: {symbol}")
            except Exception as exc:
                print(f"  subscribe failed for {symbol}: {exc}")

        print(f"Streaming for {STREAM_SECONDS}s — Ctrl-C to stop early.")
        await asyncio.sleep(STREAM_SECONDS)

        for symbol in SYMBOLS:
            with contextlib.suppress(Exception):
                await client.unsubscribe_ticks(symbol)

    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
