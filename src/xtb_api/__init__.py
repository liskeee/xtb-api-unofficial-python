"""Unofficial Python client for XTB xStation5 trading platform."""

from xtb_api.client import XTBClient, ClientMode, XTBClientConfig
from xtb_api.auth.cas_client import CASClient, CASClientConfig
from xtb_api.ws.ws_client import XTBWebSocketClient
from xtb_api.browser.browser_client import XTBBrowserClient, BrowserClientConfig
from xtb_api.grpc import GrpcClient, GrpcTradeResult, SIDE_BUY, SIDE_SELL
from xtb_api.types.enums import (
    Xs6Side,
    TradeCommand,
    TradeType,
    RequestTradeData,
    SymbolSessionType,
    SocketStatus,
    XTBEnvironment,
    SubscriptionEid,
)
from xtb_api.types.instrument import InstrumentSymbol, Quote, InstrumentSearchResult
from xtb_api.types.trading import (
    IPrice,
    IVolume,
    ISize,
    IStopLossInput,
    ITakeProfitInput,
    INewMarketOrder,
    IXs6AuthAccount,
    INewMarketOrderEvent,
    TradeOptions,
    Position,
    AccountBalance,
    TradeResult,
)
from xtb_api.types.websocket import (
    CoreAPICommand,
    WSRequest,
    WSResponse,
    WSAuthOptions,
    WSClientConfig,
    ClientInfo,
    XLoginResult,
    WSPushMessage,
    WSPushEvent,
    CASLoginSuccess,
    CASLoginTwoFactorRequired,
    CASLoginResult,
    CASError,
)
from xtb_api.utils import (
    price_from_decimal,
    price_to_decimal,
    volume_from,
    generate_req_id,
    build_account_id,
    parse_symbol_key,
)

__version__ = "0.1.0"

__all__ = [
    # Client
    "XTBClient",
    "ClientMode",
    "XTBClientConfig",
    # Auth
    "CASClient",
    "CASClientConfig",
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
