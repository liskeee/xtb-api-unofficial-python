"""Live test: CAS login → 2FA → TGT → Service Ticket → WebSocket connect."""
import asyncio
import os
import sys

sys.path.insert(0, "src")

from xtb_api.auth.cas_client import CASClient
from xtb_api.types.websocket import CASLoginSuccess, CASLoginTwoFactorRequired


async def main():
    email = os.environ.get("XTB_EMAIL", "ll.lukasz.lis@gmail.com")
    password = os.environ.get("XTB_PASSWORD", "")

    if not password:
        print("Set XTB_PASSWORD env var")
        return

    cas = CASClient()

    # Step 1: Login
    print(f"[1] Logging in as {email}...")
    result = await cas.login(email, password)

    if isinstance(result, CASLoginSuccess):
        print(f"[✅] Login succeeded without 2FA! TGT: {result.tgt[:30]}...")
        tgt = result.tgt
    elif isinstance(result, CASLoginTwoFactorRequired):
        print(f"[2] 2FA required!")
        print(f"    loginTicket: {result.login_ticket[:30]}...")
        print(f"    methods: {result.methods}")
        print(f"    type: {result.two_factor_auth_type}")

        # Wait for OTP
        otp = input("\n📱 Wpisz kod SMS: ").strip()

        print(f"[3] Submitting OTP...")
        result2 = await cas.login_with_two_factor(
            login_ticket=result.login_ticket,
            code=otp,
            two_factor_auth_type=result.two_factor_auth_type,
        )

        if isinstance(result2, CASLoginSuccess):
            print(f"[✅] 2FA success! TGT: {result2.tgt[:30]}...")
            tgt = result2.tgt
        else:
            print(f"[❌] 2FA failed: {result2}")
            return
    else:
        print(f"[❌] Unexpected: {result}")
        return

    # Step 2: Service Ticket
    print(f"\n[4] Getting service ticket...")
    st_result = await cas.get_service_ticket(tgt, "xapi5")
    print(f"[✅] Service Ticket: {st_result.service_ticket[:30]}...")

    # Step 3: WebSocket connect
    print(f"\n[5] Connecting to WebSocket...")
    from xtb_api.ws.ws_client import XTBWebSocketClient
    from xtb_api.types.websocket import WSClientConfig, WSAuthOptions

    ws = XTBWebSocketClient(WSClientConfig(
        url="wss://api5reala.x-station.eu/v1/xstation",
        account_number=51984891,
        auth=WSAuthOptions(service_ticket=st_result.service_ticket),
    ))

    await ws.connect()
    print(f"[✅] WebSocket connected!")
    print(f"    Authenticated: {ws.is_authenticated}")
    if ws.account_info:
        print(f"    Accounts: {[a.accountNo for a in ws.account_info.accountList]}")
        print(f"    User: {ws.account_info.userData}")

    # Step 4: Quick test — get balance
    print(f"\n[6] Getting balance...")
    balance = await ws.get_balance()
    print(f"[✅] Balance: {balance.balance} {balance.currency}")
    print(f"    Equity: {balance.equity}")
    print(f"    Free margin: {balance.free_margin}")

    await ws.disconnect_async()
    print(f"\n[🎉] Full auth flow works!")


if __name__ == "__main__":
    asyncio.run(main())
