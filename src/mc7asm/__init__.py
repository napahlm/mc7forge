"""Assembler toolchain for S7-300 MC7 blocks.

Implemented so far: the block container model (:mod:`mc7asm.image`) with its
validation, the opcode table (:mod:`mc7asm.opcodes`), the disassembler
(:mod:`mc7asm.disasm`), the STL front end (:mod:`mc7asm.lexer`,
:mod:`mc7asm.parser`, :mod:`mc7asm.ir`) and the code generator
(:mod:`mc7asm.codegen`) for straight-line code. Wrapping generated code into a
block container (:mod:`mc7asm.container`) is still an interface only.

This package is pure software: it never imports the PLC communication layer.
"""

from mc7asm.codegen import CompiledBlock, compile_block, compile_instruction
from mc7asm.disasm import Disassembly, disassemble
from mc7asm.errors import (
    CodegenError,
    ImageFormatError,
    Mc7AsmError,
    Mc7SyntaxError,
    NotYetImplementedError,
    NotYetSupportedError,
    UnsupportedBlockError,
)
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
from mc7asm.opcodes import Mnemonics
from mc7asm.parser import parse_file, parse_source, parse_statement
from mc7asm.source import SourceLocation
from mc7asm.validate import Finding, Severity, validate_image

__version__ = "0.1.0"

__all__ = [
    "BlockAttributes",
    "BlockFooter",
    "BlockHeader",
    "BlockImage",
    "BlockType",
    "CodegenError",
    "CompiledBlock",
    "Disassembly",
    "Finding",
    "ImageFormatError",
    "Mc7AsmError",
    "Mc7SyntaxError",
    "Mnemonics",
    "NotYetImplementedError",
    "NotYetSupportedError",
    "S7Timestamp",
    "Section",
    "Severity",
    "SourceLocation",
    "UnsupportedBlockError",
    "__version__",
    "compile_block",
    "compile_instruction",
    "disassemble",
    "parse_file",
    "parse_image",
    "parse_source",
    "parse_statement",
    "validate_image",
]
