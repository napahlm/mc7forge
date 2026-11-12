"""Conversion between Python values and S7 big-endian wire bytes.

These functions are pure: they never talk to a PLC.
All failures raise :class:`~mc7.errors.EncodingError`.
"""

from __future__ import annotations

import struct

from mc7.addressing import DataType
from mc7.errors import EncodingError

Scalar = bool | int | float
Value = bool | int | float | str

STRING_HEADER_SIZE = 2
STRING_MAX_LENGTH = 254
_STRING_CODEC = "latin-1"

_FORMATS: dict[DataType, str] = {
    DataType.BYTE: ">B",
    DataType.WORD: ">H",
    DataType.INT: ">h",
    DataType.DWORD: ">I",
    DataType.DINT: ">i",
    DataType.REAL: ">f",
}

_INT_RANGES: dict[DataType, tuple[int, int]] = {
    DataType.BYTE: (0, 0xFF),
    DataType.WORD: (0, 0xFFFF),
    DataType.INT: (-0x8000, 0x7FFF),
    DataType.DWORD: (0, 0xFFFFFFFF),
    DataType.DINT: (-0x80000000, 0x7FFFFFFF),
}


def size_of(dtype: DataType) -> int:
    """Return the number of wire bytes of a fixed-size type.

    A BOOL is transported as one byte per bit.

    Raises:
        EncodingError: For STRING, whose size depends on the PLC declaration.
    """
    if dtype is DataType.BOOL:
        return 1
    if dtype is DataType.STRING:
        raise EncodingError("STRING has no fixed size; its length is stored in the PLC")
    return struct.calcsize(_FORMATS[dtype])


def encode(dtype: DataType, value: Scalar) -> bytes:
    """Encode a scalar value as S7 wire bytes.

    Raises:
        EncodingError: If the value has the wrong Python type or is out of range.
    """
    if dtype is DataType.BOOL:
        return _encode_bool(value)
    if dtype is DataType.REAL:
        return _encode_real(value)
    if dtype is DataType.STRING:
        raise EncodingError("use encode_string() for STRING values")
    return _encode_int(dtype, value)


def decode(dtype: DataType, data: bytes) -> Scalar:
    """Decode S7 wire bytes into a Python scalar.

    Raises:
        EncodingError: If ``data`` does not have exactly the size of ``dtype``.
    """
    if dtype is DataType.STRING:
        raise EncodingError("use decode_string() for STRING values")
    expected = size_of(dtype)
    if len(data) != expected:
        raise EncodingError(f"{dtype.value} needs {expected} byte(s), got {len(data)}")
    if dtype is DataType.BOOL:
        return bool(data[0] & 0x01)
    value: int | float = struct.unpack(_FORMATS[dtype], data)[0]
    return value


def _encode_bool(value: Scalar) -> bytes:
    if not isinstance(value, bool):
        raise EncodingError(f"bool needs True or False, got {value!r}")
    return b"\x01" if value else b"\x00"


def _encode_int(dtype: DataType, value: Scalar) -> bytes:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EncodingError(f"{dtype.value} needs an integer, got {value!r}")
    low, high = _INT_RANGES[dtype]
    if not low <= value <= high:
        raise EncodingError(f"{value} is out of range for {dtype.value} ({low} to {high})")
    return struct.pack(_FORMATS[dtype], value)


def _encode_real(value: Scalar) -> bytes:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise EncodingError(f"real needs a number, got {value!r}")
    try:
        return struct.pack(_FORMATS[DataType.REAL], value)
    except (OverflowError, struct.error) as exc:
        raise EncodingError(f"{value!r} does not fit a 32-bit REAL") from exc


def parse_string_header(header: bytes) -> tuple[int, int]:
    """Return ``(max_length, current_length)`` from the two header bytes of an S7 STRING.

    Raises:
        EncodingError: If the header is too short or the lengths are inconsistent,
            which usually means the offset does not point at a STRING.
    """
    if len(header) < STRING_HEADER_SIZE:
        raise EncodingError(f"a STRING header is 2 bytes, got {len(header)}")
    max_length, current_length = header[0], header[1]
    if max_length > STRING_MAX_LENGTH or current_length > max_length:
        raise EncodingError(
            f"invalid STRING header (max length {max_length}, current length {current_length}); "
            "the offset probably does not point at a STRING"
        )
    return max_length, current_length


def decode_string(data: bytes) -> str:
    """Decode a complete S7 STRING (header followed by at least the current characters)."""
    _, current_length = parse_string_header(data)
    payload = data[STRING_HEADER_SIZE : STRING_HEADER_SIZE + current_length]
    if len(payload) != current_length:
        raise EncodingError(
            f"STRING declares {current_length} character(s) but only {len(payload)} were supplied"
        )
    return payload.decode(_STRING_CODEC)


def encode_string(value: str, max_length: int) -> bytes:
    """Encode the part of an S7 STRING that follows the max-length byte.

    The result is the current-length byte followed by the characters, to be written
    one byte after the start of the STRING so the declared max length stays untouched.

    Raises:
        EncodingError: If the text is too long or not representable in Latin-1.
    """
    if not isinstance(value, str):
        raise EncodingError(f"string needs text, got {value!r}")
    try:
        payload = value.encode(_STRING_CODEC)
    except UnicodeEncodeError as exc:
        raise EncodingError(f"{value!r} contains characters outside Latin-1") from exc
    if len(payload) > max_length:
        raise EncodingError(
            f"text is {len(payload)} character(s) but the STRING holds at most {max_length}"
        )
    return bytes((len(payload),)) + payload
