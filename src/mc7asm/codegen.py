"""Code generator: turns IR instructions into MC7 bytes with the opcode table.

For every instruction the generator selects a row of
:data:`mc7asm.opcodes.OPCODE_TABLE` by mnemonic and operand, then fills the
operand into the bits the row leaves open. Nothing is encoded that is not in
the table.

Rules
-----
* When several rows fit, the shortest encoding wins. This is what the
  reference block shows for real code: ``A I 0.1`` is the 2-byte ``c1 00``.
* Rows marked :attr:`~mc7asm.opcodes.Status.UNVERIFIED` are not used. Their
  meaning is disputed between the sources, so assembling them could produce
  wrong code without any sign of it.
* Only straight-line code is generated. Whatever has no row yet (nesting,
  fully qualified data block addresses, ``TRUE``/``FALSE``, jumps) raises
  :class:`~mc7asm.errors.NotYetSupportedError` with the source location.
* The body is exactly the instructions of the source. No ``BE`` is appended;
  the block container of the next stage decides how a block is closed.
"""

from __future__ import annotations

import struct
from collections.abc import Callable
from dataclasses import dataclass

from mc7asm import ir
from mc7asm.errors import CodegenError, NotYetSupportedError
from mc7asm.notation import S5TIME_MAX_COUNT, Notation, encode_bcd, encode_s5time
from mc7asm.opcodes import OPCODE_TABLE, OpcodeRow, Operand, Status
from mc7asm.printer import format_instruction


@dataclass(frozen=True, slots=True)
class CompiledInstruction:
    """One instruction with its encoding.

    Attributes:
        instruction: The IR instruction.
        row: The opcode row that encoded it.
        data: The MC7 bytes.
        offset: Offset of the first byte inside the block body.
    """

    instruction: ir.Instruction
    row: OpcodeRow
    data: bytes
    offset: int


@dataclass(frozen=True, slots=True)
class CompiledNetwork:
    """The instructions of one network with their place in the body.

    Attributes:
        network: The IR network.
        number: 1-based network number.
        offset: Offset of the network inside the block body.
        instructions: The compiled instructions in order.
    """

    network: ir.Network
    number: int
    offset: int
    instructions: tuple[CompiledInstruction, ...]

    @property
    def size(self) -> int:
        """Length of the network in bytes."""
        return sum(len(instruction.data) for instruction in self.instructions)


@dataclass(frozen=True, slots=True)
class CompiledBlock:
    """The MC7 body of a block, network by network.

    Attributes:
        block: The IR block.
        networks: The compiled networks in order.
    """

    block: ir.Block
    networks: tuple[CompiledNetwork, ...]

    @property
    def body(self) -> bytes:
        """The raw MC7 code of all networks."""
        return b"".join(
            instruction.data for network in self.networks for instruction in network.instructions
        )

    @property
    def size(self) -> int:
        """Length of the body in bytes."""
        return sum(network.size for network in self.networks)


def compile_block(block: ir.Block) -> CompiledBlock:
    """Compile every network of a block and account for the length of each.

    Raises:
        CodegenError: If an operand cannot be encoded.
        NotYetSupportedError: If an instruction has no usable opcode row yet.
    """
    networks = []
    offset = 0
    for number, network in enumerate(block.networks, 1):
        start = offset
        compiled = []
        for instruction in network.instructions:
            row, data = compile_instruction(instruction)
            compiled.append(CompiledInstruction(instruction, row, data, offset))
            offset += len(data)
        networks.append(CompiledNetwork(network, number, start, tuple(compiled)))
    return CompiledBlock(block, tuple(networks))


def compile_instruction(instruction: ir.Instruction) -> tuple[OpcodeRow, bytes]:
    """Return the opcode row used for an instruction and its MC7 bytes.

    Raises:
        CodegenError: If the operand cannot be encoded.
        NotYetSupportedError: If the instruction has no usable opcode row yet.
    """
    operand = ir.operand_of(instruction)
    row = _select_row(instruction, operand)
    if row.status is Status.UNVERIFIED:
        raise NotYetSupportedError(
            f"{format_instruction(instruction)} is not yet supported: its opcode row is "
            f"unverified ({row.note})",
            instruction.location,
            hint="see docs/opcodes.md",
        )
    data = _ENCODERS[row.operand](row, operand, instruction)
    assert len(data) == row.length, (row, data)
    return row, data


# ---------------------------------------------------------------------- row selection

