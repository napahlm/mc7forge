"""The MC7 opcode table, kept as data.

Every row describes one instruction form: which bits of the first two bytes
are fixed, the mnemonic, how the operand is laid out and the encoded length.
The disassembler is driven by this table and by nothing else; the encoder of a
later stage will use the same rows.

Grounding rules
---------------
* A row exists only if vectors of the rz-libmc7 corpus exercise it. Bytes no
  row matches are reported as unknown opcodes, never guessed.
* Every row was cross-checked against ``MC7toAWL.cs`` of
  DotNetSiemensPLCToolBoxLibrary and carries the result in :attr:`OpcodeRow.status`
  and the place in :attr:`OpcodeRow.source`.
* Expected texts follow the corpus literally, including spellings that differ
  from STEP 7. Those rows are marked, see :class:`Status`.

Scope
-----
:attr:`Scope.MINIMAL` is the minimal subset: ``A AN O ON = S R`` on directly
addressed bits and ``L T`` on directly addressed bytes, words and double words
and on typed constants. :attr:`Scope.REFERENCE_BLOCK` holds the few extra rows
needed to decode the reference block ``cm7.bin`` completely: edge detection
``FP FN``, the counter operations ``CU CD LC`` and ``BE``.

Mnemonics and operand areas are stored in international (English) spelling.
:data:`GERMAN_MNEMONICS` and :data:`GERMAN_AREAS` give the German (SIMATIC)
spelling, taken from ``Mnemonic.cs`` of the same C# library.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Mnemonics(Enum):
    """Spelling of operations and operand areas."""

    EN = "en"
    """International: ``A I 0.0``, ``= Q 0.0``, ``CU C 1``."""
    DE = "de"
    """German (SIMATIC): ``U E 0.0``, ``= A 0.0``, ``ZV Z 1``."""


class Operand(Enum):
    """How the operand of an instruction form is laid out and rendered."""

    NONE = "none"
    """No operand."""
    BIT_LONG = "area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3"
    BIT_SHORT_8 = "area byte.bit: bit in byte 0 bits 0-2, byte address in byte 1"
    BIT_SHORT_7 = "area byte.bit: bit in byte 0 bits 0-2, byte address in byte 1 bits 0-6"
    ADDRESS_8 = "area address: address in byte 1"
    ADDRESS_7 = "area address: address in byte 1 bits 0-6"
    ADDRESS_16 = "area address: address in bytes 2-3"
    BYTE_HEX = "B#16#n: byte 1"
    BINARY_16 = "2#bits: bytes 2-3"
    INT_16 = "signed integer: bytes 2-3"
    CHARS_16 = "'characters': bytes 2-3"
    BYTES_16 = "B#(a, b): bytes 2-3"
    HEX_16 = "W#16#hex: bytes 2-3"
    COUNTER_BCD = "C#count: three BCD digits in bytes 2-3"
    DATE = "D#year-month-day: days since 1990-01-01 in bytes 2-3"
    S5TIME = "S5T#duration: time base and three BCD digits in bytes 2-3"
    REAL = "floating point number: IEEE 754 single in bytes 2-5"
    BINARY_32 = "2#bits: bytes 2-5"
    INT_32 = "L#signed integer: bytes 2-5"
    CHARS_32 = "'characters': bytes 2-5"
    BYTES_32 = "B#(a, b, c, d): bytes 2-5"
    HEX_32 = "DW#16#hex: bytes 2-5"
    TIME = "T#milliseconds MS: bytes 2-5"
    TIME_OF_DAY = "TOD#h:m:s.ms: milliseconds since midnight in bytes 2-5"


class Scope(Enum):
    """Why a row is in the table."""

    MINIMAL = "minimal subset"
    REFERENCE_BLOCK = "needed for cm7.bin"


class Status(Enum):
    """Result of comparing the corpus with ``MC7toAWL.cs`` for a row."""

    VERIFIED = "verified"
    """Corpus vectors exercise the row and the C# decoder agrees on bytes, length and meaning."""
    NOTATION = "verified, notation differs"
    """Both agree on bytes, length and value; they spell the operand differently."""
    UNVERIFIED = "unverified"
    """The corpus and the C# decoder disagree on what the bytes mean."""


