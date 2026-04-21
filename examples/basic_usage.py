"""Basic usage example for xtb-api-python.

Shows: connect, confirm session reuse, read balance / positions / quote,
search instruments. Read-only — no trades placed.

Usage::

    export XTB_EMAIL=you@example.com
    export XTB_PASSWORD=...
    export XTB_ACCOUNT_NUMBER=12345678
    # Optional:
    #   XTB_TOTP_SECRET   — Base32 TOTP secret for auto-2FA
    #   XTB_ACCOUNT_TYPE  — 'real' (default) or 'demo'
    python examples/basic_usage.py
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

from xtb_api import SessionSource, XTBClient


async def main() -> None:
    client = XTBClient(
        email=os.environ["XTB_EMAIL"],
        password=os.environ["XTB_PASSWORD"],
        account_number=int(os.environ["XTB_ACCOUNT_NUMBER"]),
        totp_secret=os.environ.get("XTB_TOTP_SECRET", ""),
        session_file=Path.home() / ".xtb_session",
    )

    try:
        await client.connect()

        # Confirm whether the cached TGT was reused. If this prints CAS_LOGIN
        # or BROWSER_LOGIN on every run, XTB will email a login notification
        # every time — session caching is misconfigured.
        src = client.session_source
        if src in (SessionSource.SESSION_FILE, SessionSource.MEMORY):
            remaining = int((client.session_expires_at or 0) - time.time())
            print(f"Connected (session reused, TGT valid for another {remaining // 3600}h {(remaining % 3600) // 60}m)")
        else:
            print(f"Connected (fresh login: {src.value} — XTB will email a notification)")

        balance = await client.get_balance()
        print(f"Balance: {balance.balance:.2f} {balance.currency}  equity: {balance.equity:.2f}")

        positions = await client.get_positions()
        print(f"Open positions: {len(positions)}")
        for p in positions:
            print(f"  {p.symbol:<10} {p.side:<4} vol={p.volume}  open={p.open_price}")

        results = await client.search_instrument("Apple")
        print(f"Search 'Apple': {len(results)} hits")
        for r in results[:5]:
            print(f"  {r.symbol:<10} {r.description}")

        quote = await client.get_quote("AAPL.US")
        if quote is not None:
            print(f"AAPL.US  bid={quote.bid}  ask={quote.ask}  spread={quote.ask - quote.bid:.4f}")

    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
