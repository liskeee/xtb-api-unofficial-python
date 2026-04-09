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
