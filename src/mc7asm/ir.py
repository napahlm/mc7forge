"""Intermediate representation shared by the parser, the encoder and the disassembler.

The IR is the hand-over format of the pipeline::

    STL source --lexer--> tokens --parser--> IR --opcodes--> MC7 --container--> image
    image --disasm--> IR

It describes a block as networks of instructions and stays free of encoding
details, so the same structures serve assembly and disassembly.
"""

from __future__ import annotations

from dataclasses import dataclass

from mc7asm.image import BlockType


@dataclass(frozen=True, slots=True)
class Instruction:
    """One STL statement.

    Attributes:
        mnemonic: Operation in international mnemonics, for example ``A`` or ``JC``.
        operand: Operand text as written, or ``None`` for operations without one.
        label: Jump label defined on this statement, if any.
        line: 1-based source line, 0 when the instruction did not come from source.
    """

    mnemonic: str
    operand: str | None = None
    label: str | None = None
    line: int = 0


@dataclass(frozen=True, slots=True)
class Network:
    """A network: the unit the segment table of a block refers to.

    Attributes:
        instructions: The statements of the network, in execution order.
        title: Network title from the source; not stored in the online block.
    """

    instructions: tuple[Instruction, ...]
    title: str = ""


@dataclass(frozen=True, slots=True)
class BlockSource:
    """A code block as the assembler sees it.

    Attributes:
        block_type: OB, FC or FB.
        number: Block number.
        networks: The networks of the block, in order.
    """

    block_type: BlockType
    number: int
    networks: tuple[Network, ...]