@dataclass(frozen=True, slots=True)
class OpcodeRow:
    """One instruction form.

    Attributes:
        mnemonic: Operation in international mnemonics.
        opcode: Values of the fixed bits of the first two bytes.
        mask: The bits of the first two bytes that are fixed.
        length: Encoded length in bytes, operand included.
        operand: Layout of the operand.
        area: Operand area or type prefix in international mnemonics, ``""`` if none.
        scope: Why the row is in the table.
        status: Outcome of the cross-check against ``MC7toAWL.cs``.
        source: Where ``MC7toAWL.cs`` decodes this form.
        note: What differs or is not exercised, if anything.
    """

    mnemonic: str
    opcode: bytes
    mask: bytes
    length: int
    operand: Operand
    area: str = ""
    scope: Scope = Scope.MINIMAL
    status: Status = Status.VERIFIED
    source: str = ""
    note: str = ""

    def matches(self, first: int, second: int) -> bool:
        """Whether the first two bytes of an instruction select this row."""
        return first & self.mask[0] == self.opcode[0] and second & self.mask[1] == self.opcode[1]

    @property
    def key(self) -> str:
        """A stable identifier: pattern of the first two bytes plus the form."""
        return f"{self.opcode.hex()}/{self.mask.hex()}"


# Area nibble of the long bit forms and of the long load and transfer forms.
_BIT_AREAS = {1: "I", 2: "Q", 3: "M", 4: "DBX", 5: "DIX", 6: "L"}
_WIDTHS = {1: "B", 2: "W", 3: "D"}
_DATA_AREAS = {1: "I", 2: "Q", 3: "M", 4: "DB", 5: "DI", 6: "L"}

_LONG_BIT = "MC7toAWL.cs lines 107-178"
_BIT_NOTE = "bit numbers 8-15 are not exercised by the corpus and stay unknown"


def _long_bit_rows() -> list[OpcodeRow]:
    """``op area byte.bit`` in 4 bytes: byte 1 is negation bit, area nibble and bit number."""
    plain = {0x00: ("A", "AN"), 0x01: ("O", "ON"), 0x09: ("S", "R")}
    edges = {0x49: ("FP", "FN")}
    rows = []
    for table, scope in ((plain, Scope.MINIMAL), (edges, Scope.REFERENCE_BLOCK)):
        for first, pair in table.items():
            for flag, mnemonic in zip((0x00, 0x80), pair, strict=True):
                rows += [
                    OpcodeRow(
                        mnemonic,
                        bytes((first, flag | code << 4)),
                        b"\xff\xf8",
                        4,
                        Operand.BIT_LONG,
                        area,
                        scope,
                        source=_LONG_BIT,
                        note=_BIT_NOTE,
                    )
                    for code, area in _BIT_AREAS.items()
                ]
    rows += [
        OpcodeRow(
            "=",
            bytes((0x41, code << 4)),
            b"\xff\xf8",
            4,
            Operand.BIT_LONG,
            area,
            source="MC7toAWL.cs lines 545-678",
        )
        for code, area in _BIT_AREAS.items()
    ]
    return rows


def _short_bit_rows() -> list[OpcodeRow]:
    """``op area byte.bit`` in 2 bytes: the bit number sits in the opcode byte."""
    memory = {0x80: "A", 0x88: "O", 0x90: "S", 0x98: "=", 0xA0: "AN", 0xA8: "ON", 0xB0: "R"}
    rows = [
        OpcodeRow(
            mnemonic,
            bytes((first, 0x00)),
            b"\xf8\x00",
            2,
            Operand.BIT_SHORT_8,
            "M",
            source=f"MC7toAWL.cs case 0x{first:02X}-0x{first + 7:02X}",
        )
        for first, mnemonic in memory.items()
    ]
    for first, mnemonic in memory.items():
        rows += [
            OpcodeRow(
                mnemonic,
                bytes((first + 0x40, flag)),
                b"\xf8\x80",
                2,
                Operand.BIT_SHORT_7,
                area,
                source=f"MC7toAWL.cs case 0x{first + 0x40:02X}-0x{first + 0x47:02X}",
            )
            for flag, area in ((0x00, "I"), (0x80, "Q"))
        ]
    return rows


