"""Unofficial Python client for XTB xStation5 trading platform."""

from xtb_api.client import XTBClient
from xtb_api.exceptions import (
    AuthenticationError,
    CASError,
    InstrumentNotFoundError,
    ProtocolError,
    RateLimitError,
    ReconnectionError,
    TradeError,
    XTBConnectionError,
    XTBError,
    XTBTimeoutError,
)
from xtb_api.types.enums import (
    SocketStatus,
    SubscriptionEid,
    Xs6Side,
    XTBEnvironment,
)
from xtb_api.types.instrument import InstrumentSearchResult, Quote
from xtb_api.types.trading import (
    AccountBalance,
    PendingOrder,
    Position,
    TradeOptions,
    TradeResult,
)

__version__ = "0.1.0"

__all__ = [
    # Client
    "XTBClient",
    # Exceptions
    "XTBError",
    "XTBConnectionError",
    "AuthenticationError",
    "CASError",
    "ReconnectionError",
    "TradeError",
    "InstrumentNotFoundError",
    "RateLimitError",
    "XTBTimeoutError",
    "ProtocolError",
    # Data models
    "Position",
    "PendingOrder",
    "AccountBalance",
    "TradeResult",
    "TradeOptions",
    "Quote",
    "InstrumentSearchResult",
    # Enums
    "Xs6Side",
    "SocketStatus",
    "XTBEnvironment",
    "SubscriptionEid",
]
