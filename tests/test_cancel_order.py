"""XTBClient.cancel_order wraps GrpcClient.cancel_orders for a single order."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from xtb_api.client import XTBClient
from xtb_api.grpc.types import GrpcCancelResult
from xtb_api.types.trading import CancelOutcome


def _make_client(monkeypatch: pytest.MonkeyPatch) -> XTBClient:
    c = XTBClient(email="x@y.z", password="p", account_number=1, session_file=None)
    c._auth = MagicMock()
    c._ws = MagicMock()
    fake_grpc = MagicMock()
    fake_grpc.cancel_orders = AsyncMock()
    monkeypatch.setattr(c, "_ensure_grpc", lambda: fake_grpc)
    c._fake_grpc = fake_grpc  # type: ignore[attr-defined]
    return c


@pytest.mark.asyncio
async def test_cancel_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client(monkeypatch)
    client._fake_grpc.cancel_orders = AsyncMock(  # type: ignore[attr-defined]
        return_value=[
            GrpcCancelResult(
                success=True,
                order_number=872077045,
                cancellation_id="9e5b4600-2ecb-4e4b-a92c-e465367a80f9",
                grpc_status=0,
            )
        ]
    )

    result = await client.cancel_order(872077045)

    assert result.status is CancelOutcome.CANCELLED
    assert result.order_number == 872077045
    assert result.cancellation_id == "9e5b4600-2ecb-4e4b-a92c-e465367a80f9"
    assert result.success is True
    client._fake_grpc.cancel_orders.assert_awaited_once_with([872077045])  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_cancel_rejected_order_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _make_client(monkeypatch)
    client._fake_grpc.cancel_orders = AsyncMock(  # type: ignore[attr-defined]
        return_value=[
            GrpcCancelResult(
                success=False,
                order_number=42,
                grpc_status=5,
                error="order not found",
            )
        ]
    )

    result = await client.cancel_order(42)

    assert result.status is CancelOutcome.REJECTED
    assert result.order_number == 42
    assert result.cancellation_id is None
    assert result.error == "order not found"
    assert result.success is False


@pytest.mark.asyncio
async def test_cancel_rbac_denied_marks_rejected_with_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _make_client(monkeypatch)
    client._fake_grpc.cancel_orders = AsyncMock(  # type: ignore[attr-defined]
        return_value=[
            GrpcCancelResult(
                success=False,
                order_number=42,
                grpc_status=7,
                error="rbac denied",
            )
        ]
    )

    result = await client.cancel_order(42)

    assert result.status is CancelOutcome.REJECTED
    assert result.error_code == "RBAC_DENIED"


@pytest.mark.asyncio
async def test_cancel_network_failure_is_ambiguous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _make_client(monkeypatch)
    # GrpcClient.cancel_orders returns success=False with a network-error
    # string (grpc_status=0 since no trailer was ever observed).
    client._fake_grpc.cancel_orders = AsyncMock(  # type: ignore[attr-defined]
        return_value=[
            GrpcCancelResult(
                success=False,
                order_number=42,
                grpc_status=0,
                error="ConnectError: boom",
            )
        ]
    )

    result = await client.cancel_order(42)

    assert result.status is CancelOutcome.AMBIGUOUS
    assert result.error_code == "AMBIGUOUS_NO_RESPONSE"
    assert result.error is not None and "boom" in result.error
