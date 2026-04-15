"""XTBClient.buy/sell must reject volume < 1 before touching gRPC."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from xtb_api.client import XTBClient
from xtb_api.types.trading import TradeResult


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> XTBClient:
    c = XTBClient(
        email="x@y.z",
        password="p",
        account_number=1,
        session_file=None,
    )
    # Stub auth + WS + gRPC so no real I/O happens.
    c._auth = MagicMock()
    c._ws = MagicMock()
    c._ws.search_instrument = AsyncMock(return_value=[])  # unused when rejected early
    fake_grpc = MagicMock()
    fake_grpc.execute_order = AsyncMock()
    monkeypatch.setattr(c, "_ensure_grpc", lambda: fake_grpc)
    c._fake_grpc = fake_grpc  # type: ignore[attr-defined]
    return c


@pytest.mark.asyncio
async def test_buy_rejects_zero_volume(client: XTBClient) -> None:
    result = await client.buy("CIG.PL", volume=0)
    assert isinstance(result, TradeResult)
    assert result.success is False
    assert result.error is not None
    assert "insufficient_volume" in result.error
    # gRPC must not be touched
    client._fake_grpc.execute_order.assert_not_awaited()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_sell_rejects_zero_volume(client: XTBClient) -> None:
    result = await client.sell("AAPL.US", volume=0)
    assert result.success is False
    assert "insufficient_volume" in (result.error or "")
    client._fake_grpc.execute_order.assert_not_awaited()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_buy_rejects_negative_volume(client: XTBClient) -> None:
    result = await client.buy("CIG.PL", volume=-1)
    assert result.success is False
    assert "insufficient_volume" in (result.error or "")
    client._fake_grpc.execute_order.assert_not_awaited()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_buy_accepts_volume_one(client: XTBClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # Stub instrument resolution and gRPC success so the happy path completes.
    monkeypatch.setattr(
        client,
        "_resolve_instrument_id",
        AsyncMock(return_value=123),
    )
    client._fake_grpc.execute_order = AsyncMock(  # type: ignore[attr-defined]
        return_value=MagicMock(success=True, order_id="O1", error=None)
    )
    # Also stub get_positions to avoid triggering the fill-price poll (added in later task).
    client._ws.get_positions = AsyncMock(return_value=[])

    result = await client.buy("CIG.PL", volume=1)
    assert result.success is True
    client._fake_grpc.execute_order.assert_awaited()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_buy_rejects_fractional_below_half(client: XTBClient) -> None:
    """volume=0.49 rounds down to 0 and must be rejected."""
    result = await client.buy("CIG.PL", volume=0.49)  # type: ignore[arg-type]
    assert result.success is False
    assert "insufficient_volume" in (result.error or "")
    client._fake_grpc.execute_order.assert_not_awaited()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_buy_accepts_fractional_at_half(client: XTBClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """volume=0.5 rounds up to 1 and must pass validation."""
    monkeypatch.setattr(client, "_resolve_instrument_id", AsyncMock(return_value=123))
    client._fake_grpc.execute_order = AsyncMock(  # type: ignore[attr-defined]
        return_value=MagicMock(success=True, order_id="O1", error=None)
    )
    client._ws.get_positions = AsyncMock(return_value=[])

    result = await client.buy("CIG.PL", volume=0.5)  # type: ignore[arg-type]
    assert result.success is True
    client._fake_grpc.execute_order.assert_awaited()  # type: ignore[attr-defined]
