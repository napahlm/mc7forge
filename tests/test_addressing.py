from __future__ import annotations

import pytest

from mc7.addressing import Address, Area, DataType, Width, parse_address, resolve_dtype
from mc7.errors import AddressError, Mc7Error


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("I0.0", Address(Area.INPUT, 0, Width.BIT, bit=0)),
        ("Q1.7", Address(Area.OUTPUT, 1, Width.BIT, bit=7)),
        ("M10.3", Address(Area.MARKER, 10, Width.BIT, bit=3)),
        ("IB0", Address(Area.INPUT, 0, Width.BYTE)),
        ("QB4", Address(Area.OUTPUT, 4, Width.BYTE)),
        ("MW10", Address(Area.MARKER, 10, Width.WORD)),
        ("MD20", Address(Area.MARKER, 20, Width.DWORD)),
        ("DB1.DBX0.0", Address(Area.DB, 0, Width.BIT, bit=0, db_number=1)),
        ("DB1.DBB2", Address(Area.DB, 2, Width.BYTE, db_number=1)),
        ("DB10.DBW2", Address(Area.DB, 2, Width.WORD, db_number=10)),
        ("DB65535.DBD4", Address(Area.DB, 4, Width.DWORD, db_number=65535)),
    ],
)
def test_parse_valid_addresses(text: str, expected: Address) -> None:
    assert parse_address(text) == expected


@pytest.mark.parametrize(
    ("text", "canonical"),
    [
        ("  mw10 ", "MW10"),
        ("e0.1", "I0.1"),
        ("AB4", "QB4"),
        ("aw6", "QW6"),
        ("db1.dbx2.5", "DB1.DBX2.5"),
    ],
)
def test_parse_normalises_case_whitespace_and_german_mnemonics(text: str, canonical: str) -> None:
    assert str(parse_address(text)) == canonical


@pytest.mark.parametrize(
    "text",
    ["I0.0", "QB4", "MW10", "MD20", "DB1.DBX0.0", "DB1.DBB2", "DB1.DBW2", "DB1.DBD4"],
)
def test_str_round_trips(text: str) -> None:
    assert str(parse_address(text)) == text


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("", "cannot parse"),
        ("X0.0", "cannot parse"),
        ("M10", "needs a bit number"),
        ("DB1.DBX0", "bit number"),
        ("MW10.1", "must not carry a bit"),
        ("I0.8", "bit number 8"),
        ("M65536.0", "byte offset 65536"),
        ("DB0.DBW0", "DB number 0"),
        ("DB70000.DBW0", "DB number 70000"),
        ("DB1.DBW", "cannot parse"),
        ("DB1.W2", "cannot parse"),
        ("MW-1", "cannot parse"),
    ],
)
def test_parse_rejects_invalid_addresses(text: str, fragment: str) -> None:
    with pytest.raises(AddressError, match=fragment) as caught:
        parse_address(text)
    assert isinstance(caught.value, Mc7Error)
    assert isinstance(caught.value, ValueError)


def test_parse_error_names_the_offending_input() -> None:
    with pytest.raises(AddressError, match=r"'I0\.9'"):
        parse_address("I0.9")


@pytest.mark.parametrize(
    ("text", "default"),
    [
        ("M0.0", DataType.BOOL),
        ("MB0", DataType.BYTE),
        ("MW0", DataType.WORD),
        ("MD0", DataType.DWORD),
    ],
)
def test_default_type_follows_width(text: str, default: DataType) -> None:
    assert resolve_dtype(parse_address(text)) is default


@pytest.mark.parametrize(
    ("text", "dtype"),
    [
        ("MW0", DataType.INT),
        ("MD0", DataType.DINT),
        ("MD0", DataType.REAL),
        ("DB1.DBB10", DataType.STRING),
    ],
)
def test_explicit_type_matching_the_width_is_accepted(text: str, dtype: DataType) -> None:
    assert resolve_dtype(parse_address(text), dtype) is dtype


@pytest.mark.parametrize(
    ("text", "dtype"),
    [
        ("MW0", DataType.REAL),
        ("MD0", DataType.INT),
        ("M0.0", DataType.BYTE),
        ("MB0", DataType.BOOL),
        ("MW0", DataType.STRING),
    ],
)
def test_type_not_matching_the_width_is_rejected(text: str, dtype: DataType) -> None:
    with pytest.raises(AddressError, match="allowed types"):
        resolve_dtype(parse_address(text), dtype)


def test_address_rejects_inconsistent_fields() -> None:
    with pytest.raises(AddressError, match="needs a DB number"):
        Address(Area.DB, 0, Width.WORD)
    with pytest.raises(AddressError, match="does not take a DB number"):
        Address(Area.MARKER, 0, Width.WORD, db_number=1)
    with pytest.raises(AddressError, match="needs a bit number"):
        Address(Area.MARKER, 0, Width.BIT)
