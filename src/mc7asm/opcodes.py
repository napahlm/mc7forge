"""Opcode table: the mapping between STL operations and MC7 encodings.

The table will be derived from the same public references as the block layout
(rz-libmc7 ``src/simatic.c`` and DotNetSiemensPLCToolBoxLibrary
``MC7toAWL.cs``). It is the single place where encodings are defined, shared by
the encoder and the disassembler.

Interface only in this stage; no MC7 opcode is encoded or decoded yet.
"""

from __future__ import annotations

from mc7asm.errors import NotYetImplementedError
from mc7asm.ir import Instruction


def encode_instruction(instruction: Instruction) -> bytes:
    """Return the MC7 bytes of one instruction."""
    raise NotYetImplementedError("MC7 instruction encoding")


def decode_instruction(code: bytes, offset: int) -> tuple[Instruction, int]:
    """Decode the instruction at ``offset`` and return it with its length in bytes."""
    raise NotYetImplementedError("MC7 instruction decoding")
