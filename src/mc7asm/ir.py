"""Typed intermediate representation of an STL block.

The IR is what the parser produces and the code generator consumes. It is a
tree of four levels: :class:`Block`, :class:`Network`, :class:`Instruction`
and operand. It is always in international spelling; German source is
translated by the parser.

Design rules
------------
* One small class per instruction family. The class fixes which operand kinds
  are possible, so an instruction that makes no sense cannot be built.
* The instruction list of a network is flat. ``A(`` and ``)`` are instructions
  like any other, exactly as in MC7.
* Every node carries a :class:`~mc7asm.source.SourceLocation`. Locations and
  comments do not take part in equality, so two nodes are equal when they mean
  the same.
* To add a family (jumps are next), add one instruction class and, if needed,
  one operand class. Existing classes stay untouched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from mc7asm.image import BlockType
from mc7asm.notation import Notation
from mc7asm.source import NO_LOCATION, SourceLocation


class Area(Enum):
    """Memory areas an operand can address."""

    I = "I"  # noqa: E741
    Q = "Q"
    M = "M"
    DB = "DB"
    DI = "DI"
    L = "L"
    PI = "PI"
    PQ = "PQ"


class Width(Enum):
    """Width of a byte, word or double word operand; the value is its letter."""

    BYTE = "B"
    WORD = "W"
    DWORD = "D"


class IntWidth(Enum):
    """Width of an integer constant."""

    INT = "INT"
    DINT = "DINT"


# ---------------------------------------------------------------------- operands


@dataclass(frozen=True, slots=True)
class BitAddress:
    """A single bit: ``I 0.0``, ``DBX 2.1`` or the qualified ``DB1.DBX 2.1``.

    Attributes:
        area: I, Q, M, L, DB or DI.
        byte: Byte offset.
        bit: Bit number 0-7.
        db: Data block number of a fully qualified address, else ``None``.
        location: Where the operand starts in the source.
    """

    area: Area
    byte: int
    bit: int
    db: int | None = None
    location: SourceLocation = field(default=NO_LOCATION, compare=False, kw_only=True)

    @property
    def area_name(self) -> str:
        """The area as spelled in STL and in the opcode table: ``I``, ``DBX``, ``DIX``."""
        return f"{self.area.value}X" if self.area in (Area.DB, Area.DI) else self.area.value


@dataclass(frozen=True, slots=True)
class DataAddress:
    """A byte, word or double word: ``QW 4``, ``DBD 8`` or the qualified ``DB1.DBD 8``.

    Attributes:
        area: Any area.
        width: Byte, word or double word.
        byte: Byte offset.
        db: Data block number of a fully qualified address, else ``None``.
        location: Where the operand starts in the source.
    """

    area: Area
    width: Width
    byte: int
    db: int | None = None
    location: SourceLocation = field(default=NO_LOCATION, compare=False, kw_only=True)

    @property
    def area_name(self) -> str:
        """The area with its width letter: ``QW``, ``DBD``, ``PIB``."""
        return f"{self.area.value}{self.width.value}"


@dataclass(frozen=True, slots=True)
class CounterAddress:
    """A counter: ``C 5``.

    Attributes:
        number: Counter number.
        location: Where the operand starts in the source.
    """

    number: int
    location: SourceLocation = field(default=NO_LOCATION, compare=False, kw_only=True)

    @property
    def area_name(self) -> str:
        """The area as spelled in STL: ``C``."""
        return "C"


@dataclass(frozen=True, slots=True)
class BoolConstant:
    """``TRUE`` or ``FALSE``."""

    value: bool
    location: SourceLocation = field(default=NO_LOCATION, compare=False, kw_only=True)


@dataclass(frozen=True, slots=True)
class IntConstant:
    """An integer: ``100`` is an INT, ``L#100`` a DINT."""

    value: int
    width: IntWidth = IntWidth.INT
    location: SourceLocation = field(default=NO_LOCATION, compare=False, kw_only=True)


@dataclass(frozen=True, slots=True)
class RealConstant:
    """A floating point number: ``1.5``."""

    value: float
    location: SourceLocation = field(default=NO_LOCATION, compare=False, kw_only=True)


@dataclass(frozen=True, slots=True)
class TypedConstant:
    """A constant written with a type prefix, for example ``W#16#1F`` or ``S5T#2S``.

    Attributes:
        notation: The prefix family.
        value: The value as defined by :mod:`mc7asm.notation` for that notation.
        size: Encoded size in bytes: 1, 2 or 4.
        location: Where the operand starts in the source.
    """

    notation: Notation
    value: int
    size: int
    location: SourceLocation = field(default=NO_LOCATION, compare=False, kw_only=True)


Constant = BoolConstant | IntConstant | RealConstant | TypedConstant
Operand = BitAddress | DataAddress | CounterAddress | Constant

