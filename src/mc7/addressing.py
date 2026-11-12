"""Parsing and validation of S7 absolute addresses.

Supported forms (case-insensitive, IEC mnemonics with the German ones as aliases):

==================  ==========================================
``I0.0`` ``E0.0``   input bit
``QB4`` ``AB4``     output byte
``MW10``            bit memory word (2 bytes)
``MD20``            bit memory double word (4 bytes)
``DB1.DBX0.0``      data block bit
``DB1.DBB2``        data block byte
``DB1.DBW2``        data block word
``DB1.DBD4``        data block double word
==================  ==========================================

The address only fixes the *width* of the operand.
How the bytes are interpreted is chosen separately with a :class:`DataType`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from mc7.errors import AddressError

MAX_BYTE_OFFSET = 65535
MAX_DB_NUMBER = 65535


class Area(Enum):
    """Memory areas reachable through this package."""

    INPUT = "I"
    OUTPUT = "Q"
    MARKER = "M"
    DB = "DB"


class Width(Enum):
    """Operand width; the value is the size letter used in address strings."""

    BIT = "X"
    BYTE = "B"
    WORD = "W"
    DWORD = "D"


class DataType(Enum):
    """Elementary S7 data types supported by the typed helpers."""

    BOOL = "bool"
    BYTE = "byte"
    WORD = "word"
    INT = "int"
    DWORD = "dword"
    DINT = "dint"
    REAL = "real"
    STRING = "string"


_DEFAULT_TYPE: dict[Width, DataType] = {
    Width.BIT: DataType.BOOL,
    Width.BYTE: DataType.BYTE,
    Width.WORD: DataType.WORD,
    Width.DWORD: DataType.DWORD,
}

_ALLOWED_TYPES: dict[Width, tuple[DataType, ...]] = {
    Width.BIT: (DataType.BOOL,),
    Width.BYTE: (DataType.BYTE, DataType.STRING),
    Width.WORD: (DataType.WORD, DataType.INT),
    Width.DWORD: (DataType.DWORD, DataType.DINT, DataType.REAL),
}

_AREA_ALIASES: dict[str, Area] = {
    "I": Area.INPUT,
    "E": Area.INPUT,
    "Q": Area.OUTPUT,
    "A": Area.OUTPUT,
    "M": Area.MARKER,
}

_PROCESS_RE = re.compile(r"(?P<area>[IEQAM])(?P<width>[BWD])?(?P<byte>\d+)(?:\.(?P<bit>\d+))?")
_DB_RE = re.compile(r"DB(?P<db>\d+)\.DB(?P<width>[XBWD])(?P<byte>\d+)(?:\.(?P<bit>\d+))?")

_EXAMPLES = "I0.0, QB4, MW10, MD20, DB1.DBX0.0, DB1.DBB2, DB1.DBW2, DB1.DBD4"


@dataclass(frozen=True, slots=True)
class Address:
    """A validated absolute address.

    Attributes:
        area: Memory area.
        byte: Byte offset inside the area (or inside the DB).
        width: Operand width.
        bit: Bit number 0-7 for :attr:`Width.BIT`, otherwise ``None``.
        db_number: Data block number for :attr:`Area.DB`, otherwise ``None``.
    """

    area: Area
    byte: int
    width: Width
    bit: int | None = None
    db_number: int | None = None

    def __post_init__(self) -> None:
        """Reject field combinations that do not describe a real operand."""
        validate_byte_offset(self.byte)
        if self.width is Width.BIT:
            if self.bit is None:
                raise AddressError("a bit address needs a bit number (0-7)")
            validate_bit(self.bit)
        elif self.bit is not None:
            raise AddressError(f"a {self.width.name} address must not carry a bit number")
        if self.area is Area.DB:
            if self.db_number is None:
                raise AddressError("a DB address needs a DB number")
            validate_db_number(self.db_number)
        elif self.db_number is not None:
            raise AddressError(f"area {self.area.value} does not take a DB number")

    def __str__(self) -> str:
        """Return the canonical IEC spelling, for example ``DB1.DBW2`` or ``I0.0``."""
        suffix = f"{self.byte}.{self.bit}" if self.width is Width.BIT else str(self.byte)
        if self.area is Area.DB:
            return f"DB{self.db_number}.DB{self.width.value}{suffix}"
        width = "" if self.width is Width.BIT else self.width.value
        return f"{self.area.value}{width}{suffix}"


def validate_byte_offset(offset: int) -> None:
    """Raise :class:`AddressError` unless ``offset`` is a usable byte offset."""
    if not 0 <= offset <= MAX_BYTE_OFFSET:
        raise AddressError(f"byte offset {offset} is out of range 0-{MAX_BYTE_OFFSET}")


def validate_bit(bit: int) -> None:
    """Raise :class:`AddressError` unless ``bit`` is in 0-7."""
    if not 0 <= bit <= 7:
        raise AddressError(f"bit number {bit} is out of range 0-7")


def validate_db_number(db_number: int) -> None:
    """Raise :class:`AddressError` unless ``db_number`` is a valid DB number."""
    if not 1 <= db_number <= MAX_DB_NUMBER:
        raise AddressError(f"DB number {db_number} is out of range 1-{MAX_DB_NUMBER}")


def parse_address(text: str) -> Address:
    """Parse an absolute address such as ``MW10`` or ``DB1.DBX0.0``.

    Raises:
        AddressError: If the text is not a supported address or a field is out of range.
    """
    cleaned = text.strip().upper()
    if match := _DB_RE.fullmatch(cleaned):
        return _build(text, Area.DB, match, db_number=int(match["db"]))
    if match := _PROCESS_RE.fullmatch(cleaned):
        return _build(text, _AREA_ALIASES[match["area"]], match, db_number=None)
    raise AddressError(f"cannot parse address {text!r}; expected a form like {_EXAMPLES}")


def _build(text: str, area: Area, match: re.Match[str], *, db_number: int | None) -> Address:
    """Turn a regex match into an :class:`Address`, adding the input text to any error."""
    width = Width(match["width"]) if match["width"] else Width.BIT
    bit = int(match["bit"]) if match["bit"] is not None else None
    try:
        return Address(area, int(match["byte"]), width, bit, db_number)
    except AddressError as exc:
        raise AddressError(f"invalid address {text!r}: {exc}") from exc


def resolve_dtype(address: Address, dtype: DataType | None = None) -> DataType:
    """Return the data type to use for ``address``.

    With ``dtype=None`` the natural unsigned type of the width is used
    (BOOL, BYTE, WORD, DWORD).

    Raises:
        AddressError: If ``dtype`` does not fit the width of the address.
    """
    if dtype is None:
        return _DEFAULT_TYPE[address.width]
    allowed = _ALLOWED_TYPES[address.width]
    if dtype in allowed:
        return dtype
    names = ", ".join(t.value for t in allowed)
    raise AddressError(
        f"type {dtype.value} does not fit {address} ({address.width.name} operand); "
        f"allowed types: {names}"
    )
