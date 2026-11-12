"""Container writer: wraps compiled MC7 code into a complete block image.

The reading direction lives in :mod:`mc7asm.image`; this module produces the
same model for a block that was compiled from source. It is pure: it takes
compiled code and a timestamp and returns a :class:`~mc7asm.image.BlockImage`.
It performs no input or output and knows nothing about a PLC. Building an
image and loading it into a CPU are separate concerns; the only code that
talks to a PLC is the ``mc7`` package, which this package never imports.

What the builder relies on
--------------------------
The layout is the one documented in :mod:`mc7asm.image`. Every value that
cannot be derived from the source is taken from the one real block in the
repository, the OB1 ``cm7.bin`` of rz-libmc7, the working example of a minimal
organization block. ``docs/container.md`` decodes that block byte by byte.

* **Block end.** ``BE`` (``65 00``) is appended as the last instruction unless
  the source already ends with it, and is counted in the code length.
* **Interface.** A 7-byte sub-header (``01``, block number little-endian and
  zero for an OB, length of the declarations little-endian, start value
  length), the two-byte declarations, and one closing byte ``20``. An OB gets
  the ten temporary variables of the reference block (20 bytes of start
  information); an FC or FB compiled from source has no declarations.
* **Segment table.** Little-endian words: the number of networks, the length
  of each network in bytes without the closing ``BE``, and a zero word.
* **Footer.** Author, family and name empty, version byte ``10`` as in the
  reference block, and a zero checksum. The checksum algorithm is not
  documented by any source and is never computed here; the Snap7 client
  zeroes the field before a download as well.

Only the single-network OB layout is confirmed by a real block: building the
reference program reproduces ``cm7.bin`` except for its checksum. Everything
else is a generalization and is reported as a note by :func:`build_block`.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from datetime import datetime

from mc7asm import ir
from mc7asm.codegen import CompiledBlock
from mc7asm.errors import ContainerError
from mc7asm.image import (
    BlockAttributes,
    BlockFooter,
    BlockHeader,
    BlockImage,
    BlockType,
    S7Timestamp,
)
from mc7asm.validate import Finding, Severity

BLOCK_END = b"\x65\x00"
MAX_SECTION_SIZE = 0xFFFF

HEADER_VERSION = 0x01
LANGUAGE_STL = 0x01
FOOTER_VERSION = 0x10

INTERFACE_CODE_BLOCK = 0x01
INTERFACE_TRAILER = b"\x20"
# The ten temporary variables every OB1 declares, as (data type, declaration kind)
# pairs: six BYTE (02), three INT (05) and one DATE_AND_TIME (0e), all TEMP (05).
OB_START_INFORMATION = bytes.fromhex("0205 0205 0205 0205 0205 0205 0505 0505 0505 0e05")
OB_LOCAL_DATA_LENGTH = 20


@dataclass(frozen=True, slots=True)
class BuiltBlock:
    """A block image built from compiled code.

    Attributes:
        image: The complete image.
        block_end_appended: Whether the builder added the closing ``BE``.
        notes: What in this image is generalized beyond the reference block.
    """

    image: BlockImage
    block_end_appended: bool
    notes: tuple[Finding, ...]


def build_block(
    compiled: CompiledBlock, modified: datetime, interface_modified: datetime | None = None
) -> BuiltBlock:
    """Wrap compiled code into a block image.

    Args:
        compiled: Result of :func:`mc7asm.codegen.compile_block`.
        modified: Time stored as the last code change.
        interface_modified: Time stored as the last interface change; defaults
            to ``modified``.

    Raises:
        ContainerError: If the block has no network or a section does not fit
            its 16-bit length field.
    """
    block = compiled.block
    if block.block_type not in (BlockType.OB, BlockType.FC, BlockType.FB):
        raise ContainerError(f"{block.name} is not a code block; only OB, FC and FB are built")
    if not compiled.networks:
        raise ContainerError(f"{block.name} has no network; a block needs at least one")
    code, network_lengths, appended = close_code(compiled)
    if len(code) > MAX_SECTION_SIZE:
        raise ContainerError(
            f"{block.name}: the code is {len(code)} bytes, the limit is {MAX_SECTION_SIZE}"
        )
    interface = build_interface(block.block_type, block.number)
    segment_table = build_segment_table(network_lengths)
    if len(segment_table) > MAX_SECTION_SIZE:
        raise ContainerError(f"{block.name}: too many networks for the segment table")
    is_ob = block.block_type is BlockType.OB
    stamp = S7Timestamp.from_datetime(modified)
    footer = BlockFooter(bytes(8), bytes(8), bytes(8), FOOTER_VERSION, 0, 0, bytes(8))
    header = BlockHeader(
        version=HEADER_VERSION,
        attributes=BlockAttributes.LINKED,
        language=LANGUAGE_STL,
        type_code=block.block_type.value,
        number=block.number,
        length=0,
        password=bytes(4),
        modified=stamp,
        interface_modified=S7Timestamp.from_datetime(interface_modified or modified),
        interface_length=len(interface),
        segment_table_length=len(segment_table),
        local_data_length=OB_LOCAL_DATA_LENGTH if is_ob else 0,
        mc7_length=len(code),
    )
    image = BlockImage(header, code, interface, segment_table, b"", footer)
    image = BlockImage(
        _with_length(header, image.size), code, interface, segment_table, b"", footer
    )
    return BuiltBlock(image, appended, _notes(block, len(network_lengths)))


def close_code(compiled: CompiledBlock) -> tuple[bytes, tuple[int, ...], bool]:
    """Return the final code, the network lengths for the segment table and whether BE was added.

    The closing ``BE`` is recognised by the last instruction, not by the last
    two bytes, so a constant that happens to end in ``65 00`` is not mistaken
    for it. Network lengths never include the closing ``BE``.
    """
    lengths = [network.size for network in compiled.networks]
    last = compiled.networks[-1].instructions
    if last and isinstance(last[-1].instruction, ir.BlockEnd):
        lengths[-1] -= len(BLOCK_END)
        return compiled.body, tuple(lengths), False
    return compiled.body + BLOCK_END, tuple(lengths), True


def build_interface(block_type: BlockType, number: int) -> bytes:
    """Build the interface section of a block without declarations of its own."""
    is_ob = block_type is BlockType.OB
    declarations = OB_START_INFORMATION if is_ob else b""
    header = struct.pack(
        "<BHHH", INTERFACE_CODE_BLOCK, 0 if is_ob else number, len(declarations), 0
    )
    return header + declarations + INTERFACE_TRAILER


def build_segment_table(network_lengths: tuple[int, ...]) -> bytes:
    """Build the segment table: network count, one length per network, a zero word."""
    return struct.pack(f"<{len(network_lengths) + 2}H", len(network_lengths), *network_lengths, 0)


def _with_length(header: BlockHeader, length: int) -> BlockHeader:
    fields = {name: getattr(header, name) for name in header.__dataclass_fields__}
    return BlockHeader(**{**fields, "length": length})


def _notes(block: ir.Block, network_count: int) -> tuple[Finding, ...]:
    notes = []
    if block.block_type is not BlockType.OB:
        notes.append(
            Finding(
                Severity.NOTE,
                "generalized-interface",
                f"the interface and the local data length of an {block.block_type.name} "
                "without declarations are generalized from the OB1 reference block",
            )
        )
    elif block.number != 1:
        notes.append(
            Finding(
                Severity.NOTE,
                "generalized-interface",
                f"OB{block.number} gets the temporary variables of OB1; the 20 bytes of "
                "start information are the same size, the declared types may differ",
            )
        )
    if network_count != 1:
        notes.append(
            Finding(
                Severity.NOTE,
                "generalized-segment-table",
                f"the segment table for {network_count} networks is generalized from the "
                "single-network reference block",
            )
        )
    return tuple(notes)
