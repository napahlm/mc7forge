"""Turns the IR back into STL text and into the tree printed by ``mc7asm parse``."""

from __future__ import annotations

from collections.abc import Sequence

from mc7asm import ir
from mc7asm.lexer import Token, TokenKind
from mc7asm.notation import format_constant, format_real
from mc7asm.opcodes import GERMAN_AREAS, GERMAN_MNEMONICS, Mnemonics


def format_operand(operand: ir.Operand, mnemonics: Mnemonics = Mnemonics.EN) -> str:
    """Write an operand the way the disassembler does, for example ``I 0.0`` or ``W#16#1f``."""
    if isinstance(operand, ir.BitAddress | ir.DataAddress | ir.CounterAddress):
        area = operand.area_name
        if mnemonics is Mnemonics.DE:
            area = GERMAN_AREAS[area]
        if isinstance(operand, ir.CounterAddress):
            return f"{area} {operand.number}"
        prefix = f"DB{operand.db}." if operand.db is not None else ""
        bit = f".{operand.bit}" if isinstance(operand, ir.BitAddress) else ""
        return f"{prefix}{area} {operand.byte}{bit}"
    if isinstance(operand, ir.BoolConstant):
        return "TRUE" if operand.value else "FALSE"
    if isinstance(operand, ir.IntConstant):
        return str(operand.value) if operand.width is ir.IntWidth.INT else f"L#{operand.value}"
    if isinstance(operand, ir.RealConstant):
        return format_real(operand.value)
    return format_constant(operand.notation, operand.value, operand.size)


def format_mnemonic(instruction: ir.Instruction, mnemonics: Mnemonics = Mnemonics.EN) -> str:
    """Return the operation in the requested spelling."""
    name = instruction.mnemonic
    if mnemonics is Mnemonics.EN or name == ")":
        return name
    if name.endswith("("):
        return f"{GERMAN_MNEMONICS[name[:-1]]}("
    return GERMAN_MNEMONICS[name]


def format_instruction(instruction: ir.Instruction, mnemonics: Mnemonics = Mnemonics.EN) -> str:
    """Write a statement as STL text, for example ``A I 0.0``."""
    operand = ir.operand_of(instruction)
    name = format_mnemonic(instruction, mnemonics)
    return name if operand is None else f"{name} {format_operand(operand, mnemonics)}"


def render_tree(block: ir.Block) -> str:
    """Render the IR as an indented tree with the location of every node."""
    title = f' "{block.title}"' if block.title else ""
    lines = [f"Block {block.name}{title} at {block.location}"]
    for number, network in enumerate(block.networks, 1):
        title = f' "{network.title}"' if network.title else ""
        lines.append(f"  Network {number}{title} at {network.location}")
        lines += [f"    // {comment}" for comment in network.comment]
        for instruction in network.instructions:
            comment = f"  // {instruction.comment}" if instruction.comment else ""
            lines.append(
                f"    {type(instruction).__name__} {instruction.mnemonic} "
                f"at {instruction.location}{comment}"
            )
            operand = ir.operand_of(instruction)
            if operand is not None:
                lines.append(
                    f"      {type(operand).__name__} {format_operand(operand)} "
                    f"at {operand.location}"
                )
    return "\n".join(lines) + "\n"


def render_tokens(tokens: Sequence[Token]) -> str:
    """Render the token stream, one token per line."""
    rows = [
        (str(token.location), token.kind.value, repr(token.text) if token.text else "")
        for token in tokens
        if token.kind is not TokenKind.NEWLINE
    ]
    width = max(len(location) for location, _kind, _text in rows)
    return "".join(
        f"{location:<{width}}  {kind:<10}  {text}".rstrip() + "\n" for location, kind, text in rows
    )
