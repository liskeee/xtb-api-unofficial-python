"""XTBClient trade methods return TradeResult with a typed TradeOutcome (F16)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from xtb_api.client import XTBClient
from xtb_api.exceptions import AmbiguousOutcomeError
from xtb_api.types.trading import TradeOutcome, TradeResult


def _make_client(monkeypatch: pytest.MonkeyPatch) -> XTBClient:
    c = XTBClient(email="x@y.z", password="p", account_number=1, session_file=None)
    c._auth = MagicMock()
    c._ws = MagicMock()
    c._ws.get_positions = AsyncMock(return_value=[])
    fake_grpc = MagicMock()
    fake_grpc.execute_order = AsyncMock()
    fake_grpc.invalidate_jwt = MagicMock()
    monkeypatch.setattr(c, "_ensure_grpc", lambda: fake_grpc)
    monkeypatch.setattr(c, "_resolve_instrument_id", AsyncMock(return_value=42))
    c._fake_grpc = fake_grpc  # type: ignore[attr-defined]
    return c


@pytest.mark.asyncio
async def test_filled_trade_returns_outcome_filled(monkeypatch: pytest.MonkeyPatch) -> None:
    from xtb_api.types.trading import Position

    client = _make_client(monkeypatch)
    client._fake_grpc.execute_order = AsyncMock(  # type: ignore[attr-defined]
        return_value=MagicMock(success=True, order_id="O1", error=None, grpc_status=0)
    )
    pos = Position(symbol="CIG.PL", volume=1, open_price=10.0, current_price=10.0, side="buy", order_id="O1")
    client._ws.get_positions = AsyncMock(return_value=[pos])

    result = await client.buy("CIG.PL", volume=1)

    assert isinstance(result, TradeResult)
    assert result.status is TradeOutcome.FILLED
    assert result.order_id == "O1"
    assert result.error_code is None


@pytest.mark.asyncio
async def test_ambiguous_grpc_response_returns_outcome_ambiguous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _make_client(monkeypatch)
    client._fake_grpc.execute_order = AsyncMock(  # type: ignore[attr-defined]
        side_effect=AmbiguousOutcomeError("empty response")
    )

    result = await client.buy("CIG.PL", volume=1)

    assert result.status is TradeOutcome.AMBIGUOUS
    assert result.order_id is None
    assert result.error_code == "AMBIGUOUS_NO_RESPONSE"
    assert result.error is not None


@pytest.mark.asyncio
async def test_insufficient_volume_returns_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client(monkeypatch)

    result = await client.buy("CIG.PL", volume=0)

    assert result.status is TradeOutcome.INSUFFICIENT_VOLUME
    assert result.error_code == "INSUFFICIENT_VOLUME"
    client._fake_grpc.execute_order.assert_not_awaited()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_generic_rejection_returns_outcome_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _make_client(monkeypatch)
    client._fake_grpc.execute_order = AsyncMock(  # type: ignore[attr-defined]
        return_value=MagicMock(
            success=False,
            order_id=None,
            error="gRPC order rejected: NO_FUNDS",
            grpc_status=9,
        )
    )

    result = await client.buy("CIG.PL", volume=1)

    assert result.status is TradeOutcome.REJECTED
    assert "NO_FUNDS" in (result.error or "")