def _load_transfer_rows() -> list[OpcodeRow]:
    """``L`` and ``T`` on directly addressed bytes, words and double words."""
    rows = []
    for width, base in (("B", 0x0A), ("W", 0x12), ("D", 0x1A)):
        rows += [
            OpcodeRow(
                mnemonic,
                bytes((base + step, 0x00)),
                b"\xff\x00",
                2,
                Operand.ADDRESS_8,
                f"M{width}",
                source=f"MC7toAWL.cs case 0x{base + step:02X}",
            )
            for step, mnemonic in ((0, "L"), (1, "T"))
        ]
    for width, base in (("B", 0x4A), ("W", 0x52), ("D", 0x5A)):
        for step, mnemonic in ((0, "L"), (1, "T")):
            rows += [
                OpcodeRow(
                    mnemonic,
                    bytes((base + step, flag)),
                    b"\xff\x80",
                    2,
                    Operand.ADDRESS_7,
                    f"{area}{width}",
                    source=f"MC7toAWL.cs case 0x{base + step:02X}",
                )
                for flag, area in ((0x00, "I"), (0x80, "Q"))
            ]
    long_source = "MC7toAWL.cs case 0x7E, lines 1559-1773"
    for code, width in _WIDTHS.items():
        rows.append(
            OpcodeRow(
                "L",
                bytes((0x7E, code)),
                b"\xff\xff",
                4,
                Operand.ADDRESS_16,
                f"PI{width}",
                source=long_source,
            )
        )
        rows.append(
            OpcodeRow(
                "T",
                bytes((0x7E, code + 4)),
                b"\xff\xff",
                4,
                Operand.ADDRESS_16,
                f"PQ{width}",
                source=long_source,
            )
        )
        for area_code, area in _DATA_AREAS.items():
            rows += [
                OpcodeRow(
                    mnemonic,
                    bytes((0x7E, area_code << 4 | code + step)),
                    b"\xff\xff",
                    4,
                    Operand.ADDRESS_16,
                    f"{area}{width}",
                    source=long_source,
                )
                for step, mnemonic in ((0, "L"), (4, "T"))
            ]
    return rows


def _constant(
    first: int,
    second: int,
    length: int,
    operand: Operand,
    status: Status = Status.VERIFIED,
    note: str = "",
) -> OpcodeRow:
    return OpcodeRow(
        "L",
        bytes((first, second)),
        b"\xff\xff",
        length,
        operand,
        status=status,
        source=f"MC7toAWL.cs case 0x{first:02X}, sub-case 0x{second:02X}",
        note=note,
    )


_HELPER = "the C# text comes from a Helper function that was not compared"

_CONSTANT_ROWS = [
    OpcodeRow(
        "L",
        b"\x28\x00",
        b"\xff\x00",
        2,
        Operand.BYTE_HEX,
        status=Status.UNVERIFIED,
        source="MC7toAWL.cs case 0x28",
        note=(
            "the corpus prints the byte in decimal after B#16# (0x12 gives B#16#18), "
            "the C# decoder prints it in hexadecimal (B#16#12)"
        ),
    ),
    _constant(0x30, 0x02, 4, Operand.BINARY_16, Status.NOTATION, _HELPER),
    _constant(0x30, 0x03, 4, Operand.INT_16),
    _constant(0x30, 0x05, 4, Operand.CHARS_16, Status.NOTATION, _HELPER),
    _constant(0x30, 0x06, 4, Operand.BYTES_16, note="values below 10 are not exercised"),
    _constant(0x30, 0x07, 4, Operand.HEX_16, Status.NOTATION, "C# prints upper-case hex digits"),
    _constant(
        0x30, 0x08, 4, Operand.COUNTER_BCD, note="the corpus rejects values above 999, C# does not"
    ),
    _constant(0x30, 0x0A, 4, Operand.DATE, Status.NOTATION, _HELPER),
    _constant(0x30, 0x0C, 4, Operand.S5TIME, Status.NOTATION, _HELPER),
    _constant(0x38, 0x01, 6, Operand.REAL, Status.NOTATION, "corpus fixed notation, C# scientific"),
    _constant(0x38, 0x02, 6, Operand.BINARY_32, Status.NOTATION, _HELPER),
    _constant(0x38, 0x03, 6, Operand.INT_32),
    _constant(0x38, 0x05, 6, Operand.CHARS_32, Status.NOTATION, _HELPER),
    _constant(
        0x38,
        0x06,
        6,
        Operand.BYTES_32,
        Status.NOTATION,
        "the corpus pads each byte to 2 digits (0 gives 00), C# does not pad",
    ),
    _constant(0x38, 0x07, 6, Operand.HEX_32, Status.NOTATION, "C# prints upper-case hex digits"),
    _constant(
        0x38,
        0x09,
        6,
        Operand.TIME,
        Status.NOTATION,
        "the corpus prints unsigned milliseconds; " + _HELPER,
    ),
    _constant(0x38, 0x0B, 6, Operand.TIME_OF_DAY, Status.NOTATION, _HELPER),
]

