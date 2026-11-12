"""Disassembler: decodes the MC7 code of a block image with the opcode table.

The decoder is table driven. For every position it looks up the row selected
by the first two bytes (:func:`mc7asm.opcodes.find_row`), takes the length from
that row and renders the operand. Bytes without a row are reported as
:class:`UnknownOpcode` entries with their offset; nothing is skipped silently.

MC7 instructions in the corpus are 2, 4 or 6 bytes long, so an unknown opcode
advances by one 2-byte word. An unknown instruction may be longer than that,
which is why a finding warns that boundaries after the first unknown opcode are
not certain.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Callable
from dataclasses import dataclass

from mc7asm.errors import UnsupportedBlockError
from mc7asm.image import HEADER_SIZE, BlockImage, BlockType
from mc7asm.notation import (
    S5TIME_MAX_COUNT,
    S5TIME_UNITS_MS,
    Notation,
    format_constant,
    format_real,
    format_s5time,
)
from mc7asm.opcodes import (
    GERMAN_AREAS,
    GERMAN_MNEMONICS,
    Mnemonics,
    OpcodeRow,
    Operand,
    find_row,
)
from mc7asm.validate import Finding, Severity, validate_image

WORD_SIZE = 2


@dataclass(frozen=True, slots=True)
class DecodedInstruction:
    """One instruction decoded with a table row.

    Attributes:
        offset: Offset of the first byte inside the code section.
        data: The bytes of the instruction.
        mnemonic: Operation, in the requested spelling.
        operand: Operand text, ``""`` if the instruction has none.
        row: The table row that decoded it.
    """

    offset: int
    data: bytes
    mnemonic: str
    operand: str
    row: OpcodeRow

    @property
    def text(self) -> str:
        """The statement as STL text, for example ``A I 0.1``."""
        return f"{self.mnemonic} {self.operand}" if self.operand else self.mnemonic


@dataclass(frozen=True, slots=True)
class UnknownOpcode:
    """Bytes the table cannot decode.

    Attributes:
        offset: Offset of the first byte inside the code section.
        data: The bytes that were stepped over, normally one 2-byte word.
        reason: Why they could not be decoded.
    """

    offset: int
    data: bytes
    reason: str


Entry = DecodedInstruction | UnknownOpcode


@dataclass(frozen=True, slots=True)
class Disassembly:
    """The result of disassembling one code block.

    Attributes:
        image: The block image the code came from.
        entries: Instructions and unknown-opcode entries, in code order.
        findings: Layout findings of the image followed by decode findings.
    """

    image: BlockImage
    entries: tuple[Entry, ...]
    findings: tuple[Finding, ...]

    @property
    def code_size(self) -> int:
        """Number of bytes in the code section."""
        return len(self.image.payload)

    @property
    def unknown_bytes(self) -> int:
        """Number of code bytes that could not be decoded."""
        return sum(len(entry.data) for entry in self.entries if isinstance(entry, UnknownOpcode))

    @property
    def decoded_bytes(self) -> int:
        """Number of code bytes covered by decoded instructions."""
        return self.code_size - self.unknown_bytes


def disassemble(image: BlockImage, mnemonics: Mnemonics = Mnemonics.EN) -> Disassembly:
    """Decode the code section of an OB, FC or FB.

    Layout problems of the image are reported as findings and the code section
    is decoded all the same.

    Raises:
        UnsupportedBlockError: For data blocks and the other block types that
            hold no user MC7 code.
    """
    _require_code_block(image)
    entries = decode_code(image.payload, mnemonics)
    return Disassembly(image, entries, (*validate_image(image), *_decode_findings(entries)))


def decode_code(code: bytes, mnemonics: Mnemonics = Mnemonics.EN) -> tuple[Entry, ...]:
    """Decode a run of MC7 code into instructions and unknown-opcode entries."""
    entries: list[Entry] = []
    offset = 0
    while offset < len(code):
        entry = _decode_at(code, offset, mnemonics)
        entries.append(entry)
        offset += len(entry.data)
    return tuple(entries)


def decode_instruction(
    data: bytes, mnemonics: Mnemonics = Mnemonics.EN
) -> DecodedInstruction | None:
    """Decode the single instruction at the start of ``data``, or return ``None``."""
    entry = _decode_at(data, 0, mnemonics) if data else None
    return entry if isinstance(entry, DecodedInstruction) else None


def _decode_at(code: bytes, offset: int, mnemonics: Mnemonics) -> Entry:
    remaining = len(code) - offset
    if remaining < WORD_SIZE:
        return UnknownOpcode(offset, code[offset:], "a single byte is left over")
    word = code[offset : offset + WORD_SIZE]
    row = find_row(word[0], word[1])
    if row is None:
        return UnknownOpcode(offset, word, "no table row matches")
    if row.length > remaining:
        return UnknownOpcode(
            offset,
            code[offset:],
            f"{row.mnemonic} needs {row.length} bytes, only {remaining} are left",
        )
    data = code[offset : offset + row.length]
    operand = _OPERANDS[row.operand](data)
    if operand is None:
        return UnknownOpcode(offset, word, "the operand value is one the corpus rejects")
    german = mnemonics is Mnemonics.DE
    mnemonic = GERMAN_MNEMONICS[row.mnemonic] if german else row.mnemonic
    area = GERMAN_AREAS[row.area] if german and row.area else row.area
    text = " ".join(part for part in (area, operand) if part)
    return DecodedInstruction(offset, data, mnemonic, text, row)


def _require_code_block(image: BlockImage) -> None:
    header = image.header
    block_type = header.block_type
    if block_type in (BlockType.OB, BlockType.FC, BlockType.FB):
        return
    if block_type is BlockType.DB:
        reason = "is a data block: its body holds values, not MC7 code"
    elif block_type is BlockType.SDB:
        reason = "is a system data block: it holds configuration data, not MC7 code"
    elif block_type in (BlockType.SFC, BlockType.SFB):
        reason = "is a system block that lives in the CPU firmware and is out of scope"
    else:
        reason = "has an undocumented block type"
    raise UnsupportedBlockError(
        f"{header.name} {reason}; only OB, FC and FB can be disassembled "
        "(use 'mc7asm dump' to inspect the block)"
    )


def _decode_findings(entries: tuple[Entry, ...]) -> list[Finding]:
    unknown = [entry for entry in entries if isinstance(entry, UnknownOpcode)]
    findings = [
        Finding(
            Severity.WARNING,
            "unknown-opcode",
            f"unknown opcode {entry.data.hex(' ')} at code offset 0x{entry.offset:04x} "
            f"(file offset 0x{entry.offset + HEADER_SIZE:04x}): {entry.reason}",
        )
        for entry in unknown
    ]
    if unknown and unknown[0] is not entries[-1]:
        findings.append(
            Finding(
                Severity.WARNING,
                "boundaries-uncertain",
                f"instruction boundaries after code offset 0x{unknown[0].offset:04x} are not "
                "certain: an unknown instruction may be longer than the bytes stepped over",
            )
        )
    return findings


# ---------------------------------------------------------------------- operands
#
# Each renderer receives the complete instruction bytes and returns the operand
# text without the area prefix, or None for a value the corpus rejects or does
# not exercise. Constants are spelled by mc7asm.notation.


def _u16(data: bytes) -> int:
    value: int = struct.unpack_from(">H", data, 2)[0]
    return value


def _u32(data: bytes) -> int:
    value: int = struct.unpack_from(">I", data, 2)[0]
    return value


def _nibbles(value: int) -> tuple[int, int, int, int]:
    return value >> 12 & 0xF, value >> 8 & 0xF, value >> 4 & 0xF, value & 0xF


def _typed(notation: Notation, size: int) -> Callable[[bytes], str | None]:
    """Render the ``size`` bytes after the opcode as a constant of ``notation``."""

    def render(data: bytes) -> str:
        return format_constant(notation, int.from_bytes(data[2 : 2 + size], "big"), size)

    return render


def _characters(size: int) -> Callable[[bytes], str | None]:
    def render(data: bytes) -> str | None:
        text = data[2 : 2 + size].lstrip(b"\x00")
        if not text or any(not 0x20 <= byte < 0x7F or byte == 0x27 for byte in text):
            return None
        return format_constant(Notation.CHARS, int.from_bytes(text, "big"), size)

    return render


def _counter(data: bytes) -> str | None:
    thousands, hundreds, tens, ones = _nibbles(_u16(data))
    value = thousands * 1000 + hundreds * 100 + tens * 10 + ones
    return format_constant(Notation.COUNTER, value, 2) if value <= S5TIME_MAX_COUNT else None


def _s5time(data: bytes) -> str | None:
    base, hundreds, tens, ones = _nibbles(_u16(data))
    value = hundreds * 100 + tens * 10 + ones
    if base >= len(S5TIME_UNITS_MS) or value > S5TIME_MAX_COUNT:
        return None
    return format_s5time(value * S5TIME_UNITS_MS[base])


def _real(data: bytes) -> str | None:
    value: float = struct.unpack_from(">f", data, 2)[0]
    return format_real(value) if math.isfinite(value) else None


_OPERANDS: dict[Operand, Callable[[bytes], str | None]] = {
    Operand.NONE: lambda data: "",
    Operand.BIT_LONG: lambda data: f"{_u16(data)}.{data[1] & 7}",
    Operand.BIT_SHORT_8: lambda data: f"{data[1]}.{data[0] & 7}",
    Operand.BIT_SHORT_7: lambda data: f"{data[1] & 0x7F}.{data[0] & 7}",
    Operand.ADDRESS_8: lambda data: str(data[1]),
    Operand.ADDRESS_7: lambda data: str(data[1] & 0x7F),
    Operand.ADDRESS_16: lambda data: str(_u16(data)),
    # The corpus prints this byte in decimal behind the hex prefix; the row is unverified.
    Operand.BYTE_HEX: lambda data: f"B#16#{data[1]}",
    Operand.BINARY_16: _typed(Notation.BINARY, 2),
    Operand.INT_16: lambda data: str(struct.unpack_from(">h", data, 2)[0]),
    Operand.CHARS_16: _characters(2),
    Operand.BYTES_16: _typed(Notation.BYTES, 2),
    Operand.HEX_16: _typed(Notation.HEX_WORD, 2),
    Operand.COUNTER_BCD: _counter,
    Operand.DATE: _typed(Notation.DATE, 2),
    Operand.S5TIME: _s5time,
    Operand.REAL: _real,
    Operand.BINARY_32: _typed(Notation.BINARY, 4),
    Operand.INT_32: lambda data: f"L#{struct.unpack_from('>i', data, 2)[0]}",
    Operand.CHARS_32: _characters(4),
    Operand.BYTES_32: _typed(Notation.BYTES, 4),
    Operand.HEX_32: _typed(Notation.HEX_DWORD, 4),
    Operand.TIME: _typed(Notation.TIME, 4),
    Operand.TIME_OF_DAY: _typed(Notation.TIME_OF_DAY, 4),
}
