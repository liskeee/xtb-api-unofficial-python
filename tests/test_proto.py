"""Tests for protobuf encoding/decoding functions."""

import base64
import struct

from xtb_api.grpc.proto import (
    SIDE_BUY,
    SIDE_SELL,
    build_create_access_token_request,
    build_grpc_frame,
    build_grpc_web_text_body,
    build_new_market_order,
    decode_varint,
    encode_field_bytes,
    encode_field_varint,
    encode_varint,
    extract_jwt,
    parse_grpc_frames,
    parse_proto_fields,
)
from xtb_api.types.enums import Xs6Side


class TestVarint:
    def test_encode_zero(self):
        assert encode_varint(0) == b"\x00"

    def test_encode_small(self):
        assert encode_varint(1) == b"\x01"
        assert encode_varint(127) == b"\x7f"

    def test_encode_multibyte(self):
        assert encode_varint(128) == b"\x80\x01"
        assert encode_varint(300) == b"\xac\x02"

    def test_encode_large(self):
        result = encode_varint(9438)
        # Verify roundtrip
        decoded, _ = decode_varint(result)
        assert decoded == 9438

    def test_decode_single_byte(self):
        value, pos = decode_varint(b"\x42", 0)
        assert value == 0x42
        assert pos == 1

    def test_decode_multibyte(self):
        value, pos = decode_varint(b"\xac\x02", 0)
        assert value == 300
        assert pos == 2

    def test_decode_at_offset(self):
        data = b"\xff\xac\x02"
        value, pos = decode_varint(data, 1)
        assert value == 300
        assert pos == 3

    def test_roundtrip(self):
        for n in [0, 1, 127, 128, 255, 1000, 9438, 51984891, 2**20]:
            encoded = encode_varint(n)
            decoded, _ = decode_varint(encoded)
            assert decoded == n, f"Roundtrip failed for {n}"


class TestFieldEncoding:
    def test_encode_field_varint(self):
        result = encode_field_varint(1, 9438)
        fields = parse_proto_fields(result)
        assert 1 in fields
        assert fields[1][0] == (0, 9438)

    def test_encode_field_bytes(self):
        result = encode_field_bytes(2, b"hello")
        fields = parse_proto_fields(result)
        assert 2 in fields
        assert fields[2][0] == (2, b"hello")


class TestBuildNewMarketOrder:
    def test_structure(self):
        msg = build_new_market_order(9438, 19, SIDE_BUY)
        fields = parse_proto_fields(msg)

        # Field 1: instrument_id
        assert fields[1][0] == (0, 9438)
        # Field 3: side
        assert fields[3][0] == (0, SIDE_BUY)
        # Field 2: order (nested)
        assert fields[2][0][0] == 2  # wire type length-delimited

    def test_buy_vs_sell(self):
        buy = build_new_market_order(100, 10, SIDE_BUY)
        sell = build_new_market_order(100, 10, SIDE_SELL)
        assert buy != sell

        buy_fields = parse_proto_fields(buy)
        sell_fields = parse_proto_fields(sell)
        assert buy_fields[3][0] == (0, 1)
        assert sell_fields[3][0] == (0, 2)

    def test_nested_volume(self):
        msg = build_new_market_order(9438, 19, SIDE_BUY)
        fields = parse_proto_fields(msg)
        # Parse the nested order message
        order_bytes = fields[2][0][1]
        order_fields = parse_proto_fields(order_bytes)
        # Field 2 of order = volume message
        volume_bytes = order_fields[2][0][1]
        volume_fields = parse_proto_fields(volume_bytes)
        assert volume_fields[1][0] == (0, 19)


class TestBuildCreateAccessTokenRequest:
    def test_structure(self):
        msg = build_create_access_token_request("TGT-123-abc", "51984891", "XS-real1")
        fields = parse_proto_fields(msg)

        # Field 1: TGT (bytes)
        assert fields[1][0] == (2, b"TGT-123-abc")
        # Field 2: Account (nested bytes)
        account_bytes = fields[2][0][1]
        account_fields = parse_proto_fields(account_bytes)
        assert account_fields[1][0] == (0, 51984891)
        assert account_fields[2][0] == (2, b"XS-real1")


