from __future__ import annotations

import math

import pytest

from mc7.addressing import DataType
from mc7.encoding import (
    Scalar,
    decode,
    decode_string,
    encode,
    encode_string,
    parse_string_header,
    size_of,
)
from mc7.errors import EncodingError


@pytest.mark.parametrize(
    ("dtype", "value", "wire"),
    [
        (DataType.BOOL, True, b"\x01"),
        (DataType.BOOL, False, b"\x00"),
        (DataType.BYTE, 0xAB, b"\xab"),
        (DataType.WORD, 0xBEEF, b"\xbe\xef"),
        (DataType.INT, -2, b"\xff\xfe"),
        (DataType.INT, 32767, b"\x7f\xff"),
        (DataType.DWORD, 0xDEADBEEF, b"\xde\xad\xbe\xef"),
        (DataType.DINT, -70000, b"\xff\xfe\xee\x90"),
        (DataType.REAL, 1.5, b"\x3f\xc0\x00\x00"),
        (DataType.REAL, -0.0, b"\x80\x00\x00\x00"),
    ],
)
def test_encode_and_decode_are_big_endian_inverses(
    dtype: DataType, value: Scalar, wire: bytes
) -> None:
    assert encode(dtype, value) == wire
    assert decode(dtype, wire) == value
    assert type(decode(dtype, wire)) is type(value)


@pytest.mark.parametrize(
    ("dtype", "size"),
    [
        (DataType.BOOL, 1),
        (DataType.BYTE, 1),
        (DataType.WORD, 2),
        (DataType.INT, 2),
        (DataType.DWORD, 4),
        (DataType.DINT, 4),
        (DataType.REAL, 4),
    ],
)
def test_size_of(dtype: DataType, size: int) -> None:
    assert size_of(dtype) == size


def test_string_has_no_fixed_size() -> None:
    with pytest.raises(EncodingError, match="no fixed size"):
        size_of(DataType.STRING)


@pytest.mark.parametrize(
    ("dtype", "value"),
    [
        (DataType.BYTE, 256),
        (DataType.BYTE, -1),
        (DataType.WORD, 65536),
        (DataType.INT, 32768),
        (DataType.INT, -32769),
        (DataType.DWORD, -1),
        (DataType.DINT, 2**31),
    ],
)
def test_out_of_range_integers_are_rejected(dtype: DataType, value: int) -> None:
    with pytest.raises(EncodingError, match="out of range"):
        encode(dtype, value)


@pytest.mark.parametrize(
    ("dtype", "value"),
    [
        (DataType.INT, 1.5),
        (DataType.INT, True),
        (DataType.WORD, "12"),
        (DataType.BOOL, 1),
        (DataType.REAL, "1.0"),
        (DataType.REAL, True),
    ],
)
def test_wrong_python_type_is_rejected(dtype: DataType, value: object) -> None:
    with pytest.raises(EncodingError):
        encode(dtype, value)  # type: ignore[arg-type]


def test_real_accepts_integers_and_rejects_overflow() -> None:
    assert encode(DataType.REAL, 2) == b"\x40\x00\x00\x00"
    with pytest.raises(EncodingError, match="32-bit REAL"):
        encode(DataType.REAL, 1e40)


def test_real_round_trips_special_values() -> None:
    assert decode(DataType.REAL, encode(DataType.REAL, math.inf)) == math.inf
    decoded = decode(DataType.REAL, encode(DataType.REAL, math.nan))
    assert isinstance(decoded, float)
    assert math.isnan(decoded)


def test_decode_requires_the_exact_size() -> None:
    with pytest.raises(EncodingError, match="needs 2 byte"):
        decode(DataType.INT, b"\x00")
    with pytest.raises(EncodingError, match="needs 4 byte"):
        decode(DataType.REAL, bytes(5))


def test_string_helpers_are_separate_from_scalar_ones() -> None:
    with pytest.raises(EncodingError, match="encode_string"):
        encode(DataType.STRING, 1)
    with pytest.raises(EncodingError, match="decode_string"):
        decode(DataType.STRING, b"\x02\x00")


def test_decode_string_uses_the_current_length() -> None:
    assert decode_string(b"\x0a\x03abcXXXXXXX") == "abc"
    assert decode_string(b"\x0a\x00") == ""
    assert decode_string(b"\x02\x02\xe6\xf8") == "æø"


def test_decode_string_rejects_truncated_payload() -> None:
    with pytest.raises(EncodingError, match="only 1 were supplied"):
        decode_string(b"\x0a\x03a")


@pytest.mark.parametrize("header", [b"\x05\x06", b"\xff\x01", b"\x05"])
def test_invalid_string_header_is_rejected(header: bytes) -> None:
    with pytest.raises(EncodingError, match="STRING header"):
        parse_string_header(header)


def test_encode_string_returns_length_byte_and_characters() -> None:
    assert encode_string("abc", 10) == b"\x03abc"
    assert encode_string("", 10) == b"\x00"
    assert encode_string("x" * 10, 10) == b"\x0a" + b"x" * 10


def test_encode_string_rejects_too_long_and_non_latin1_text() -> None:
    with pytest.raises(EncodingError, match="holds at most 3"):
        encode_string("abcd", 3)
    with pytest.raises(EncodingError, match="outside Latin-1"):
        encode_string("€", 10)
