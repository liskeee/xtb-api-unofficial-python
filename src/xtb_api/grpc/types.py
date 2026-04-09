"""Result types for gRPC-web trading."""

from __future__ import annotations

from pydantic import BaseModel


class GrpcTradeResult(BaseModel):
    """Result of a gRPC-web trade execution."""

    success: bool
    order_id: str | None = None
    grpc_status: int = 0
    error: str | None = None