class TestGrpcFrames:
    def test_build_frame(self):
        msg = b"\x08\x01"
        frame = build_grpc_frame(msg)
        assert frame[0] == 0  # data frame flag
        length = struct.unpack(">I", frame[1:5])[0]
        assert length == 2
        assert frame[5:] == msg

    def test_build_web_text_body(self):
        msg = b"\x08\x01"
        body = build_grpc_web_text_body(msg)
        # Should be valid base64
        decoded = base64.b64decode(body)
        assert decoded[0] == 0
        assert decoded[5:] == msg

    def test_parse_single_frame(self):
        payload = b"hello"
        frame = struct.pack(">BI", 0, len(payload)) + payload
        frames = parse_grpc_frames(frame)
        assert len(frames) == 1
        assert frames[0] == b"hello"

    def test_parse_multiple_frames(self):
        p1, p2 = b"first", b"second"
        data = struct.pack(">BI", 0, len(p1)) + p1 + struct.pack(">BI", 0x80, len(p2)) + p2
        frames = parse_grpc_frames(data)
        assert len(frames) == 2
        assert frames[0] == b"first"
        assert frames[1] == b"second"

    def test_parse_empty(self):
        assert parse_grpc_frames(b"") == []

    def test_parse_truncated(self):
        # Frame header says 100 bytes but only 5 available
        data = struct.pack(">BI", 0, 100) + b"short"
        frames = parse_grpc_frames(data)
        assert frames == []


class TestParseProtoFields:
    def test_varint_field(self):
        data = encode_field_varint(1, 42)
        fields = parse_proto_fields(data)
        assert fields[1][0] == (0, 42)

    def test_bytes_field(self):
        data = encode_field_bytes(3, b"test")
        fields = parse_proto_fields(data)
        assert fields[3][0] == (2, b"test")

    def test_multiple_fields(self):
        data = encode_field_varint(1, 100) + encode_field_bytes(2, b"abc") + encode_field_varint(3, 1)
        fields = parse_proto_fields(data)
        assert len(fields) == 3
        assert fields[1][0] == (0, 100)
        assert fields[2][0] == (2, b"abc")
        assert fields[3][0] == (0, 1)

    def test_empty_data(self):
        assert parse_proto_fields(b"") == {}


class TestSideEnumMismatch:
    """Guard test: gRPC and WebSocket side constants are intentionally different.

    Xs6Side (WebSocket): BUY=0, SELL=1
    gRPC proto:          SIDE_BUY=1, SIDE_SELL=2

    These must NOT be conflated — mixing protocols would flip trade direction.
    """

    def test_grpc_side_differs_from_ws_side(self):
        assert Xs6Side.BUY != SIDE_BUY, "Xs6Side.BUY must differ from gRPC SIDE_BUY"
        assert Xs6Side.SELL != SIDE_SELL, "Xs6Side.SELL must differ from gRPC SIDE_SELL"

    def test_grpc_side_values(self):
        assert SIDE_BUY == 1
        assert SIDE_SELL == 2

    def test_ws_side_values(self):
        assert Xs6Side.BUY == 0
        assert Xs6Side.SELL == 1


class TestExtractJwt:
    def test_extracts_jwt(self):
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJhY24iOiI1MTk4NDg5MSJ9.abc_def-123"
        data = b"\x0a\x20" + jwt.encode("latin-1") + b"\x00\x00"
        result = extract_jwt(data)
        assert result == jwt

    def test_returns_none_for_no_jwt(self):
        assert extract_jwt(b"no jwt here") is None
        assert extract_jwt(b"") is None

    def test_handles_binary_data(self):
        data = bytes(range(256))
        # Should not crash
        result = extract_jwt(data)
        assert result is None or isinstance(result, str)


class TestBuildDeleteOrdersRequest:
    """DeleteOrders request: field 1 = packed repeated uint64 (order numbers).

    Wire reference: captured in demo_market_closed.har entry 3, single cancel
    of order 872077045 produced exactly these 7 payload bytes.
    """

    def test_single_order_matches_har_bytes(self):
        from xtb_api.grpc.proto import build_delete_orders_request

        msg = build_delete_orders_request([872077045])
        # Expected: 0a (field 1, wire 2) 05 (length) f5 ad eb 9f 03 (packed varint 872077045)
        assert msg == bytes.fromhex("0a05f5adeb9f03")

    def test_multiple_orders_packed(self):
        from xtb_api.grpc.proto import build_delete_orders_request

        msg = build_delete_orders_request([1, 127, 128])
        # Packed payload: 01 (varint 1) 7f (varint 127) 80 01 (varint 128) → 4 bytes
        # Full: 0a (tag) 04 (length) 01 7f 80 01
        assert msg == bytes.fromhex("0a04017f8001")

    def test_empty_list_produces_empty_packed_field(self):
        from xtb_api.grpc.proto import build_delete_orders_request

        # field 1 with length 0 is still valid protobuf
        msg = build_delete_orders_request([])
        assert msg == bytes.fromhex("0a00")


