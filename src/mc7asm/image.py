"""Typed, lossless model of an S7-300/400 block container.

This module works at field level only: it splits a block image into its header
fields, its raw sections and its footer fields, and writes exactly the same
bytes back. It does not decode MC7 instructions or the interface contents.

Sources
-------
The layout is taken from two public reverse-engineering projects:

* **ToolBox**: DotNetSiemensPLCToolBoxLibrary, ``MC7Converter.cs``
  (``ParseBlockHeaderAndFooterFromMC7``), ``Helper.cs`` and ``S7Block.cs``.
* **rz**: rz-libmc7, ``src/plugin_bin.c`` (``mc7_parse_block``) and its sample
  block ``example/cm7.bin``.

Header, 36 bytes, big-endian. Both sources agree on every offset:

======  ====  =======================  ============================================
offset  size  field                    notes
======  ====  =======================  ============================================
0       2     signature                ``70 70`` ("pp")
2       1     block version            meaning unclear according to ToolBox
3       1     attributes               bit flags, see :class:`BlockAttributes`
4       1     language                 see :data:`LANGUAGE_NAMES`
5       1     block type               see :class:`BlockType`
6       2     block number
8       4     block length             size of the whole image
12      4     password                 non-zero means know-how protected (ToolBox)
16      6     last modified            see :class:`S7Timestamp`
22      6     last interface change    see :class:`S7Timestamp`
28      2     interface length
30      2     segment table length
32      2     local data length        a size only, there are no such bytes here
34      2     MC7 length               for a DB: length of the body at offset 36
======  ====  =======================  ============================================

Body, in the order given by the ToolBox remarks and confirmed by adding up the
rz sample (36 + 36 + 28 + 6 + 36 = 142 bytes, which is its length field):
MC7 code (or the actual values of a DB), interface, segment table.

Footer, the last 36 bytes of the image. Only ToolBox parses it:

======  ====  =========  ==================================================
offset  size  field      notes
======  ====  =========  ==================================================
+0      8     author
+8      8     family
+16     8     name
+24     1     version    high nibble major, low nibble minor
+25     1     unknown    not parsed by either source
+26     2     checksum   algorithm not documented by either source
+28     8     unknown    not parsed by either source
======  ====  =========  ==================================================

Anything between the end of the declared sections and the footer is kept as
:attr:`BlockImage.trailing_unknown`, so no byte is ever dropped.

Block end. The code section of a code block ends with the instruction ``BE``
(``65 00``), and those two bytes are counted in the MC7 length at offset 34.
The reference block ends this way, and ToolBox ``MC7Converter.cs`` decodes
``CodeSize - 2`` bytes because STEP 7 does not show that instruction. The
source of a block therefore does not contain it: :mod:`mc7asm.container`
appends it when it builds a block. The single network length in the segment
table of the reference block (34) also excludes it.

TODO(real-db-fixture): the DB layout is not settled by the sources. The ToolBox
header comment gives fields 28 and 34 a second meaning for data blocks, while
its code reads the interface and start-value lengths from the 7-byte sub-header
inside the interface. Whether start values are counted in field 28 has to be
decided from a real DB fixture. Until then the split below is purely
sequential and any start values that are not counted show up as
``trailing_unknown`` (or in the segment table slot if field 30 is non-zero).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum, IntFlag

from mc7asm.errors import ImageFormatError

HEADER_SIZE = 36
FOOTER_SIZE = 36
MIN_IMAGE_SIZE = HEADER_SIZE + FOOTER_SIZE
SIGNATURE = b"pp"

# ToolBox Helper.GetDT and rz mc7_parse_s7_date both count from this date.
S7_EPOCH = datetime(1984, 1, 1)

_HEADER = struct.Struct(">2sBBBBHI4s6s6sHHHH")
_FOOTER = struct.Struct(">8s8s8sBBH8s")
_TIMESTAMP = struct.Struct(">IH")


class BlockType(Enum):
    """Block type codes of header offset 5.

    ToolBox ``Helper.GetPLCBlockType`` and rz ``mc7_type`` list the same values.
    """

    OB = 0x08
    DB = 0x0A
    SDB = 0x0B
    FC = 0x0C
    SFC = 0x0D
    FB = 0x0E
    SFB = 0x0F

    @property
    def is_data(self) -> bool:
        """Whether the body at offset 36 holds data instead of MC7 code."""
        return self in (BlockType.DB, BlockType.SDB)


class BlockAttributes(IntFlag):
    """Attribute bits of header offset 3.

    Values are those of the ``S7BlockAtributes`` enum in ToolBox ``S7Block.cs``.
    rz reads the byte without naming its bits.
    """

    LINKED = 0x01
    """The block is linked into execution.

    According to ToolBox this bit is clear while a code block has been
    downloaded but not yet linked, and for a DB marked "unlinked".
    """
    STANDARD_BLOCK = 0x02
    """The block is a standard block from the default library."""
    KNOW_HOW_PROTECTED = 0x08
    """The block is know-how protected."""
    NON_RETAIN = 0x20
    """The block is not retentive."""
    F_BLOCK = 0x40
    """The block is a safety block of a safety PLC."""


KNOWN_ATTRIBUTE_BITS = sum(flag.value for flag in BlockAttributes)
"""Mask of the attribute bits that ToolBox documents."""

LANGUAGE_NAMES: dict[int, str] = {
    1: "STL",
    2: "LAD",
    3: "FBD",
    4: "SCL",
    5: "DB",
    6: "GRAPH",
}
"""Language codes of header offset 4 on which both sources agree.

