"""End-to-end validation against a real XTB account.

Exercises read operations and the typed-outcome surface introduced in W1
(TradeOutcome, TradeResult, AmbiguousOutcomeError, INSUFFICIENT_VOLUME /
INSTRUMENT_NOT_FOUND error_codes) against a live account.

**This script can move real money.** It ships in two modes:

* **read-only (default)** — balance, positions, search, plus the two
  non-trading typed-failure paths (volume=0, unknown symbol). Safe to run
  on any account, any time.
* **live trade (`--live` AND env ``XTB_VALIDATE_LIVE=1``)** — also places a
  BUY then a SELL for 1 share of the cheap ticker (default: CIG.PL). Both
  gates are required so a stray flag alone can't execute trades.

Credentials come from ``.env`` in the repo root (override with
``--env-file``)::

    XTB_EMAIL=...
    XTB_PASSWORD=...
    XTB_ACCOUNT_NUMBER=...        # or XTB_USER_ID
    # optional
    XTB_TOTP_SECRET=...

Usage::

    # Read-only validation (no trades):
    uv run python scripts/validate_live.py

    # Point at a different .env:
    uv run python scripts/validate_live.py --env-file ~/some/.env

    # Live validation with buy+sell (both required):
    XTB_VALIDATE_LIVE=1 uv run python scripts/validate_live.py --live

Re-run after any library change to confirm nothing regressed on the wire.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

from xtb_api import SessionSource, XTBClient
from xtb_api.exceptions import XTBError
from xtb_api.types.trading import TradeOutcome, TradeResult

DEFAULT_SYMBOL = "CIG.PL"
UNKNOWN_SYMBOL = "DEFINITELY_NOT_A_REAL_TICKER.XX"
LIVE_ENV_GATE = "XTB_VALIDATE_LIVE"


def load_dotenv(path: Path) -> None:
    """Minimal .env parser — keep the script zero-dep."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def require(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        sys.exit(f"Missing required env var: {key} (set it in .env)")
    return val


def require_any(*keys: str) -> str:
    for k in keys:
        val = os.environ.get(k)
        if val:
            return val
    sys.exit(f"Missing required env var (need one of: {', '.join(keys)})")


def describe_session(client: XTBClient, session_file: Path) -> str:
    """Render a one-line banner describing whether the session was reused.

    The user's test is: running the validator twice within 8h must produce a
    ``session_file`` banner — if it's ``cas_login`` or ``browser_login``
    twice in a row, the remember-device path regressed and XTB will email
    on every run.
    """
    src = client.session_source
    if src is SessionSource.UNCACHED:
        return "session: UNCACHED (no TGT obtained yet)"

    expires_at = client.session_expires_at
    remaining_hm = ""
    if expires_at is not None:
        remaining = int(expires_at - time.time())
        if remaining > 0:
            remaining_hm = f" (TGT expires in {remaining // 3600}h {(remaining % 3600) // 60}m)"

    match src:
        case SessionSource.SESSION_FILE:
            return f"session: REUSED from {session_file}{remaining_hm} — no XTB login email"
        case SessionSource.MEMORY:
            return f"session: REUSED from in-memory cache{remaining_hm}"
        case SessionSource.CAS_LOGIN:
            return f"session: FRESH CAS login{remaining_hm} — XTB will email a login notification"
        case SessionSource.BROWSER_LOGIN:
            return f"session: FRESH browser login{remaining_hm} — XTB will email a login notification"
    return f"session: {src.value}{remaining_hm}"


def describe(result: TradeResult) -> str:
    """Format a TradeResult using match on TradeOutcome (W1 consumer shape)."""
    match result.status:
        case TradeOutcome.FILLED:
            headline = f"FILLED order={result.order_id} price={result.price}"
        case TradeOutcome.REJECTED:
            headline = f"REJECTED code={result.error_code} error={result.error!r}"
        case TradeOutcome.AMBIGUOUS:
            headline = f"AMBIGUOUS code={result.error_code} — reconcile via get_positions()"
        case TradeOutcome.INSUFFICIENT_VOLUME:
            headline = f"INSUFFICIENT_VOLUME code={result.error_code}"
        case TradeOutcome.AUTH_EXPIRED:
            headline = f"AUTH_EXPIRED code={result.error_code} error={result.error!r}"
        case TradeOutcome.RATE_LIMITED:
            headline = f"RATE_LIMITED code={result.error_code}"
        case TradeOutcome.TIMEOUT:
            headline = f"TIMEOUT code={result.error_code}"
    return f"[{result.side.upper()} {result.symbol} vol={result.volume}] {headline}"


async def run_readonly(client: XTBClient) -> None:
    print("\n── Read-only checks ───────────────────────────────────")

    balance = await client.get_balance()
    print(f"  balance: {balance.balance:.2f} {balance.currency}  equity: {balance.equity:.2f}")

    positions = await client.get_positions()
    print(f"  open positions: {len(positions)}")
    for p in positions:
        print(f"    {p.symbol} {p.side} vol={p.volume} open={p.open_price} id={p.order_id}")

    hits = await client.search_instrument(DEFAULT_SYMBOL)
    match = next((h for h in hits if h.symbol.upper() == DEFAULT_SYMBOL), None)
    print(f"  search({DEFAULT_SYMBOL!r}): {len(hits)} results, exact match: {match is not None}")


