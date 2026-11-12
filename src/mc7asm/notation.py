"""Spelling of typed constants: the single place that maps literal text to values and back.

The disassembler, the IR printer and the parser all go through this module, so
a literal is always written and read the same way. The written forms follow
the opcode corpus, including its habits (lower-case hex digits, bytes of a
4-byte ``B#(...)`` padded to two digits, ``T#`` as a plain millisecond count).

Every constant is a :class:`Notation`, a non-negative integer value and a size
in bytes. What the value means depends on the notation: milliseconds for the
time notations, days since 1990-01-01 for ``D#``, the packed bytes for
characters and ``B#(...)``, the number itself otherwise.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, timedelta
from enum import Enum

DATE_EPOCH = date(1990, 1, 1)
S5TIME_UNITS_MS = (10, 100, 1000, 10000)
S5TIME_MAX_COUNT = 999


class Notation(Enum):
    """The typed constant notations of the opcode table; the value is the prefix."""

    BYTE_HEX = "B#16#"
    BINARY = "2#"
    HEX_WORD = "W#16#"
    HEX_DWORD = "DW#16#"
    CHARS = "'"
    BYTES = "B#("
    COUNTER = "C#"
    DATE = "D#"
    S5TIME = "S5T#"
    TIME = "T#"
    TIME_OF_DAY = "TOD#"


class NotationError(ValueError):
    """A literal has a known prefix but is malformed or out of range.

    Attributes:
        hint: An example of a valid literal or the reason for the limit.
    """

    def __init__(self, message: str, hint: str = "") -> None:
        """Store the message and the hint."""
        super().__init__(message)
        self.hint = hint


# ---------------------------------------------------------------------- formatting


def format_constant(notation: Notation, value: int, size: int) -> str:
    """Write a constant the way the opcode corpus does."""
    return _FORMATTERS[notation](value, size)


def format_real(value: float) -> str:
    """Write a real number in fixed notation with six decimals, as the corpus does."""
    return f"{value:f}"


def format_s5time(milliseconds: int) -> str:
    """Write a duration as ``S5T#`` with hour, minute, second and millisecond parts."""
    parts = (
        (milliseconds // 3_600_000, "H"),
        (milliseconds // 60_000 % 60, "M"),
        (milliseconds // 1000 % 60, "S"),
        (milliseconds % 1000, "MS"),
    )
    text = "".join(f"{amount}{unit}" for amount, unit in parts if amount)
    return f"S5T#{text or '0MS'}"


def _format_chars(value: int, size: int) -> str:
    return "'" + value.to_bytes(size, "big").lstrip(b"\x00").decode("ascii") + "'"


def _format_bytes(value: int, size: int) -> str:
    raw = value.to_bytes(size, "big")
    width = 2 if size == 4 else 1
    return "B#(" + ", ".join(f"{byte:0{width}d}" for byte in raw) + ")"


def _format_date(days: int, _size: int) -> str:
    day = DATE_EPOCH + timedelta(days=days)
    return f"D#{day.year}-{day.month}-{day.day}"


def _format_time_of_day(milliseconds: int, _size: int) -> str:
    return (
        f"TOD#{milliseconds // 3_600_000}:{milliseconds // 60_000 % 60}:"
        f"{milliseconds // 1000 % 60}.{milliseconds % 1000:03d}"
    )


_FORMATTERS: dict[Notation, Callable[[int, int], str]] = {
    Notation.BYTE_HEX: lambda value, _size: f"B#16#{value:X}",
    Notation.BINARY: lambda value, _size: f"2#{value:b}",
    Notation.HEX_WORD: lambda value, _size: f"W#16#{value:x}",
    Notation.HEX_DWORD: lambda value, _size: f"DW#16#{value:x}",
    Notation.CHARS: _format_chars,
    Notation.BYTES: _format_bytes,
    Notation.COUNTER: lambda value, _size: f"C#{value}",
    Notation.DATE: _format_date,
    Notation.S5TIME: lambda value, _size: format_s5time(value),
    Notation.TIME: lambda value, _size: f"T#{value}MS",
    Notation.TIME_OF_DAY: _format_time_of_day,
}

# ---------------------------------------------------------------------- encodings


def encode_s5time(milliseconds: int) -> int | None:
    """Return the 16-bit S5TIME word: time base in bits 12-13, three BCD digits below.

    The smallest time base that represents the duration exactly is used, which
    is the most precise one. Returns ``None`` if no base can represent it.
    """
    for base, unit in enumerate(S5TIME_UNITS_MS):
        count, remainder = divmod(milliseconds, unit)
        if remainder == 0 and count <= S5TIME_MAX_COUNT:
            return base << 12 | encode_bcd(count)
    return None


def encode_bcd(value: int) -> int:
    """Return a number below 1000 as three BCD digits."""
    return value // 100 << 8 | value // 10 % 10 << 4 | value % 10


# ---------------------------------------------------------------------- parsing


def parse_constant(text: str) -> tuple[Notation, int, int] | None:
    """Read a typed constant and return ``(notation, value, size in bytes)``.

    Returns ``None`` if the text does not start like any typed constant.

    Raises:
        NotationError: If the text has a known prefix but is malformed or out of range.
    """
    upper = text.upper()
    for prefix, parser in _PARSERS:
        if upper.startswith(prefix):
            return parser(text)
    return None


def _match(pattern: str, text: str, what: str, example: str) -> re.Match[str]:
    match = re.fullmatch(pattern, text, re.IGNORECASE)
    if match is None:
        raise NotationError(f"malformed {what} constant {text!r}", f"write it like {example}")
    return match


def _parse_byte_hex(text: str) -> tuple[Notation, int, int]:
    match = _match(r"B#16#([0-9A-F]{1,2})", text, "byte", "B#16#1F")
    return Notation.BYTE_HEX, int(match[1], 16), 1


def _parse_binary(text: str) -> tuple[Notation, int, int]:
    digits = _match(r"2#([01_]+)", text, "binary", "2#1010")[1].replace("_", "")
    if not digits or len(digits) > 32:
        raise NotationError(
            f"binary constant {text!r} needs 1 to 32 digits", "write it like 2#1010"
        )
    value = int(digits, 2)
    return Notation.BINARY, value, 2 if len(digits) <= 16 else 4


def _parse_hex_word(text: str) -> tuple[Notation, int, int]:
    match = _match(r"W#16#([0-9A-F]{1,4})", text, "word", "W#16#1A2B")
    return Notation.HEX_WORD, int(match[1], 16), 2


def _parse_hex_dword(text: str) -> tuple[Notation, int, int]:
    match = _match(r"DW#16#([0-9A-F]{1,8})", text, "double word", "DW#16#1A2B3C4D")
    return Notation.HEX_DWORD, int(match[1], 16), 4


def _parse_chars(text: str) -> tuple[Notation, int, int]:
    match = _match(r"'([\x20-\x26\x28-\x7e]{1,4})'", text, "character", "'AB'")
    raw = match[1].encode("ascii")
    return Notation.CHARS, int.from_bytes(raw, "big"), 2 if len(raw) <= 2 else 4


def _parse_bytes(text: str) -> tuple[Notation, int, int]:
    match = _match(r"B#\(([0-9, ]*)\)", text, "byte list", "B#(10, 20)")
    items = [item.strip() for item in match[1].split(",")]
    if len(items) not in (2, 4) or not all(item.isdigit() and int(item) <= 255 for item in items):
        raise NotationError(
            f"byte list {text!r} needs 2 or 4 values from 0 to 255", "write it like B#(10, 20)"
        )
    raw = bytes(int(item) for item in items)
    return Notation.BYTES, int.from_bytes(raw, "big"), len(raw)


def _parse_counter(text: str) -> tuple[Notation, int, int]:
    value = int(_match(r"C#(\d+)", text, "counter", "C#100")[1])
    if value > S5TIME_MAX_COUNT:
        raise NotationError(f"counter constant {text!r} is above C#999")
    return Notation.COUNTER, value, 2


def _parse_date(text: str) -> tuple[Notation, int, int]:
    match = _match(r"D#(\d{4})-(\d{1,2})-(\d{1,2})", text, "date", "D#2024-12-31")
    try:
        days = (date(int(match[1]), int(match[2]), int(match[3])) - DATE_EPOCH).days
    except ValueError as exc:
        raise NotationError(f"date constant {text!r} is not a calendar date") from exc
    if not 0 <= days <= 0xFFFF:
        raise NotationError(f"date constant {text!r} is outside D#1990-1-1 to D#2169-6-6")
    return Notation.DATE, days, 2


def _parse_s5time(text: str) -> tuple[Notation, int, int]:
    match = _match(
        r"S5T#(?=\d)(?:(\d+)H)?(?:(\d+)M(?!S))?(?:(\d+)S)?(?:(\d+)MS)?",
        text,
        "S5TIME",
        "S5T#2H46M30S",
    )
    hours, minutes, seconds, millis = (int(part or 0) for part in match.groups())
    total = ((hours * 60 + minutes) * 60 + seconds) * 1000 + millis
    if encode_s5time(total) is None:
        raise NotationError(
            f"S5TIME constant {text!r} cannot be represented exactly",
            "S5TIME holds 3 digits with a time base of 10 ms, 100 ms, 1 s or 10 s, "
            "at most S5T#2H46M30S",
        )
    return Notation.S5TIME, total, 2


def _parse_time(text: str) -> tuple[Notation, int, int]:
    value = int(_match(r"T#(\d+)MS", text, "TIME", "T#1500MS (milliseconds only)")[1])
    if value > 0xFFFFFFFF:
        raise NotationError(f"TIME constant {text!r} does not fit 32 bits")
    return Notation.TIME, value, 4


def _parse_time_of_day(text: str) -> tuple[Notation, int, int]:
    match = _match(r"TOD#(\d+):(\d{1,2}):(\d{1,2})\.(\d{3})", text, "time of day", "TOD#8:30:0.000")
    hours, minutes, seconds, millis = (int(part) for part in match.groups())
    total = ((hours * 60 + minutes) * 60 + seconds) * 1000 + millis
    if minutes > 59 or seconds > 59 or total > 0xFFFFFFFF:
        raise NotationError(f"time of day constant {text!r} is out of range")
    return Notation.TIME_OF_DAY, total, 4


# Longer prefixes first, so that B#16# and B#( win over a shorter look-alike.
_PARSERS: tuple[tuple[str, Callable[[str], tuple[Notation, int, int]]], ...] = (
    ("DW#16#", _parse_hex_dword),
    ("W#16#", _parse_hex_word),
    ("B#16#", _parse_byte_hex),
    ("B#(", _parse_bytes),
    ("S5T#", _parse_s5time),
    ("TOD#", _parse_time_of_day),
    ("T#", _parse_time),
    ("2#", _parse_binary),
    ("C#", _parse_counter),
    ("D#", _parse_date),
    ("'", _parse_chars),
)
