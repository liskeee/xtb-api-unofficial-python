"""Place a buy, cancel it if XTB queued it due to a closed market.

Demonstrates the v1.0 queued-order surface (TradeOutcome.QUEUED +
XTBClient.cancel_order). The classic trigger is placing a BUY on a US
stock outside NASDAQ hours from a non-US timezone — XTB accepts the
order but parks it until market open.

WARNING: this example places a real order. Set XTB_ACCOUNT_TYPE=demo
in your environment unless you deliberately want a live order.

Run with::

    export XTB_EXAMPLE_TRADE=1
    export XTB_ACCOUNT_TYPE=demo
    python examples/cancel_queued_order.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from xtb_api import CancelOutcome, TradeOutcome, XTBClient

SYMBOL = "AAPL.US"
VOLUME = 1


async def main() -> int:
    if os.environ.get("XTB_EXAMPLE_TRADE") != "1":
        print("Refusing to place a real order without XTB_EXAMPLE_TRADE=1 in env.")
        return 2

    client = XTBClient(
        email=os.environ["XTB_EMAIL"],
        password=os.environ["XTB_PASSWORD"],
        account_number=int(os.environ["XTB_ACCOUNT_NUMBER"]),
        totp_secret=os.environ.get("XTB_TOTP_SECRET", ""),
        session_file=Path.home() / ".xtb_session",
    )

    try:
        await client.connect()
        print(f"Placing BUY {SYMBOL} vol={VOLUME} (expecting QUEUED if market is closed)...")

        result = await client.buy(SYMBOL, volume=VOLUME)
        print(f"buy() → status={result.status.value}  order_number={result.order_number}  order_id={result.order_id}")

        if result.status is not TradeOutcome.QUEUED:
            print(f"Not queued (status={result.status.value}); exiting without cancel.")
            return 0

        assert result.order_number is not None
        print(f"Cancelling queued order {result.order_number}...")
        cancel = await client.cancel_order(result.order_number)
        print(
            f"cancel_order() → status={cancel.status.value}  "
            f"cancellation_id={cancel.cancellation_id}  error={cancel.error!r}"
        )
        return 0 if cancel.status is CancelOutcome.CANCELLED else 1

    finally:
        await client.disconnect()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