async def run_typed_failures(client: XTBClient) -> bool:
    """Non-destructive paths that must return typed outcomes."""
    print("\n── Typed failure paths (no money moved) ───────────────")
    ok = True

    zero = await client.buy(DEFAULT_SYMBOL, volume=0)
    print(f"  buy(volume=0): {describe(zero)}")
    if zero.status is not TradeOutcome.INSUFFICIENT_VOLUME:
        print(f"    ✗ expected INSUFFICIENT_VOLUME, got {zero.status}")
        ok = False
    if zero.error_code != "INSUFFICIENT_VOLUME":
        print(f"    ✗ expected error_code=INSUFFICIENT_VOLUME, got {zero.error_code!r}")
        ok = False

    unknown = await client.buy(UNKNOWN_SYMBOL, volume=1)
    print(f"  buy({UNKNOWN_SYMBOL!r}): {describe(unknown)}")
    if unknown.status is not TradeOutcome.REJECTED:
        print(f"    ✗ expected REJECTED, got {unknown.status}")
        ok = False

    return ok


async def run_live_trades(client: XTBClient, symbol: str) -> bool:
    """BUY 1 share → verify → SELL 1 share → verify. Real money."""
    print("\n── Live trade cycle (REAL MONEY) ──────────────────────")

    buy_res = await client.buy(symbol, volume=1)
    print(f"  {describe(buy_res)}")
    if buy_res.status is not TradeOutcome.FILLED:
        print(f"    ✗ buy did not FILL ({buy_res.status}); aborting — will NOT attempt sell")
        return False

    await asyncio.sleep(1.0)
    positions = await client.get_positions()
    matched = [p for p in positions if p.order_id == buy_res.order_id]
    print(f"  after-buy positions: {len(positions)} total, matching order_id: {len(matched)}")

    sell_res = await client.sell(symbol, volume=1)
    print(f"  {describe(sell_res)}")
    if sell_res.status is not TradeOutcome.FILLED:
        print(f"    ✗ sell did not FILL ({sell_res.status}); manual reconciliation required")
        return False

    await asyncio.sleep(1.0)
    positions = await client.get_positions()
    print(f"  after-sell positions: {len(positions)} total")

    return True


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", action="store_true", help=f"Execute buy+sell. Requires {LIVE_ENV_GATE}=1 env var.")
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL, help=f"Ticker for live trades (default: {DEFAULT_SYMBOL})")
    parser.add_argument("--env-file", type=Path, default=None, help="Path to .env file (default: <repo_root>/.env)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable INFO-level logging.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)

    repo_root = Path(__file__).resolve().parents[1]
    env_path = args.env_file.expanduser() if args.env_file else repo_root / ".env"
    load_dotenv(env_path)
    print(f"  env: {env_path}")

    live_requested = args.live
    live_gate_set = os.environ.get(LIVE_ENV_GATE) == "1"
    live_mode = live_requested and live_gate_set

    if live_requested and not live_gate_set:
        sys.exit(f"--live requires {LIVE_ENV_GATE}=1 in env (belt-and-braces safety)")

    print("═════════════════════════════════════════════════════════")
    print(" xtb-api-python — live validation")
    print(f" mode: {'LIVE (real money)' if live_mode else 'READ-ONLY'}")
    print(f" symbol: {args.symbol if live_mode else '—'}")
    print("═════════════════════════════════════════════════════════")

    email = require("XTB_EMAIL")
    password = require("XTB_PASSWORD")
    account_number = int(require_any("XTB_ACCOUNT_NUMBER", "XTB_USER_ID"))
    totp_secret = os.environ.get("XTB_TOTP_SECRET", "")

    session_file = repo_root / ".xtb_session"
    cookies_file = repo_root / ".xtb_session_cookies.json"

    print("── Session state (pre-connect) ────────────────────────")
    print(f"  session file : {session_file} ({'exists' if session_file.exists() else 'missing'})")
    print(f"  cookies file : {cookies_file} ({'exists' if cookies_file.exists() else 'missing'})")
    if not session_file.exists():
        print("  NOTE: no cached TGT — this run will perform a fresh CAS login")
        print("        (XTB will send a login notification email).")
    print()

    client = XTBClient(
        email=email,
        password=password,
        account_number=account_number,
        totp_secret=totp_secret,
        session_file=session_file,
    )

    exit_code = 0
    try:
        await client.connect()
        print(f"  connected. {describe_session(client, session_file)}")

        await run_readonly(client)

        if not await run_typed_failures(client):
            exit_code = 1

        if live_mode:
            if not await run_live_trades(client, args.symbol):
                exit_code = 1
        else:
            print("\n── Skipped live trade cycle (--live not set, or gate env missing).")

    except XTBError as e:
        print(f"\nXTBError: {type(e).__name__}: {e}")
        exit_code = 2
    finally:
        await client.disconnect()

    print("\n═════════════════════════════════════════════════════════")
    print(f" result: {'PASS' if exit_code == 0 else 'FAIL'}")
    print("═════════════════════════════════════════════════════════")
    return exit_code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