Code 7 is disputed: rz ``mc7_lang`` calls it SDB, ToolBox ``PLCLanguage.cs``
calls it CFC and adds 8 (SFC) and 31 to 35 (FAWL, FKOP, FFUP, FDB, FCALL).
Codes outside this table are therefore reported as plain numbers.
"""


@dataclass(frozen=True, slots=True)
class S7Timestamp:
    """A 6-byte header timestamp.

    The encoding is a big-endian u32 of milliseconds since midnight followed by
    a big-endian u16 of days since 1984-01-01 (rz ``mc7_parse_s7_date``,
    ToolBox ``Helper.GetDT``).

    Attributes:
        milliseconds: Milliseconds since midnight.
        days: Days since 1984-01-01.
    """

    milliseconds: int
    days: int

    @classmethod
    def from_bytes(cls, data: bytes) -> S7Timestamp:
        """Decode the 6 wire bytes."""
        if len(data) != _TIMESTAMP.size:
            raise ImageFormatError(f"a timestamp is {_TIMESTAMP.size} bytes, got {len(data)}")
        milliseconds, days = _TIMESTAMP.unpack(data)
        return cls(milliseconds, days)

    def to_bytes(self) -> bytes:
        """Encode to the 6 wire bytes."""
        return _pack(_TIMESTAMP, "timestamp", self.milliseconds, self.days)

    @classmethod
    def from_datetime(cls, moment: datetime) -> S7Timestamp:
        """Encode a point in time; anything below a millisecond is dropped.

        Raises:
            ImageFormatError: If the date is outside 1984-01-01 to 2163-06-06.
        """
        days = (moment.date() - S7_EPOCH.date()).days
        if not 0 <= days <= 0xFFFF:
            raise ImageFormatError(f"{moment.date()} is outside the range of a block timestamp")
        midnight = moment.replace(hour=0, minute=0, second=0, microsecond=0)
        return cls((moment - midnight) // timedelta(milliseconds=1), days)

    def to_datetime(self) -> datetime:
        """Return the point in time as a naive :class:`~datetime.datetime`."""
        return S7_EPOCH + timedelta(days=self.days, milliseconds=self.milliseconds)


@dataclass(frozen=True, slots=True)
class BlockHeader:
    """The raw fields of the 36-byte block header, in wire order.

    Every attribute holds the value exactly as stored; the properties add the
    decoded views. See the module docstring for offsets and sources.

    Attributes:
        version: Block version byte (offset 2).
        attributes: Attribute bits (offset 3).
        language: Language code (offset 4).
        type_code: Block type code (offset 5).
        number: Block number (offset 6).
        length: Declared size of the whole image (offset 8).
        password: The four password bytes (offset 12).
        modified: Time of the last code change (offset 16).
        interface_modified: Time of the last interface change (offset 22).
        interface_length: Declared length of the interface section (offset 28).
        segment_table_length: Declared length of the segment table (offset 30).
        local_data_length: Size of the local data the block needs (offset 32).
        mc7_length: Declared length of the MC7 code or DB body (offset 34).
    """

    version: int
    attributes: int
    language: int
    type_code: int
    number: int
    length: int
    password: bytes
    modified: S7Timestamp
    interface_modified: S7Timestamp
    interface_length: int
    segment_table_length: int
    local_data_length: int
    mc7_length: int

    @classmethod
    def from_bytes(cls, data: bytes) -> BlockHeader:
        """Decode the first 36 bytes of an image.

        Raises:
            ImageFormatError: If there are fewer than 36 bytes or the signature is wrong.
        """
        if len(data) < HEADER_SIZE:
            raise ImageFormatError(
                f"a block header is {HEADER_SIZE} bytes, only {len(data)} available"
            )
        (
            signature,
            version,
            attributes,
            language,
            type_code,
            number,
            length,
            password,
            modified,
            interface_modified,
            interface_length,
            segment_table_length,
            local_data_length,
            mc7_length,
        ) = _HEADER.unpack_from(data)
        if signature != SIGNATURE:
            raise ImageFormatError(
                f"signature is {bytes(signature).hex(' ')}, expected 70 70 ('pp'); "
                "this is not a block container"
            )
        return cls(
            version,
            attributes,
            language,
            type_code,
            number,
            length,
            password,
            S7Timestamp.from_bytes(modified),
            S7Timestamp.from_bytes(interface_modified),
            interface_length,
            segment_table_length,
            local_data_length,
            mc7_length,
        )

    def to_bytes(self) -> bytes:
        """Encode to the 36 wire bytes."""
        return _pack(
            _HEADER,
            "header",
            SIGNATURE,
            self.version,
            self.attributes,
            self.language,
            self.type_code,
            self.number,
            self.length,
            _fixed(self.password, 4, "password"),
            self.modified.to_bytes(),
            self.interface_modified.to_bytes(),
            self.interface_length,
            self.segment_table_length,
            self.local_data_length,
            self.mc7_length,
        )

    @property
    def block_type(self) -> BlockType | None:
        """The block type, or ``None`` for a code no source documents."""
        try:
            return BlockType(self.type_code)
        except ValueError:
            return None

    @property
    def attribute_flags(self) -> BlockAttributes:
        """The attribute byte as flags; undocumented bits are preserved."""
        return BlockAttributes(self.attributes)

    @property
    def language_name(self) -> str:
        """The language mnemonic, or the number for a code the sources do not agree on."""
        return LANGUAGE_NAMES.get(self.language, str(self.language))

    @property
    def has_password(self) -> bool:
        """Whether any password byte is non-zero."""
        return any(self.password)

    @property
    def name(self) -> str:
        """A display name such as ``OB1``; unknown types show their code."""
        block_type = self.block_type
        prefix = block_type.name if block_type else f"type 0x{self.type_code:02X} #"
        return f"{prefix}{self.number}"


@dataclass(frozen=True, slots=True)
class BlockFooter:
    """The raw fields of the 36-byte block footer, in wire order.

    Attributes:
        author: Author field, 8 bytes (offset +0).
        family: Family field, 8 bytes (offset +8).
        name: Name field, 8 bytes (offset +16).
        version: Version byte (offset +24).
        unknown_25: Byte at offset +25, not parsed by either source.
        checksum: Checksum word (offset +26).
        unknown_28: The 8 bytes at offset +28, not parsed by either source.
    """

    author: bytes
    family: bytes
    name: bytes
    version: int
    unknown_25: int
    checksum: int
    unknown_28: bytes

    @classmethod
    def from_bytes(cls, data: bytes) -> BlockFooter:
        """Decode the 36 footer bytes."""
        if len(data) != FOOTER_SIZE:
            raise ImageFormatError(f"a block footer is {FOOTER_SIZE} bytes, got {len(data)}")
        return cls(*_FOOTER.unpack(data))

    def to_bytes(self) -> bytes:
        """Encode to the 36 wire bytes."""
        return _pack(
            _FOOTER,
            "footer",
            _fixed(self.author, 8, "author"),
            _fixed(self.family, 8, "family"),
            _fixed(self.name, 8, "name"),
            self.version,
            self.unknown_25,
            self.checksum,
            _fixed(self.unknown_28, 8, "footer tail"),
        )

    @property
    def author_text(self) -> str:
        """The author with padding removed."""
        return _text(self.author)

    @property
    def family_text(self) -> str:
        """The family with padding removed."""
        return _text(self.family)

    @property
    def name_text(self) -> str:
        """The name with padding removed."""
        return _text(self.name)

    @property
    def version_text(self) -> str:
        """The version as ``major.minor`` (ToolBox ``Helper.GetVersion``)."""
        return f"{self.version >> 4}.{self.version & 0x0F}"


@dataclass(frozen=True, slots=True)
class Section:
    """One contiguous region of an image, for reports.

    Attributes:
        name: Stable identifier of the region.
        offset: Offset of the first byte from the start of the image.
        data: The bytes of the region.
    """

    name: str
    offset: int
    data: bytes


@dataclass(frozen=True, slots=True)
class BlockImage:
    """A complete block container, split into regions that concatenate back losslessly.

    The sections hold whatever bytes are actually there. The header holds what
    the image declares about them. :attr:`declared_layout_fits` tells whether
    the two agree.

    Attributes:
        header: The 36-byte header.
        payload: MC7 code of a code block, or the body of a data block.
        interface: The interface section, undecoded.
        segment_table: The segment table, undecoded.
        trailing_unknown: Bytes between the declared sections and the footer
            that no header length field accounts for.
        footer: The last 36 bytes.
    """

    header: BlockHeader
    payload: bytes
    interface: bytes
    segment_table: bytes
    trailing_unknown: bytes
    footer: BlockFooter

    def to_bytes(self) -> bytes:
        """Serialize the image; the inverse of :func:`parse_image`."""
        return b"".join(
            (
                self.header.to_bytes(),
                self.payload,
                self.interface,
                self.segment_table,
                self.trailing_unknown,
                self.footer.to_bytes(),
            )
        )

    @property
    def size(self) -> int:
        """Actual size of the image in bytes."""
        return (
            HEADER_SIZE
            + len(self.payload)
            + len(self.interface)
            + len(self.segment_table)
            + len(self.trailing_unknown)
            + FOOTER_SIZE
        )

    @property
    def declared_layout_fits(self) -> bool:
        """Whether every section has exactly the length its header field declares."""
        return (
            len(self.payload) == self.header.mc7_length
            and len(self.interface) == self.header.interface_length
            and len(self.segment_table) == self.header.segment_table_length
        )

    def sections(self) -> tuple[Section, ...]:
        """Return all regions in image order with their offsets."""
        regions = (
            ("header", self.header.to_bytes()),
            ("payload", self.payload),
            ("interface", self.interface),
            ("segment_table", self.segment_table),
            ("trailing_unknown", self.trailing_unknown),
            ("footer", self.footer.to_bytes()),
        )
        sections = []
        offset = 0
        for name, data in regions:
            sections.append(Section(name, offset, data))
            offset += len(data)
        return tuple(sections)


def parse_image(data: bytes) -> BlockImage:
    """Split a block image into its typed fields and raw sections.

    The length field at offset 8 is not enforced, and bytes that the header
    does not account for are kept in :attr:`BlockImage.trailing_unknown`.
    Use :func:`mc7asm.validate.validate_image` to learn about such deviations.
    ``parse_image(data).to_bytes() == data`` holds for every accepted input.

    Raises:
        ImageFormatError: If the data is too short to hold a header and a
            footer, or does not start with the block signature.
    """
    if len(data) < MIN_IMAGE_SIZE:
        raise ImageFormatError(
            f"a block image needs at least {MIN_IMAGE_SIZE} bytes "
            f"({HEADER_SIZE}-byte header and {FOOTER_SIZE}-byte footer), got {len(data)}"
        )
    header = BlockHeader.from_bytes(data)
    body = data[HEADER_SIZE : len(data) - FOOTER_SIZE]
    payload, interface, segment_table, trailing = _split_body(
        body, (header.mc7_length, header.interface_length, header.segment_table_length)
    )
    footer = BlockFooter.from_bytes(data[len(data) - FOOTER_SIZE :])
    return BlockImage(header, payload, interface, segment_table, trailing, footer)


def _split_body(body: bytes, lengths: tuple[int, int, int]) -> tuple[bytes, bytes, bytes, bytes]:
    """Slice the declared sections off ``body`` in order and return the rest last.

    Slicing stops at the first section that does not fit: that section and the
    ones after it stay empty and their bytes end up in the rest, so nothing is
    guessed and nothing is lost.
    """
    sections: list[bytes] = []
    offset = 0
    fits = True
    for length in lengths:
        fits = fits and offset + length <= len(body)
        if fits:
            sections.append(body[offset : offset + length])
            offset += length
        else:
            sections.append(b"")
    return sections[0], sections[1], sections[2], body[offset:]


def _pack(layout: struct.Struct, what: str, *values: object) -> bytes:
    try:
        return layout.pack(*values)
    except struct.error as exc:
        raise ImageFormatError(f"{what} field out of range: {exc}") from exc


def _fixed(data: bytes, size: int, what: str) -> bytes:
    if len(data) != size:
        raise ImageFormatError(f"{what} must be exactly {size} bytes, got {len(data)}")
    return data


def _text(raw: bytes) -> str:
    """Decode a padded text field the way ToolBox ``Helper.GetString`` does."""
    return raw.decode("latin-1").replace("\x00", "").strip()
