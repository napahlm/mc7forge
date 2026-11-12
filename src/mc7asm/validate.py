"""Field-level consistency checks on a block image.

Validation never raises for a questionable image. It returns findings, so the
same image can still be dumped and re-serialized. Checks on assembler source
will be added here once the parser exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from mc7asm.image import (
    FOOTER_SIZE,
    HEADER_SIZE,
    KNOWN_ATTRIBUTE_BITS,
    LANGUAGE_NAMES,
    BlockImage,
)


class Severity(Enum):
    """How much a finding matters."""

    NOTE = "note"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class Finding:
    """One observation about an image.

    Attributes:
        severity: How much it matters.
        code: Stable identifier, usable in tests and scripts.
        message: Human-readable explanation with the numbers involved.
    """

    severity: Severity
    code: str
    message: str


def validate_image(image: BlockImage) -> list[Finding]:
    """Compare what the header declares with what the image contains.

    The length field and unaccounted bytes are reported, not rejected: they are
    the signals used to check the documented layout against real blocks.
    """
    header = image.header
    findings: list[Finding] = []

    def add(severity: Severity, code: str, message: str) -> None:
        findings.append(Finding(severity, code, message))

    if header.length != image.size:
        add(
            Severity.WARNING,
            "length-field",
            f"block length field says {header.length} bytes, the image is {image.size} bytes",
        )
    declared = header.mc7_length + header.interface_length + header.segment_table_length
    available = image.size - HEADER_SIZE - FOOTER_SIZE
    if not image.declared_layout_fits:
        add(
            Severity.ERROR,
            "sections-overrun",
            f"declared sections need {declared} bytes (MC7 {header.mc7_length}, interface "
            f"{header.interface_length}, segment table {header.segment_table_length}) but only "
            f"{available} lie between header and footer; the sections that do not fit are "
            "left in the trailing unknown region",
        )
    elif image.trailing_unknown:
        add(
            Severity.NOTE,
            "trailing-unknown",
            f"{len(image.trailing_unknown)} byte(s) between the declared sections and the "
            "footer are not accounted for by any header length field",
        )
    if header.block_type is None:
        add(
            Severity.WARNING,
            "unknown-block-type",
            f"block type code 0x{header.type_code:02X} is not documented",
        )
    if header.language not in LANGUAGE_NAMES:
        add(
            Severity.NOTE,
            "unknown-language",
            f"language code {header.language} is not one the references agree on",
        )
    unknown_bits = header.attributes & ~KNOWN_ATTRIBUTE_BITS
    if unknown_bits:
        add(
            Severity.NOTE,
            "unknown-attribute-bits",
            f"attribute bits 0x{unknown_bits:02X} are not documented",
        )
    return findings
