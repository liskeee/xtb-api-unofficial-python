"""Execute a trade and handle every TradeOutcome case (v1.0 W1 surface).

Trades go through gRPC internally, but the consumer API is
``XTBClient.buy`` / ``XTBClient.sell`` — both return a typed
``TradeResult`` whose ``status`` field is a ``TradeOutcome`` enum. This
example shows the match-on-status pattern that replaces the v0.x
string-match on free-text error messages.

WARNING: this example places a real order. Use a demo account / demo
WebSocket URL (``wss://api5demoa.x-station.eu/v1/xstation``) unless you
are deliberately testing on a live account.

Set the live gate explicitly to actually submit the order::

    export XTB_EXAMPLE_TRADE=1
    python examples/grpc_trade.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from xtb_api import TradeOutcome, TradeResult, XTBClient

SYMBOL = "CIG.PL"
VOLUME = 1


def describe(result: TradeResult) -> str:
    """Render a TradeResult using every TradeOutcome case (consumer template)."""
    match result.status:
        case TradeOutcome.FILLED:
            return f"FILLED  order={result.order_id} price={result.price}"
        case TradeOutcome.REJECTED:
            return f"REJECTED  code={result.error_code}  error={result.error!r}"
        case TradeOutcome.AMBIGUOUS:
            return f"AMBIGUOUS  code={result.error_code}  — reconcile via client.get_positions() before retrying"
        case TradeOutcome.INSUFFICIENT_VOLUME:
            return f"INSUFFICIENT_VOLUME  code={result.error_code}"
        case TradeOutcome.AUTH_EXPIRED:
            return f"AUTH_EXPIRED  code={result.error_code}  error={result.error!r}"
        case TradeOutcome.RATE_LIMITED:
            return f"RATE_LIMITED  code={result.error_code}"
        case TradeOutcome.TIMEOUT:
            return f"TIMEOUT  code={result.error_code}"


async def main() -> int:
    if os.environ.get("XTB_EXAMPLE_TRADE") != "1":
        print("Refusing to place a real order without XTB_EXAMPLE_TRADE=1 in env.")
        return 2

    client = XTBClient(
        email=os.environ["XTB_EMAIL"],
        password=os.environ["XTB_PASSWORD"],
        account_number=int(os.environ["XTB_ACCOUNT_NUMBER"]),
        totp_secret=os.environ.get("XTB_TOTP_SECRET", ""),
        ws_url=os.environ.get("XTB_WS_URL", "wss://api5reala.x-station.eu/v1/xstation"),
        session_file=Path.home() / ".xtb_session",
    )

    try:
        await client.connect()
        print(f"Connected ({client.session_source.value}). Placing BUY {SYMBOL} vol={VOLUME}...")

        result = await client.buy(SYMBOL, volume=VOLUME)
        print(f"[{result.side.upper()} {result.symbol} vol={result.volume}] {describe(result)}")

        # Derived `success` property kept for brevity, but `status` is the
        # source of truth — FILLED is the only success case. AMBIGUOUS
        # means the broker may or may not have placed the order; probe
        # get_positions() before retrying.
        return 0 if result.status is TradeOutcome.FILLED else 1

    finally:
        await client.disconnect()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
