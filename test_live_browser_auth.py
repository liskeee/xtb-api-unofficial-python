"""Live test: Browser-based CAS login → 2FA → TGT → Service Ticket → WebSocket connect.

Usage:
    XTB_EMAIL=you@example.com XTB_PASSWORD=xxx python test_live_browser_auth.py

Launches a visible browser (headless=False) for debugging/inspection.
"""

import asyncio
import os
import sys

sys.path.insert(0, "src")

from xtb_api.auth.cas_client import CASClient
from xtb_api.types.websocket import CASLoginSuccess, CASLoginTwoFactorRequired


async def main():
    email = os.environ.get("XTB_EMAIL", "")
    password = os.environ.get("XTB_PASSWORD", "")

    if not email or not password:
        print("Set XTB_EMAIL and XTB_PASSWORD env vars")
        return

    cas = CASClient()

    # Step 1: Browser login
    print(f"[1] Launching browser login for {email}...")
    headless = os.environ.get("HEADLESS", "true").lower() != "false"
    print(f"    headless={headless}")
    result = await cas.login_with_browser(email, password, headless=headless)

    if isinstance(result, CASLoginSuccess):
        print(f"[OK] Login succeeded without 2FA! TGT: {result.tgt[:30]}...")
        tgt = result.tgt
    elif isinstance(result, CASLoginTwoFactorRequired):
        print(f"[2] 2FA required!")
        print(f"    login_ticket: {result.login_ticket}")
        print(f"    methods: {result.methods}")
        print(f"    type: {result.two_factor_auth_type}")

        otp = input("\nEnter SMS/OTP code: ").strip()

        print(f"[3] Submitting OTP via browser...")
        result2 = await cas.submit_browser_otp(otp)

        if isinstance(result2, CASLoginSuccess):
            print(f"[OK] 2FA success! TGT: {result2.tgt[:30]}...")
            tgt = result2.tgt
        else:
            print(f"[FAIL] 2FA failed: {result2}")
            return
    else:
        print(f"[FAIL] Unexpected: {result}")
        return

    # Step 2: Service Ticket
    print(f"\n[4] Getting service ticket...")
    st_result = await cas.get_service_ticket(tgt, "xapi5")
    print(f"[OK] Service Ticket: {st_result.service_ticket[:30]}...")

    # Step 3: WebSocket connect
    print(f"\n[5] Connecting to WebSocket...")
    from xtb_api.ws.ws_client import XTBWebSocketClient
    from xtb_api.types.websocket import WSClientConfig, WSAuthOptions

    account_number = int(os.environ.get("XTB_ACCOUNT", "0"))
    if not account_number:
        print("Set XTB_ACCOUNT env var (your account number)")
        return

    ws = XTBWebSocketClient(WSClientConfig(
        url="wss://api5reala.x-station.eu/v1/xstation",
        account_number=account_number,
        auth=WSAuthOptions(service_ticket=st_result.service_ticket),
    ))

    await ws.connect()
    print(f"[OK] WebSocket connected!")
    print(f"    Authenticated: {ws.is_authenticated}")
    if ws.account_info:
        print(f"    Accounts: {[a.accountNo for a in ws.account_info.accountList]}")
        print(f"    User: {ws.account_info.userData}")

    # Step 4: Get balance
    print(f"\n[6] Getting balance...")
    balance = await ws.get_balance()
    print(f"[OK] Balance: {balance.balance} {balance.currency}")
    print(f"    Equity: {balance.equity}")
    print(f"    Free margin: {balance.free_margin}")

    await ws.disconnect_async()
    print(f"\n[DONE] Full browser auth flow works!")


if __name__ == "__main__":
    asyncio.run(main())
