"""Trading type definitions."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from xtb_api.types.enums import Xs6Side


class IPrice(BaseModel):
    """Price representation with value and scale.

    Actual price = value × 10^(-scale)
    """
    value: int
    scale: int


class IVolume(BaseModel):
    """Volume representation with value and scale."""
    value: int
    scale: int = 0


class ISize(BaseModel):
    """Trade size specification — either volume or amount."""
    volume: IVolume | None = None
    amount: float | None = None


class IStopLossInput(BaseModel):
    """Stop loss configuration."""
    price: IPrice | None = None
    trailingstopinput: dict | None = None


class ITakeProfitInput(BaseModel):
    """Take profit configuration."""
    price: IPrice | None = None


class INewMarketOrder(BaseModel):
    """Market order definition for WebSocket trading."""
    instrumentid: int
    size: ISize
    side: Xs6Side
    stoploss: IStopLossInput | None = None
    takeprofit: ITakeProfitInput | None = None


class IXs6AuthAccount(BaseModel):
    """Account information for trade events."""
    number: int
    server: str
    currency: str


class INewMarketOrderEvent(BaseModel):
    """Complete market order event for WebSocket API."""
    order: INewMarketOrder
    uiTrackingId: str | None = None
    account: IXs6AuthAccount


class TradeOptions(BaseModel):
    """Simplified trade options for high-level API."""
    stop_loss: float | None = None
    take_profit: float | None = None
    trailing_stop: float | None = None
    amount: float | None = None


class Position(BaseModel):
    """Open trading position information."""
    symbol: str
    instrument_id: int | None = None
    volume: float
    current_price: float = 0.0
    open_price: float
    stop_loss: float | None = None
    take_profit: float | None = None
    profit_percent: float = 0.0
    profit_net: float = 0.0
    swap: float | None = None
    side: Literal["buy", "sell"]
    order_id: str | None = None
    commission: float | None = None
    margin: float | None = None
    open_time: int | None = None


class AccountBalance(BaseModel):
    """Account balance and equity information."""
    balance: float
    equity: float
    free_margin: float
    currency: str
    account_number: int


class TradeResult(BaseModel):
    """Trade execution result."""
    success: bool
    order_id: str | None = None
    symbol: str
    side: Literal["buy", "sell"]
    volume: float | None = None
    price: float | None = None
    error: str | None = None
