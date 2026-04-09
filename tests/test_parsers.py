"""Tests for WebSocket response parsers."""

from xtb_api.ws.parsers import (
    parse_balance,
    parse_instruments,
    parse_orders,
    parse_positions,
    parse_quote,
)


class TestParseBalance:
    def test_parses_valid_balance(self) -> None:
        elements = [{"value": {"xtotalbalance": {
            "balance": 10000.50,
            "equity": 10500.75,
            "freeMargin": 9800.25,
        }}}]
        result = parse_balance(elements, "PLN", 12345)
        assert result.balance == 10000.50
        assert result.equity == 10500.75
        assert result.free_margin == 9800.25
        assert result.currency == "PLN"
        assert result.account_number == 12345

    def test_returns_zeros_on_empty_elements(self) -> None:
        result = parse_balance([], "USD", 99999)
        assert result.balance == 0.0
        assert result.equity == 0.0
        assert result.free_margin == 0.0

    def test_returns_zeros_on_missing_balance_data(self) -> None:
        elements = [{"value": {}}]
        result = parse_balance(elements, "EUR", 11111)
        assert result.balance == 0.0

    def test_handles_none_element(self) -> None:
        elements = [None]
        result = parse_balance(elements, "PLN", 1)
        assert result.balance == 0.0


class TestParsePositions:
    def test_parses_buy_position(self) -> None:
        elements = [{"value": {"xcfdtrade": {
            "symbol": "EURUSD",
            "idQuote": 9438,
            "volume": 1.0,
            "openPrice": 1.0850,
            "sl": 1.0800,
            "tp": 1.0900,
            "swap": -0.5,
            "side": 0,
            "positionId": "12345",
            "commission": -2.0,
            "margin": 100.0,
            "openTime": 1700000000,
        }}}]
        positions = parse_positions(elements)
        assert len(positions) == 1
        pos = positions[0]
        assert pos.symbol == "EURUSD"
        assert pos.instrument_id == 9438
        assert pos.side == "buy"
        assert pos.stop_loss == 1.0800
        assert pos.take_profit == 1.0900
        assert pos.order_id == "12345"

    def test_parses_sell_position(self) -> None:
        elements = [{"value": {"xcfdtrade": {
            "symbol": "CIG.PL",
            "volume": 100,
            "openPrice": 2.50,
            "side": 1,
            "sl": 0,
            "tp": 0,
        }}}]
        positions = parse_positions(elements)
        assert len(positions) == 1
        assert positions[0].side == "sell"
        assert positions[0].stop_loss is None
        assert positions[0].take_profit is None

    def test_skips_elements_without_xcfdtrade(self) -> None:
        elements = [
            {"value": {"xcfdtrade": {"symbol": "A", "side": 0, "volume": 1}}},
            {"value": {}},
            {"value": {"other": "data"}},
        ]
        assert len(parse_positions(elements)) == 1

    def test_empty_elements(self) -> None:
        assert parse_positions([]) == []


class TestParseOrders:
    def test_parses_pending_order(self) -> None:
        elements = [{"value": {"xcfdtrade": {
            "symbol": "BTCUSD",
            "idQuote": 5001,
            "volume": 0.1,
            "openPrice": 60000.0,
            "sl": 59000,
            "tp": 62000,
            "side": 0,
            "positionId": "ORD-999",
            "orderType": "LIMIT",
            "expiration": 1700100000,
            "openTime": 1700000000,
        }}}]
        orders = parse_orders(elements)
        assert len(orders) == 1
        order = orders[0]
        assert order.symbol == "BTCUSD"
        assert order.order_type == "LIMIT"
        assert order.price == 60000.0

    def test_empty_elements(self) -> None:
        assert parse_orders([]) == []


class TestParseInstruments:
    def test_parses_instrument(self) -> None:
        elements = [{"value": {"xcfdsymbol": {
            "name": "EURUSD",
            "instrumentId": 9438,
            "description": "Euro vs US Dollar",
            "idAssetClass": "9",
            "groupId": "6",
        }}}]
        instruments = parse_instruments(elements)
        assert len(instruments) == 1
        inst = instruments[0]
        assert inst.symbol == "EURUSD"
        assert inst.instrument_id == 9438
        assert inst.description == "Euro vs US Dollar"
        assert inst.symbol_key == "9_EURUSD_6"

    def test_falls_back_to_quote_id(self) -> None:
        elements = [{"value": {"xcfdsymbol": {
            "name": "TEST",
            "quoteId": 1234,
            "description": "Test",
            "idAssetClass": "1",
        }}}]
        instruments = parse_instruments(elements)
        assert instruments[0].instrument_id == 1234

    def test_empty_elements(self) -> None:
        assert parse_instruments([]) == []


class TestParseQuote:
    def test_parses_valid_quote(self) -> None:
        elements = [{"value": {"xcfdtick": {
            "symbol": "EURUSD",
            "ask": 1.0855,
            "bid": 1.0850,
            "high": 1.0900,
            "low": 1.0800,
            "timestamp": 1700000000,
        }}}]
        quote = parse_quote(elements, "EURUSD")
        assert quote is not None
        assert quote.ask == 1.0855
        assert quote.bid == 1.0850
        assert quote.spread == pytest.approx(0.0005)
        assert quote.high == 1.0900
        assert quote.time == 1700000000

    def test_returns_none_on_empty(self) -> None:
        assert parse_quote([], "X") is None

    def test_returns_none_on_no_tick(self) -> None:
        elements = [{"value": {}}]
        assert parse_quote(elements, "X") is None

    def test_uses_fallback_symbol(self) -> None:
        elements = [{"value": {"xcfdtick": {"ask": 1.0, "bid": 0.9}}}]
        quote = parse_quote(elements, "FALLBACK")
        assert quote is not None
        assert quote.symbol == "FALLBACK"


# Need pytest for approx
import pytest  # noqa: E402