# ---------------------------------------------------------------------- instructions


class BitOp(Enum):
    """Bit logic operations."""

    A = "A"
    AN = "AN"
    O = "O"  # noqa: E741
    ON = "ON"


class WriteOp(Enum):
    """Operations that write the result of logic operation to a bit."""

    ASSIGN = "="
    SET = "S"
    RESET = "R"


class EdgeOp(Enum):
    """Edge detection operations."""

    FP = "FP"
    FN = "FN"


class CounterOp(Enum):
    """Operations on a counter."""

    CU = "CU"
    CD = "CD"
    LC = "LC"


@dataclass(frozen=True, slots=True, kw_only=True)
class Instruction:
    """Base of all instructions.

    Attributes:
        location: Where the mnemonic starts in the source.
        comment: Text of a trailing ``//`` comment, without the slashes.
    """

    location: SourceLocation = field(default=NO_LOCATION, compare=False)
    comment: str = field(default="", compare=False)

    @property
    def mnemonic(self) -> str:
        """The operation in international spelling, as used in the opcode table."""
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class BitLogic(Instruction):
    """``A``, ``AN``, ``O`` or ``ON`` on a bit."""

    op: BitOp
    operand: BitAddress

    @property
    def mnemonic(self) -> str:
        """The operation in international spelling."""
        return self.op.value


@dataclass(frozen=True, slots=True)
class NestOpen(Instruction):
    """``A(``, ``AN(``, ``O(`` or ``ON(``: open a nested expression."""

    op: BitOp

    @property
    def mnemonic(self) -> str:
        """The operation in international spelling."""
        return f"{self.op.value}("


@dataclass(frozen=True, slots=True)
class NestClose(Instruction):
    """``)``: close the innermost nested expression."""

    @property
    def mnemonic(self) -> str:
        """The operation in international spelling."""
        return ")"


@dataclass(frozen=True, slots=True)
class BitWrite(Instruction):
    """``=``, ``S`` or ``R`` on a bit."""

    op: WriteOp
    operand: BitAddress

    @property
    def mnemonic(self) -> str:
        """The operation in international spelling."""
        return self.op.value


@dataclass(frozen=True, slots=True)
class EdgeDetect(Instruction):
    """``FP`` or ``FN`` with its edge memory bit."""

    op: EdgeOp
    operand: BitAddress

    @property
    def mnemonic(self) -> str:
        """The operation in international spelling."""
        return self.op.value


@dataclass(frozen=True, slots=True)
class Load(Instruction):
    """``L``: load an address or a constant into accumulator 1."""

    operand: DataAddress | Constant

    @property
    def mnemonic(self) -> str:
        """The operation in international spelling."""
        return "L"


@dataclass(frozen=True, slots=True)
class Transfer(Instruction):
    """``T``: transfer accumulator 1 to an address."""

    operand: DataAddress

    @property
    def mnemonic(self) -> str:
        """The operation in international spelling."""
        return "T"


@dataclass(frozen=True, slots=True)
class CounterControl(Instruction):
    """``CU``, ``CD`` or ``LC`` on a counter."""

    op: CounterOp
    operand: CounterAddress

    @property
    def mnemonic(self) -> str:
        """The operation in international spelling."""
        return self.op.value


@dataclass(frozen=True, slots=True)
class BlockEnd(Instruction):
    """``BE``: end of the block."""

    @property
    def mnemonic(self) -> str:
        """The operation in international spelling."""
        return "BE"


def operand_of(instruction: Instruction) -> Operand | None:
    """Return the operand of an instruction, or ``None`` if it has none."""
    operand: Operand | None = getattr(instruction, "operand", None)
    return operand


# ---------------------------------------------------------------------- structure


@dataclass(frozen=True, slots=True)
class Network:
    """A network: a titled group of instructions.

    Attributes:
        instructions: The statements in execution order.
        title: Text of the ``TITLE =`` line, ``""`` if absent.
        comment: The comment lines between the title and the first statement.
        location: Where the ``NETWORK`` keyword is.
    """

    instructions: tuple[Instruction, ...]
    title: str = ""
    comment: tuple[str, ...] = field(default=(), compare=False)
    location: SourceLocation = field(default=NO_LOCATION, compare=False, kw_only=True)


@dataclass(frozen=True, slots=True)
class Block:
    """A code block as written in source.

    Attributes:
        block_type: OB, FC or FB.
        number: Block number.
        networks: The networks in order.
        title: Text of the block ``TITLE =`` line, ``""`` if absent.
        location: Where the block keyword is.
    """

    block_type: BlockType
    number: int
    networks: tuple[Network, ...]
    title: str = ""
    location: SourceLocation = field(default=NO_LOCATION, compare=False, kw_only=True)

    @property
    def name(self) -> str:
        """The block name, for example ``OB1``."""
        return f"{self.block_type.name}{self.number}"
