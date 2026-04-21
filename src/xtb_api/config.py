"""Env-driven configuration for XTB account type (real vs demo).

Pure resolver functions that convert the `account_type` kwarg + environment
variables into a concrete `ws_url` and `account_server` pair. Keeping these
separate from `client.py` makes them unit-testable without constructing a
client or touching the network.
"""

from __future__ import annotations

import os
from typing import Literal, TypedDict

AccountType = Literal["real", "demo"]


class _Preset(TypedDict):
    ws_url: str
    account_server: str


PRESETS: dict[AccountType, _Preset] = {
    "real": {
        "ws_url": "wss://api5reala.x-station.eu/v1/xstation",
        "account_server": "XS-real1",
    },
    "demo": {
        "ws_url": "wss://api5demoa.x-station.eu/v1/xstation",
        "account_server": "XS-demo1",
    },
}