_REFERENCE_ROWS = [
    OpcodeRow(
        "LC",
        b"\x4c\x00",
        b"\xff\x00",
        2,
        Operand.ADDRESS_8,
        "C",
        Scope.REFERENCE_BLOCK,
        source="MC7toAWL.cs case 0x4C",
    ),
    OpcodeRow(
        "CD",
        b"\x54\x00",
        b"\xff\x00",
        2,
        Operand.ADDRESS_8,
        "C",
        Scope.REFERENCE_BLOCK,
        source="MC7toAWL.cs case 0x54",
        note="C# decodes counter numbers below 128 only; the corpus also has C 255",
    ),
    OpcodeRow(
        "CU",
        b"\x6c\x00",
        b"\xff\x00",
        2,
        Operand.ADDRESS_8,
        "C",
        Scope.REFERENCE_BLOCK,
        source="MC7toAWL.cs case 0x6C",
    ),
    OpcodeRow(
        "BE",
        b"\x65\x00",
        b"\xff\xff",
        2,
        Operand.NONE,
        "",
        Scope.REFERENCE_BLOCK,
        source="MC7toAWL.cs case 0x65, sub-case 0x00",
    ),
]

OPCODE_TABLE: tuple[OpcodeRow, ...] = (
    *_long_bit_rows(),
    *_short_bit_rows(),
    *_load_transfer_rows(),
    *_CONSTANT_ROWS,
    *_REFERENCE_ROWS,
)
"""All instruction forms the toolchain knows, in documentation order."""

GERMAN_MNEMONICS: dict[str, str] = {
    "A": "U",
    "AN": "UN",
    "O": "O",
    "ON": "ON",
    "=": "=",
    "S": "S",
    "R": "R",
    "L": "L",
    "T": "T",
    "FP": "FP",
    "FN": "FN",
    "LC": "LC",
    "CD": "ZR",
    "CU": "ZV",
    "BE": "BE",
}
"""German (SIMATIC) spelling of every mnemonic in the table, from ``Mnemonic.cs``."""

GERMAN_AREAS: dict[str, str] = {
    "I": "E",
    "Q": "A",
    "M": "M",
    "DBX": "DBX",
    "DIX": "DIX",
    "L": "L",
    "C": "Z",
    **{
        f"{area}{width}": f"{german}{width}"
        for area, german in (
            ("I", "E"),
            ("Q", "A"),
            ("M", "M"),
            ("DB", "DB"),
            ("DI", "DI"),
            ("L", "L"),
            ("PI", "PE"),
            ("PQ", "PA"),
        )
        for width in "BWD"
    },
}
"""German (SIMATIC) spelling of every operand area in the table, from ``Mnemonic.cs``."""


def find_row(first: int, second: int) -> OpcodeRow | None:
    """Return the row selected by the first two bytes of an instruction, if any."""
    for row in _ROWS_BY_FIRST_BYTE.get(first, ()):
        if row.matches(first, second):
            return row
    return None


def _index() -> dict[int, tuple[OpcodeRow, ...]]:
    index: dict[int, list[OpcodeRow]] = {}
    for row in OPCODE_TABLE:
        for first in range(256):
            if first & row.mask[0] == row.opcode[0]:
                index.setdefault(first, []).append(row)
    return {first: tuple(rows) for first, rows in index.items()}


_ROWS_BY_FIRST_BYTE = _index()
