"""High-level XTB trading client.

Provides a unified API over WebSocket and gRPC transports.

⚠️ Warning: This is an unofficial library. Use at your own risk.
Always test thoroughly on demo accounts before using with real money.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from xtb_api.grpc.client import GrpcClient
from xtb_api.types.instrument import InstrumentSearchResult, Quote
from xtb_api.types.trading import AccountBalance, Position, TradeOptions, TradeResult
from xtb_api.types.websocket import WSAuthOptions, WSClientConfig
from xtb_api.ws.ws_client import XTBWebSocketClient

ClientMode = Literal["websocket", "grpc"]


class GrpcClientConfig(BaseModel):
    """gRPC-web client configuration."""
    cdp_url: str = "http://localhost:18800"
    account_number: str = "51984891"
    account_server: str = "XS-real1"


class XTBClientConfig(BaseModel):
    """XTB client configuration."""
    mode: ClientMode
    websocket: WSClientConfig | None = None
    grpc: GrpcClientConfig | None = None
    auth: WSAuthOptions | None = None


class XTBClient:
    """High-level XTB trading client.

    Provides a unified API over WebSocket and gRPC transports.

    Features:
    - WebSocket Mode: Direct CoreAPI protocol for quotes, positions, balance
    - gRPC Mode: Native gRPC-web for trading operations
    - CAS Authentication: Full login flow (credentials → TGT → ST → session)
    - Real-time Data: Live quotes, positions, balance via push events
    - Trading: Buy/sell market orders with SL/TP
    - Instrument Search: Access to 11,888+ instruments
    """

    def __init__(self, config: XTBClientConfig) -> None:
        self._mode = config.mode
        self._ws_client: XTBWebSocketClient | None = None
        self._grpc_client: GrpcClient | None = None

        if config.mode == "grpc":
            grpc_cfg = config.grpc or GrpcClientConfig()
            self._grpc_client = GrpcClient(
                cdp_url=grpc_cfg.cdp_url,
                account_number=grpc_cfg.account_number,
                account_server=grpc_cfg.account_server,
            )
        else:
            if not config.websocket:
                raise ValueError("websocket config required for websocket mode")
            ws_config = config.websocket.model_copy()
            if config.auth:
                ws_config.auth = config.auth
            self._ws_client = XTBWebSocketClient(ws_config)

    @classmethod
    def websocket(
        cls,
        url: str,
        account_number: int,
        auth: WSAuthOptions | None = None,
        **kwargs,
    ) -> XTBClient:
        """Create a WebSocket mode client instance."""
        return cls(
            XTBClientConfig(
                mode="websocket",
                websocket=WSClientConfig(
                    url=url,
                    account_number=account_number,
                    auth=auth,
                    **kwargs,
                ),
                auth=auth,
            )
        )

    async def connect(self) -> None:
        """Connect to XTB and authenticate if needed."""
        await self._ws_client.connect()

    async def disconnect(self) -> None:
        """Disconnect from XTB."""
        await self._ws_client.disconnect_async()

    async def buy(
        self, symbol: str, volume: int, options: TradeOptions | None = None
    ) -> TradeResult:
        """Execute a BUY order.

        ⚠️ WARNING: This executes real trades. Use demo accounts for testing.
        """
        return await self._ws_client.buy(symbol, volume, options)

    async def sell(
        self, symbol: str, volume: int, options: TradeOptions | None = None
    ) -> TradeResult:
        """Execute a SELL order.

        ⚠️ WARNING: This executes real trades. Use demo accounts for testing.
        """
        return await self._ws_client.sell(symbol, volume, options)

    async def get_positions(self) -> list[Position]:
        """Get all open positions."""
        return await self._ws_client.get_positions()

    async def get_balance(self) -> AccountBalance:
        """Get account balance and equity information."""
        return await self._ws_client.get_balance()

    async def search_instrument(self, query: str) -> list[InstrumentSearchResult]:
        """Search for financial instruments."""
        return await self._ws_client.search_instrument(query)

    async def get_quote(self, symbol: str) -> Quote | None:
        """Get current quote (bid/ask prices) for a symbol."""
        return await self._ws_client.get_quote(symbol)

    async def get_account_number(self) -> int:
        """Get the account number associated with this session."""
        return self._ws_client.get_account_number()

    @classmethod
    def grpc(
        cls,
        cdp_url: str = "http://localhost:18800",
        account_number: str = "51984891",
        account_server: str = "XS-real1",
    ) -> XTBClient:
        """Create a gRPC-web mode client instance."""
        return cls(
            XTBClientConfig(
                mode="grpc",
                grpc=GrpcClientConfig(
                    cdp_url=cdp_url,
                    account_number=account_number,
                    account_server=account_server,
                ),
            )
        )

    @property
    def ws(self) -> XTBWebSocketClient | None:
        """Get the underlying WebSocket client (only in WebSocket mode)."""
        return self._ws_client

    @property
    def grpc_client(self) -> GrpcClient | None:
        """Get the underlying gRPC client (only in gRPC mode)."""
        return self._grpc_client
