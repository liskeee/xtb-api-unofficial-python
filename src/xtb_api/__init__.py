"""Unofficial Python client for XTB xStation5 trading platform."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

from xtb_api.auth.auth_manager import AuthManager as XTBAuth
from xtb_api.client import XTBClient
from xtb_api.instruments import InstrumentRegistry
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

try:
    __version__ = _pkg_version("xtb-api-python")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0+unknown"

__all__ = [
    # Client
    "XTBClient",
    "XTBAuth",
    "InstrumentRegistry",
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
