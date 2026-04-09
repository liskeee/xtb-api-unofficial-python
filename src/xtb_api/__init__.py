"""Unofficial Python client for XTB xStation5 trading platform."""

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

from xtb_api.auth.auth_manager import AuthManager
from xtb_api.auth.cas_client import CASClient, CASClientConfig
from xtb_api.auth.chrome_session import ChromeSession
from xtb_api.browser.browser_client import BrowserClientConfig, XTBBrowserClient
from xtb_api.client import ClientMode, XTBClient, XTBClientConfig
from xtb_api.grpc import SIDE_BUY, SIDE_SELL, GrpcClient, GrpcTradeResult
from xtb_api.types.enums import (
    RequestTradeData,
    SocketStatus,
    SubscriptionEid,
    SymbolSessionType,
    TradeCommand,
    TradeType,
    Xs6Side,
    XTBEnvironment,
)
from xtb_api.types.instrument import InstrumentSearchResult, InstrumentSymbol, Quote
from xtb_api.types.trading import (
    AccountBalance,
    INewMarketOrder,
    INewMarketOrderEvent,
    IPrice,
    ISize,
    IStopLossInput,
    ITakeProfitInput,
    IVolume,
    IXs6AuthAccount,
    PendingOrder,
    Position,
    TradeOptions,
    TradeResult,
)
from xtb_api.types.websocket import (
    CASLoginResult,
    CASLoginSuccess,
    CASLoginTwoFactorRequired,
    ClientInfo,
    CoreAPICommand,
    WSAuthOptions,
    WSClientConfig,
    WSPushEvent,
    WSPushMessage,
    WSRequest,
    WSResponse,
    XLoginResult,
)
from xtb_api.utils import (
    build_account_id,
    generate_req_id,
    parse_symbol_key,
    price_from_decimal,
    price_to_decimal,
    volume_from,
)
from xtb_api.ws.ws_client import XTBWebSocketClient

__version__ = "0.1.0"

__all__ = [
    # Client
    "XTBClient",
    "ClientMode",
    "XTBClientConfig",
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
    # Auth
    "AuthManager",
    "CASClient",
    "CASClientConfig",
    "ChromeSession",
    # WebSocket
    "XTBWebSocketClient",
    # Browser
    "XTBBrowserClient",
    "BrowserClientConfig",
    # gRPC
    "GrpcClient",
    "GrpcTradeResult",
    "SIDE_BUY",
    "SIDE_SELL",
    # Enums
    "Xs6Side",
    "TradeCommand",
    "TradeType",
    "RequestTradeData",
    "SymbolSessionType",
    "SocketStatus",
    "XTBEnvironment",
    "SubscriptionEid",
    # Instrument types
    "InstrumentSymbol",
    "Quote",
    "InstrumentSearchResult",
    # Trading types
    "IPrice",
    "IVolume",
    "ISize",
    "IStopLossInput",
    "ITakeProfitInput",
    "INewMarketOrder",
    "IXs6AuthAccount",
    "INewMarketOrderEvent",
    "TradeOptions",
    "Position",
    "PendingOrder",
    "AccountBalance",
    "TradeResult",
    # WebSocket types
    "CoreAPICommand",
    "WSRequest",
    "WSResponse",
    "WSAuthOptions",
    "WSClientConfig",
    "ClientInfo",
    "XLoginResult",
    "WSPushMessage",
    "WSPushEvent",
    "CASLoginSuccess",
    "CASLoginTwoFactorRequired",
    "CASLoginResult",
    "CASError",
    # Utils
    "price_from_decimal",
    "price_to_decimal",
    "volume_from",
    "generate_req_id",
    "build_account_id",
    "parse_symbol_key",
]