_ADDRESS_LIMITS = {
    Operand.BIT_LONG: 0xFFFF,
    Operand.BIT_SHORT_8: 0xFF,
    Operand.BIT_SHORT_7: 0x7F,
    Operand.ADDRESS_16: 0xFFFF,
    Operand.ADDRESS_8: 0xFF,
    Operand.ADDRESS_7: 0x7F,
}

_INT_FORMS = {ir.IntWidth.INT: (Operand.INT_16, ">h"), ir.IntWidth.DINT: (Operand.INT_32, ">i")}

_TYPED_FORMS = {
    (Notation.BYTE_HEX, 1): Operand.BYTE_HEX,
    (Notation.BINARY, 2): Operand.BINARY_16,
    (Notation.BINARY, 4): Operand.BINARY_32,
    (Notation.HEX_WORD, 2): Operand.HEX_16,
    (Notation.HEX_DWORD, 4): Operand.HEX_32,
    (Notation.CHARS, 2): Operand.CHARS_16,
    (Notation.CHARS, 4): Operand.CHARS_32,
    (Notation.BYTES, 2): Operand.BYTES_16,
    (Notation.BYTES, 4): Operand.BYTES_32,
    (Notation.COUNTER, 2): Operand.COUNTER_BCD,
    (Notation.DATE, 2): Operand.DATE,
    (Notation.S5TIME, 2): Operand.S5TIME,
    (Notation.TIME, 4): Operand.TIME,
    (Notation.TIME_OF_DAY, 4): Operand.TIME_OF_DAY,
}

AddressOperand = ir.BitAddress | ir.DataAddress | ir.CounterAddress


def _index() -> tuple[dict[tuple[str, str], list[OpcodeRow]], dict[tuple[str, Operand], OpcodeRow]]:
    by_area: dict[tuple[str, str], list[OpcodeRow]] = {}
    by_form: dict[tuple[str, Operand], OpcodeRow] = {}
    for row in OPCODE_TABLE:
        if row.operand in _ADDRESS_LIMITS:
            by_area.setdefault((row.mnemonic, row.area), []).append(row)
        else:
            by_form[(row.mnemonic, row.operand)] = row
    return by_area, by_form


_ROWS_BY_AREA, _ROWS_BY_FORM = _index()


def _select_row(instruction: ir.Instruction, operand: ir.Operand | None) -> OpcodeRow:
    text = format_instruction(instruction)
    if isinstance(instruction, ir.NestOpen | ir.NestClose):
        raise NotYetSupportedError(
            f"{text} is not yet supported: nesting operations are not in the opcode table",
            instruction.location,
            hint="write the expression without parentheses for now",
        )
    if isinstance(operand, ir.BitAddress | ir.DataAddress | ir.CounterAddress):
        return _address_row(instruction, operand, text)
    form = _constant_form(instruction, operand, text)
    row = _ROWS_BY_FORM.get((instruction.mnemonic, form))
    if row is None:
        raise NotYetSupportedError(
            f"{text} is not yet supported: the opcode table has no row for it",
            instruction.location,
        )
    return row


def _address_row(instruction: ir.Instruction, operand: AddressOperand, text: str) -> OpcodeRow:
    if not isinstance(operand, ir.CounterAddress) and operand.db is not None:
        raise NotYetSupportedError(
            f"{text} is not yet supported: a fully qualified data block address needs "
            "OPN DB, which is not in the opcode table",
            operand.location,
            hint=f"only {operand.area_name} without the DB{operand.db}. prefix can be encoded",
        )
    rows = _ROWS_BY_AREA.get((instruction.mnemonic, operand.area_name))
    if not rows:
        raise NotYetSupportedError(
            f"{text} is not yet supported: the opcode table has no row for "
            f"{instruction.mnemonic} on {operand.area_name}",
            operand.location,
        )
    address = _address(operand)
    fitting = [row for row in rows if 0 <= address <= _ADDRESS_LIMITS[row.operand]]
    if not fitting:
        limit = max(_ADDRESS_LIMITS[row.operand] for row in rows)
        raise CodegenError(
            f"{text}: address {address} is out of range",
            operand.location,
            hint=f"{instruction.mnemonic} {operand.area_name} takes 0 to {limit}",
        )
    return min(fitting, key=lambda row: row.length)


