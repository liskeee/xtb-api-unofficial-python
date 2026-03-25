"""Result types for gRPC-web trading."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GrpcTradeResult:
    """Result of a gRPC-web trade execution."""

    success: bool
    order_id: str | None = None
    grpc_status: int = 0
    error: str | None = None
