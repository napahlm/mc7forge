"""Plain-text field and hex report of a block image, as printed by ``mc7asm dump``."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from mc7asm.image import (
    FOOTER_SIZE,
    HEADER_SIZE,
    KNOWN_ATTRIBUTE_BITS,
    SIGNATURE,
    BlockAttributes,
    BlockFooter,
    BlockHeader,
    BlockImage,
    S7Timestamp,
)
from mc7asm.validate import Finding

_BYTES_PER_LINE = 16

Row = tuple[str, str, bytes, str]


def render_dump(label: str, image: BlockImage, findings: Sequence[Finding]) -> str:
    """Render the complete report for one image.

    Args:
        label: How to refer to the image in the first line, usually the file path.
        image: The parsed image.
        findings: Result of :func:`mc7asm.validate.validate_image` for it.
    """
    header = image.header
    payload_title = _payload_title(header)
    titles = {
        "payload": payload_title,
        "interface": "Interface",
        "segment_table": "Segment table",
        "trailing_unknown": "Trailing unknown",
    }
    offsets = {section.name: section.offset for section in image.sections()}
    width = max(4, len(f"{image.size:x}"))

    lines = [f"{label}: {header.name}, {image.size} bytes", ""]
    lines += [
        _region_title("Header", 0, HEADER_SIZE),
        *_table(_header_rows(header, payload_title)),
        "",
    ]
    lines += ["Sections", *_section_rows(image, titles, width), ""]
    for section in image.sections():
        if section.name in titles:
            lines.append(_region_title(titles[section.name], section.offset, len(section.data)))
            lines += _hexdump(section.data, section.offset, width)
            lines.append("")
    footer_offset = offsets["footer"]
    lines += [
        _region_title("Footer", footer_offset, FOOTER_SIZE),
        *_table(_footer_rows(image.footer)),
        "",
        "Findings",
        *_finding_rows(findings),
    ]
    return "\n".join(lines) + "\n"


def _payload_title(header: BlockHeader) -> str:
    block_type = header.block_type
    if block_type is None:
        return "Payload"
    return "Data" if block_type.is_data else "MC7 code"


def _region_title(title: str, offset: int, size: int) -> str:
    return f"{title} (offset 0x{offset:04x}, {size} bytes)"


def _header_rows(header: BlockHeader, payload_title: str) -> list[Row]:
    def word(value: int, size: int) -> bytes:
        return value.to_bytes(size, "big")

    return [
        ("0", "signature", SIGNATURE, SIGNATURE.decode("ascii")),
        ("2", "block version", word(header.version, 1), str(header.version)),
        ("3", "attributes", word(header.attributes, 1), _attributes(header)),
        ("4", "language", word(header.language, 1), header.language_name),
        ("5", "block type", word(header.type_code, 1), _block_type(header)),
        ("6", "block number", word(header.number, 2), str(header.number)),
        ("8", "block length", word(header.length, 4), str(header.length)),
        ("12", "password", header.password, "set" if header.has_password else "not set"),
        ("16", "last modified", header.modified.to_bytes(), _time(header.modified)),
        (
            "22",
            "last interface change",
            header.interface_modified.to_bytes(),
            _time(header.interface_modified),
        ),
        ("28", "interface length", word(header.interface_length, 2), str(header.interface_length)),
        (
            "30",
            "segment table length",
            word(header.segment_table_length, 2),
            str(header.segment_table_length),
        ),
        (
            "32",
            "local data length",
            word(header.local_data_length, 2),
            str(header.local_data_length),
        ),
        ("34", f"{payload_title} length", word(header.mc7_length, 2), str(header.mc7_length)),
    ]


def _footer_rows(footer: BlockFooter) -> list[Row]:
    return [
        ("+0", "author", footer.author, repr(footer.author_text)),
        ("+8", "family", footer.family, repr(footer.family_text)),
        ("+16", "name", footer.name, repr(footer.name_text)),
        ("+24", "version", bytes((footer.version,)), footer.version_text),
        ("+25", "unknown", bytes((footer.unknown_25,)), ""),
        ("+26", "checksum", footer.checksum.to_bytes(2, "big"), f"0x{footer.checksum:04X}"),
        ("+28", "unknown", footer.unknown_28, ""),
    ]


def _attributes(header: BlockHeader) -> str:
    flags = header.attribute_flags
    names = [flag.name for flag in BlockAttributes if flag in flags and flag.name]
    unknown = header.attributes & ~KNOWN_ATTRIBUTE_BITS
    if unknown:
        names.append(f"0x{unknown:02X}")
    return " | ".join(names) if names else "none"


def _block_type(header: BlockHeader) -> str:
    block_type = header.block_type
    return block_type.name if block_type else f"0x{header.type_code:02X}"


def _time(timestamp: S7Timestamp) -> str:
    return timestamp.to_datetime().isoformat(sep=" ", timespec="milliseconds")


def _table(rows: Sequence[Row]) -> list[str]:
    """Align rows of (offset, field, raw bytes, decoded value)."""
    cells = [("off", "field", "raw", "decoded")] + [
        (offset, field, raw.hex(" "), decoded) for offset, field, raw, decoded in rows
    ]
    widths = [max(len(row[column]) for row in cells) for column in range(3)]
    return [
        f"  {offset:>{widths[0]}}  {field:<{widths[1]}}  {raw:<{widths[2]}}  {decoded}".rstrip()
        for offset, field, raw, decoded in cells
    ]


def _section_rows(image: BlockImage, titles: dict[str, str], width: int) -> list[str]:
    names = {"header": "Header", "footer": "Footer", **titles}
    rows = [
        (f"0x{section.offset:0{width}x}", str(len(section.data)), names[section.name])
        for section in image.sections()
    ]
    cells = [("offset", "size", "section"), *rows]
    widths = [max(len(row[column]) for row in cells) for column in range(2)]
    return [f"  {offset:>{widths[0]}}  {size:>{widths[1]}}  {name}" for offset, size, name in cells]


def _hexdump(data: bytes, base: int, width: int) -> list[str]:
    if not data:
        return ["  (empty)"]
    lines = []
    for start in range(0, len(data), _BYTES_PER_LINE):
        chunk = data[start : start + _BYTES_PER_LINE]
        halves = (chunk[:8].hex(" "), chunk[8:].hex(" "))
        text = "".join(chr(byte) if 0x20 <= byte < 0x7F else "." for byte in chunk)
        lines.append(f"  {base + start:0{width}x}  {halves[0]:<23}  {halves[1]:<23}  |{text}|")
    return lines


def _finding_rows(findings: Iterable[Finding]) -> list[str]:
    rows = [
        f"  {finding.severity.value}: {finding.message} [{finding.code}]" for finding in findings
    ]
    return rows or ["  none"]
