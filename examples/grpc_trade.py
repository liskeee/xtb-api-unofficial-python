"""Example: Execute a trade via gRPC-web through Chrome CDP.

Prerequisites:
1. Chrome running with remote debugging:
   google-chrome --remote-debugging-port=18800 https://xstation5.xtb.com
2. Logged into xStation5 in Chrome
3. TGT obtained via CAS authentication (see auth examples)

Usage:
  python examples/grpc_trade.py
"""

import asyncio
import logging

from xtb_api.grpc import GrpcClient, SIDE_BUY

logging.basicConfig(level=logging.INFO)


async def main():
    # Create gRPC client pointing at Chrome CDP
    client = GrpcClient(
        cdp_url="http://localhost:18800",
        account_number="51984891",  # your XTB account number
        account_server="XS-real1",  # XS-real1, XS-demo1, etc.
    )

    # Connect — discovers xStation5 tab and Worker via CDP
    await client.connect()

    # Get JWT for trading (requires TGT from CAS auth)
    tgt = "YOUR_TGT_HERE"  # obtain via CASClient or browser cookies
    jwt = await client.get_jwt(tgt)
    print(f"JWT obtained: {jwt[:20]}...")

    # Execute a BUY order
    # instrument_id is the gRPC instrument ID (different from WebSocket quoteId)
    # Example: CIG.PL = 9438
    result = await client.buy(instrument_id=9438, volume=1)
    print(f"Trade result: success={result.success}, order_id={result.order_id}")

    if result.error:
        print(f"Error: {result.error}")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