def _constant_form(instruction: ir.Instruction, operand: ir.Operand | None, text: str) -> Operand:
    if operand is None:
        return Operand.NONE
    if isinstance(operand, ir.IntConstant):
        return _INT_FORMS[operand.width][0]
    if isinstance(operand, ir.RealConstant):
        return Operand.REAL
    if isinstance(operand, ir.TypedConstant):
        form = _TYPED_FORMS.get((operand.notation, operand.size))
        if form is not None:
            return form
    reason = "this constant has no row in the opcode table"
    if isinstance(operand, ir.BoolConstant):
        reason = "TRUE and FALSE have no row in the opcode table"
    raise NotYetSupportedError(f"{text} is not yet supported: {reason}", instruction.location)


# ---------------------------------------------------------------------- encoders
#
# The inverse of the operand renderers of mc7asm.disasm: each takes the row and
# the operand and returns the complete instruction bytes.

Encoder = Callable[[OpcodeRow, "ir.Operand | None", ir.Instruction], bytes]


def _address(operand: ir.Operand | None) -> int:
    assert isinstance(operand, ir.BitAddress | ir.DataAddress | ir.CounterAddress)
    return operand.number if isinstance(operand, ir.CounterAddress) else operand.byte


def _bit(operand: ir.Operand | None, instruction: ir.Instruction) -> int:
    assert isinstance(operand, ir.BitAddress)
    if not 0 <= operand.bit <= 7:
        raise CodegenError(
            f"{format_instruction(instruction)}: bit number {operand.bit} is out of range",
            operand.location,
            hint="bits are numbered 0 to 7",
        )
    return operand.bit


def _bit_long(row: OpcodeRow, operand: ir.Operand | None, instruction: ir.Instruction) -> bytes:
    second = row.opcode[1] | _bit(operand, instruction)
    return bytes((row.opcode[0], second)) + _address(operand).to_bytes(2, "big")


def _bit_short(row: OpcodeRow, operand: ir.Operand | None, instruction: ir.Instruction) -> bytes:
    first = row.opcode[0] | _bit(operand, instruction)
    return bytes((first, row.opcode[1] | _address(operand)))


def _address_short(row: OpcodeRow, operand: ir.Operand | None, _: ir.Instruction) -> bytes:
    return bytes((row.opcode[0], row.opcode[1] | _address(operand)))


def _address_long(row: OpcodeRow, operand: ir.Operand | None, _: ir.Instruction) -> bytes:
    return row.opcode + _address(operand).to_bytes(2, "big")


def _integer(row: OpcodeRow, operand: ir.Operand | None, instruction: ir.Instruction) -> bytes:
    assert isinstance(operand, ir.IntConstant)
    try:
        return row.opcode + struct.pack(_INT_FORMS[operand.width][1], operand.value)
    except struct.error as exc:
        raise CodegenError(
            f"{format_instruction(instruction)}: {operand.value} does not fit "
            f"{operand.width.value}",
            operand.location,
        ) from exc


def _real(row: OpcodeRow, operand: ir.Operand | None, instruction: ir.Instruction) -> bytes:
    assert isinstance(operand, ir.RealConstant)
    try:
        return row.opcode + struct.pack(">f", operand.value)
    except (OverflowError, struct.error) as exc:
        raise CodegenError(
            f"{format_instruction(instruction)}: the value does not fit a 32-bit real",
            operand.location,
        ) from exc


def _typed(row: OpcodeRow, operand: ir.Operand | None, instruction: ir.Instruction) -> bytes:
    assert isinstance(operand, ir.TypedConstant)
    payload: int | None = operand.value
    if operand.notation is Notation.S5TIME:
        payload = encode_s5time(operand.value)
    elif operand.notation is Notation.COUNTER:
        payload = encode_bcd(operand.value) if 0 <= operand.value <= S5TIME_MAX_COUNT else None
    if payload is None or not 0 <= payload < 1 << 8 * operand.size:
        raise CodegenError(
            f"{format_instruction(instruction)}: the value cannot be encoded in "
            f"{operand.size} byte(s)",
            operand.location,
        )
    if operand.notation is Notation.BYTE_HEX:
        return bytes((row.opcode[0], payload))
    return row.opcode + payload.to_bytes(operand.size, "big")


_ENCODERS: dict[Operand, Encoder] = {
    Operand.NONE: lambda row, _operand, _instruction: row.opcode,
    Operand.BIT_LONG: _bit_long,
    Operand.BIT_SHORT_8: _bit_short,
    Operand.BIT_SHORT_7: _bit_short,
    Operand.ADDRESS_8: _address_short,
    Operand.ADDRESS_7: _address_short,
    Operand.ADDRESS_16: _address_long,
    Operand.INT_16: _integer,
    Operand.INT_32: _integer,
    Operand.REAL: _real,
    **dict.fromkeys(_TYPED_FORMS.values(), _typed),
}
