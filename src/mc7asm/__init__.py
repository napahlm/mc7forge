"""Assembler toolchain for S7-300 MC7 blocks.

Stage 2.0 provides the block container model (:mod:`mc7asm.image`), its
validation and the ``mc7asm dump`` command. The assembler pipeline modules
(:mod:`~mc7asm.lexer`, :mod:`~mc7asm.parser`, :mod:`~mc7asm.ir`,
:mod:`~mc7asm.opcodes`, :mod:`~mc7asm.container`, :mod:`~mc7asm.disasm`) define
their interfaces only.

This package is pure software: it never imports the PLC communication layer.
"""

from mc7asm.errors import ImageFormatError, Mc7AsmError, NotYetImplementedError
from mc7asm.image import (
    BlockAttributes,
    BlockFooter,
    BlockHeader,
    BlockImage,
    BlockType,
    S7Timestamp,
    Section,
    parse_image,
)
from mc7asm.validate import Finding, Severity, validate_image

__version__ = "0.1.0"

__all__ = [
    "BlockAttributes",
    "BlockFooter",
    "BlockHeader",
    "BlockImage",
    "BlockType",
    "Finding",
    "ImageFormatError",
    "Mc7AsmError",
    "NotYetImplementedError",
    "S7Timestamp",
    "Section",
    "Severity",
    "__version__",
    "parse_image",
    "validate_image",
]
