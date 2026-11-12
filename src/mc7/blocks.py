"""S7 block images: header parsing, validation and file storage.

A block image is the byte sequence the CPU hands out on a full upload:
a 36-byte header, the MC7 payload, the interface description and a footer.
The same bytes are what the CPU expects back on a download.

Header layout (big-endian), as used by STEP 7 and the Snap7 library:

======  ====  ==========================================
offset  size  field
======  ====  ==========================================
0       2     constant ``pp`` (0x70 0x70)
2       1     header version
3       1     block flags
4       1     block language
5       1     sub-block type (0x08 OB, 0x0A DB, ...)
6       2     block number
8       4     load memory length = size of the whole image
12      4     block security
16      6     code timestamp
22      6     interface timestamp
28      2     interface section length
30      2     segment table length
32      2     local data length
34      2     MC7 payload length
======  ====  ==========================================
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from mc7.errors import BlockFormatError

HEADER_SIZE = 36
BLOCK_MAGIC = b"pp"
BLOCK_FILE_SUFFIX = ".mc7"
MAX_BLOCK_NUMBER = 65535
MAX_BLOCK_SIZE = 999_999


class BlockType(Enum):
    """Block categories of an S7-300/400 CPU."""

    OB = "OB"
    DB = "DB"
    SDB = "SDB"
    FC = "FC"
    SFC = "SFC"
    FB = "FB"
    SFB = "SFB"

    @property
    def type_code(self) -> int:
        """Code used in S7 block file names on the wire (ASCII ``8``, ``A``, ...)."""
        return _TYPE_CODES[self]

    @property
    def subblock_code(self) -> int:
        """Code stored at offset 5 of the block header."""
        return _SUBBLOCK_CODES[self]


_TYPE_CODES: dict[BlockType, int] = {
    BlockType.OB: 0x38,
    BlockType.DB: 0x41,
    BlockType.SDB: 0x42,
    BlockType.FC: 0x43,
    BlockType.SFC: 0x44,
    BlockType.FB: 0x45,
    BlockType.SFB: 0x46,
}

_SUBBLOCK_CODES: dict[BlockType, int] = {
    BlockType.OB: 0x08,
    BlockType.DB: 0x0A,
    BlockType.SDB: 0x0B,
    BlockType.FC: 0x0C,
    BlockType.SFC: 0x0D,
    BlockType.FB: 0x0E,
    BlockType.SFB: 0x0F,
}

_BY_SUBBLOCK_CODE: dict[int, BlockType] = {code: bt for bt, code in _SUBBLOCK_CODES.items()}

_HEADER_STRUCT = struct.Struct(">2sBBBBHII6s6sHHHH")
_SPEC_RE = re.compile(r"(?P<type>SDB|SFC|SFB|OB|DB|FC|FB)(?P<number>\d+)")


@dataclass(frozen=True, slots=True)
class BlockHeader:
    """Decoded fields of a block image header.

    Attributes:
        block_type: Block category.
        number: Block number.
        language: Raw language code (1 STL, 2 LAD, 3 FBD, 4 SCL, 5 DB, 6 GRAPH, ...).
        flags: Raw block flags byte.
        load_size: Size of the whole image in bytes.
        mc7_size: Size of the MC7 payload in bytes.
    """

    block_type: BlockType
    number: int
    language: int
    flags: int
    load_size: int
    mc7_size: int

    @property
    def name(self) -> str:
        """Return the STEP 7 style name, for example ``OB1`` or ``DB10``."""
        return f"{self.block_type.value}{self.number}"


def parse_block(data: bytes) -> BlockHeader:
    """Validate a block image and return its decoded header.

    The checks mirror what a download client must guarantee before sending:
    the ``pp`` constant, a known block type, a length field that matches the
    actual size, and room for the footer after the MC7 payload.

    Raises:
        BlockFormatError: If the bytes are not a complete, consistent block image.
    """
    if len(data) < HEADER_SIZE:
        raise BlockFormatError(
            f"block image is {len(data)} byte(s), shorter than the {HEADER_SIZE}-byte header"
        )
    magic, _version, flags, language, subblock, number, load_size, *_rest, mc7_size = (
        _HEADER_STRUCT.unpack_from(data)
    )
    if magic != BLOCK_MAGIC:
        raise BlockFormatError(
            f"block image starts with {bytes(magic).hex()} instead of 7070 ('pp'); "
            "this is not a block uploaded with full header"
        )
    block_type = _BY_SUBBLOCK_CODE.get(subblock)
    if block_type is None:
        raise BlockFormatError(f"unknown block type code 0x{subblock:02X} in block header")
    if load_size != len(data):
        raise BlockFormatError(
            f"header declares {load_size} byte(s) but the image is {len(data)} byte(s); "
            "the block is truncated or has trailing data"
        )
    if load_size > MAX_BLOCK_SIZE:
        raise BlockFormatError(
            f"block of {load_size} bytes exceeds the {MAX_BLOCK_SIZE}-byte limit"
        )
    if mc7_size + HEADER_SIZE >= len(data):
        raise BlockFormatError(
            f"MC7 length {mc7_size} leaves no room for the block footer in {len(data)} byte(s)"
        )
    return BlockHeader(block_type, number, language, flags, load_size, mc7_size)


def parse_block_spec(text: str) -> tuple[BlockType, int]:
    """Parse a block name such as ``OB1``, ``fc105`` or ``DB10``.

    Raises:
        BlockFormatError: If the text is not a block name or the number is out of range.
    """
    match = _SPEC_RE.fullmatch(text.strip().upper())
    if match is None:
        raise BlockFormatError(
            f"cannot parse block name {text!r}; expected a form like OB1, FC105, FB3 or DB10"
        )
    number = int(match["number"])
    validate_block_number(number)
    return BlockType(match["type"]), number


def validate_block_number(number: int) -> None:
    """Raise :class:`BlockFormatError` unless ``number`` is a valid block number."""
    if not 0 <= number <= MAX_BLOCK_NUMBER:
        raise BlockFormatError(f"block number {number} is out of range 0-{MAX_BLOCK_NUMBER}")


def block_filename(block_type: BlockType, number: int) -> str:
    """Return the default file name for a block, for example ``OB1.mc7``."""
    return f"{block_type.value}{number}{BLOCK_FILE_SUFFIX}"


def save_block(path: Path, data: bytes, *, overwrite: bool = False) -> BlockHeader:
    """Validate a block image and write it to ``path``.

    Raises:
        BlockFormatError: If ``data`` is not a valid block image.
        FileExistsError: If ``path`` exists and ``overwrite`` is false.
    """
    header = parse_block(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb" if overwrite else "xb") as handle:
        handle.write(data)
    return header


def load_block(path: Path) -> tuple[bytes, BlockHeader]:
    """Read a block image from ``path`` and validate it.

    Raises:
        BlockFormatError: If the file content is not a valid block image.
        OSError: If the file cannot be read.
    """
    data = path.read_bytes()
    try:
        return data, parse_block(data)
    except BlockFormatError as exc:
        raise BlockFormatError(f"{path}: {exc}") from exc