class TestParseNewMarketOrderResponse:
    """Parse the (UUID, order_number) response shape used by NewMarketOrder
    and DeleteOrders. Reference bytes reconstructed from demo_market_closed.har.
    """

    def _build_response(self, uuid_str: str, order_number: int, trailing: bytes = b"") -> bytes:
        """Reconstruct a response frame: field1=UUID bytes, field2={field1=order_number varint, trailing}."""
        from xtb_api.grpc.proto import encode_field_bytes, encode_field_varint

        inner = encode_field_varint(1, order_number) + trailing
        return encode_field_bytes(1, uuid_str.encode("utf-8")) + encode_field_bytes(2, inner)

    def test_extracts_uuid_and_order_number(self):
        from xtb_api.grpc.proto import parse_new_market_order_response

        # Shape of demo_market_closed.har entry 1 (NewMarketOrder response, 46B)
        payload = self._build_response("a4c205ea-84c0-45aa-b0e0-34ef7ce060fe", 872077045)
        assert len(payload) == 46

        order_id, order_number = parse_new_market_order_response(payload)
        assert order_id == "a4c205ea-84c0-45aa-b0e0-34ef7ce060fe"
        assert order_number == 872077045

    def test_empty_payload_returns_none_tuple(self):
        from xtb_api.grpc.proto import parse_new_market_order_response

        assert parse_new_market_order_response(b"") == (None, None)

    def test_uuid_only_no_order_number(self):
        from xtb_api.grpc.proto import encode_field_bytes, parse_new_market_order_response

        payload = encode_field_bytes(1, b"deadbeef-dead-beef-dead-beefdeadbeef")
        order_id, order_number = parse_new_market_order_response(payload)
        assert order_id == "deadbeef-dead-beef-dead-beefdeadbeef"
        assert order_number is None

    def test_falls_back_to_regex_when_field1_is_not_utf8(self):
        from xtb_api.grpc.proto import encode_field_bytes, parse_new_market_order_response

        # Simulate a future wire change where the UUID is nested deeper — the
        # parser must still find it via a regex sweep so we don't silently
        # regress against captures where field 1 shape changes.
        hidden = b"\xff\xfe" + b"a4c205ea-84c0-45aa-b0e0-34ef7ce060fe".ljust(40, b"\x00")
        payload = encode_field_bytes(99, hidden)
        order_id, _ = parse_new_market_order_response(payload)
        assert order_id == "a4c205ea-84c0-45aa-b0e0-34ef7ce060fe"


class TestParseDeleteOrdersResponse:
    """DeleteOrders response shape matches NewMarketOrder — same helper."""

    def test_extracts_cancellation_uuid_and_order_number(self):
        from xtb_api.grpc.proto import (
            encode_field_bytes,
            encode_field_varint,
            parse_delete_orders_response,
        )

        # Shape of demo_market_closed.har entry 3 (DeleteOrders response, 48B).
        # Nested field 2 carries order_number plus an empty field 2 bytes — reproduce
        # the trailing "12 00" seen in the capture.
        inner = encode_field_varint(1, 872077045) + encode_field_bytes(2, b"")
        payload = encode_field_bytes(1, b"9e5b4600-2ecb-4e4b-a92c-e465367a80f9") + encode_field_bytes(2, inner)
        assert len(payload) == 48

        cancellation_id, order_number = parse_delete_orders_response(payload)
        assert cancellation_id == "9e5b4600-2ecb-4e4b-a92c-e465367a80f9"
        assert order_number == 872077045


class TestEndpoints:
    """Endpoint constants must match the xStation5 HAR-captured URLs."""

    def test_delete_orders_endpoint_matches_xstation5_url(self):
        from xtb_api.grpc.proto import GRPC_DELETE_ORDERS_ENDPOINT

        assert GRPC_DELETE_ORDERS_ENDPOINT == (
            "https://ipax.xtb.com/pl.xtb.ipax.pub.grpc.cashtradingneworder.v1.CashTradingNewOrderService/DeleteOrders"
        )
