"""Parser: turns STL source into the typed IR.

Accepted source, one block per file::

    ORGANIZATION_BLOCK OB 1        (or FUNCTION FC 1 : VOID, FUNCTION_BLOCK FB 1)
    TITLE = optional block title
    BEGIN
    NETWORK
    TITLE = optional network title
    // optional network comment
          A     I 0.0;             // optional statement comment
          =     Q 0.0;
    END_ORGANIZATION_BLOCK

Operations: ``A AN O ON = S R FP FN`` on a bit address, ``A( AN( O( ON( )``,
``L`` with an address or a constant, ``T`` with an address, ``CU CD LC`` with a
counter and ``BE``. Addresses may be written ``I0.0`` or ``I 0.0``; the ``;``
is optional. With :attr:`~mc7asm.opcodes.Mnemonics.DE` the German spelling is
expected instead (``U``, ``UN``, ``E``, ``A``, ``ZV``, ``ZR``, ``Z``).

Declaration sections and anything else outside this subset are rejected with
a :class:`~mc7asm.errors.Mc7SyntaxError` that carries the location, the
offending text and a hint.
"""

from __future__ import annotations

import math
import re
import struct
from collections.abc import Callable
from pathlib import Path

from mc7asm import ir
from mc7asm.errors import Mc7SyntaxError
from mc7asm.image import BlockType
from mc7asm.lexer import Token, TokenKind, tokenize
from mc7asm.notation import NotationError, parse_constant
from mc7asm.opcodes import GERMAN_AREAS, GERMAN_MNEMONICS, Mnemonics
from mc7asm.source import SourceLocation

MAX_BYTE_ADDRESS = 0xFFFF
MAX_BLOCK_NUMBER = 0xFFFF
MAX_COUNTER_NUMBER = 0xFF

_BLOCKS = {
    "ORGANIZATION_BLOCK": (BlockType.OB, "END_ORGANIZATION_BLOCK"),
    "FUNCTION": (BlockType.FC, "END_FUNCTION"),
    "FUNCTION_BLOCK": (BlockType.FB, "END_FUNCTION_BLOCK"),
}
_END_KEYWORDS = frozenset(end for _type, end in _BLOCKS.values())
_HEADER_HINT = "start with ORGANIZATION_BLOCK OB 1, FUNCTION FC 1 : VOID or FUNCTION_BLOCK FB 1"

_NESTING = ("A", "AN", "O", "ON")
_INTERNATIONAL = {*GERMAN_MNEMONICS, *(f"{name}(" for name in _NESTING), ")"}
_FROM_GERMAN = {
    **{german: name for name, german in GERMAN_MNEMONICS.items()},
    **{f"{GERMAN_MNEMONICS[name]}(": f"{name}(" for name in _NESTING},
    ")": ")",
}
_AREAS_FROM_GERMAN = {german: name for name, german in GERMAN_AREAS.items()}
_SUPPORTED = "A AN O ON = S R FP FN L T CU CD LC BE A( AN( O( ON( )"

_BIT_AREAS = {"I": ir.Area.I, "Q": ir.Area.Q, "M": ir.Area.M, "L": ir.Area.L}
_BIT_AREAS |= {"DBX": ir.Area.DB, "DIX": ir.Area.DI}
_ADDRESS = re.compile(r"(?:DB(?P<db>\d+)\.)?(?P<area>[A-Z]+)(?P<byte>\d+)(?:\.(?P<bit>\d+))?")
_DATA_AREA = re.compile(r"(PI|PQ|I|Q|M|L|DB|DI)([BWD])")
_INTEGER = re.compile(r"[+-]?\d+")
_REAL = re.compile(r"[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?")
_DINT = re.compile(r"L#([+-]?\d+)", re.IGNORECASE)


def parse_file(path: Path, mnemonics: Mnemonics = Mnemonics.EN) -> ir.Block:
    """Read and parse an STL source file; locations carry ``path`` as given."""
    return parse_source(path.read_text(encoding="utf-8"), str(path), mnemonics)


def parse_source(
    source: str, file: str = "<source>", mnemonics: Mnemonics = Mnemonics.EN
) -> ir.Block:
    """Parse the STL source of one block into its intermediate representation.

    Raises:
        Mc7SyntaxError: For anything outside the supported subset.
    """
    return _BlockParser(tokenize(source, file), file, mnemonics).block()


def parse_statement(
    text: str, mnemonics: Mnemonics = Mnemonics.EN, file: str = "<statement>"
) -> ir.Instruction:
    """Parse a single statement such as ``A I 0.0``.

    Raises:
        Mc7SyntaxError: If the text is not exactly one supported statement.
    """
    lines = _lines(tokenize(text, file))
    if len(lines) != 1:
        raise Mc7SyntaxError(
            "expected exactly one statement", SourceLocation(file, 1, 1), text=text
        )
    return _StatementParser(mnemonics).statement(lines[0])


def _lines(tokens: list[Token]) -> list[list[Token]]:
    """Group tokens into the non-empty source lines."""
    lines: list[list[Token]] = [[]]
    for token in tokens:
        if token.kind in (TokenKind.NEWLINE, TokenKind.END):
            lines.append([])
        else:
            lines[-1].append(token)
    return [line for line in lines if line]


def _is_keyword(line: list[Token], *words: str) -> bool:
    return line[0].kind is TokenKind.KEYWORD and line[0].text.upper() in words


def _end_of_line(tokens: list[Token], what: str) -> None:
    """Require that only a comment is left on the line."""
    if tokens and tokens[0].kind is not TokenKind.COMMENT:
        raise Mc7SyntaxError(
            f"unexpected text {tokens[0].text!r} after {what}",
            tokens[0].location,
            text=tokens[0].text,
        )


class _BlockParser:
    """Parses the block structure and delegates statements to :class:`_StatementParser`."""

    def __init__(self, tokens: list[Token], file: str, mnemonics: Mnemonics) -> None:
        self._lines = _lines(tokens)
        self._index = 0
        self._end = tokens[-1].location
        self._file = file
        self._statements = _StatementParser(mnemonics)

    def _peek(self) -> list[Token] | None:
        return self._lines[self._index] if self._index < len(self._lines) else None

    def _next_code_line(self) -> list[Token] | None:
        """Skip comment-only lines and return the next line without consuming it."""
        while (line := self._peek()) is not None and line[0].kind is TokenKind.COMMENT:
            self._index += 1
        return line

    def block(self) -> ir.Block:
        line = self._next_code_line()
        if line is None:
            raise Mc7SyntaxError(
                "the source contains no block", SourceLocation(self._file, 1, 1), hint=_HEADER_HINT
            )
        head = line[0]
        keyword = head.text.upper()
        if head.kind is not TokenKind.KEYWORD or keyword not in _BLOCKS:
            raise Mc7SyntaxError(
                f"expected a block header, found {head.text!r}",
                head.location,
                text=head.text,
                hint=_HEADER_HINT,
            )
        block_type, end_keyword = _BLOCKS[keyword]
        number, rest = self._block_name(line, block_type)
        if block_type is BlockType.FC and rest and rest[0].text == ":":
            if len(rest) < 2 or rest[1].text.upper() != "VOID":
                offender = rest[1] if len(rest) > 1 else rest[0]
                raise Mc7SyntaxError(
                    "only functions without a return value are supported",
                    offender.location,
                    text=offender.text,
                    hint="write FUNCTION FC 1 : VOID",
                )
            rest = rest[2:]
        _end_of_line(rest, "the block header")
        self._index += 1
        title = self._title()
        self._begin()
        networks = self._networks(keyword, end_keyword)
        trailing = self._next_code_line()
        if trailing is not None:
            raise Mc7SyntaxError(
                f"unexpected text {trailing[0].text!r} after {end_keyword}",
                trailing[0].location,
                text=trailing[0].text,
                hint="a source file holds exactly one block",
            )
        return ir.Block(block_type, number, tuple(networks), title, location=head.location)

    def _block_name(self, line: list[Token], block_type: BlockType) -> tuple[int, list[Token]]:
        prefix = block_type.name
        hint = f"write {line[0].text.upper()} {prefix} 1"
        if len(line) < 2 or line[1].kind is TokenKind.COMMENT:
            raise Mc7SyntaxError(
                f"{line[0].text} needs a block name", line[0].location, text=line[0].text, hint=hint
            )
        name, rest = line[1].text, line[2:]
        if rest and rest[0].kind is TokenKind.NUMBER:
            name, rest = f"{name} {rest[0].text}", rest[1:]
        match = re.fullmatch(rf"{prefix}(\d+)", name.replace(" ", "").upper())
        if match is None or int(match[1]) > MAX_BLOCK_NUMBER:
            raise Mc7SyntaxError(
                f"{name!r} is not a valid name for this block",
                line[1].location,
                text=name,
                hint=hint,
            )
        return int(match[1]), rest

    def _title(self) -> str:
        line = self._peek()
        if line is None or not _is_keyword(line, "TITLE"):
            return ""
        if len(line) < 3 or line[1].text != "=" or line[2].kind is not TokenKind.TEXT:
            raise Mc7SyntaxError(
                "expected = after TITLE", line[0].location, text="TITLE", hint="write TITLE = text"
            )
        self._index += 1
        return line[2].text

    def _begin(self) -> None:
        line = self._next_code_line()
        if line is None:
            raise Mc7SyntaxError("expected BEGIN, found the end of the file", self._end)
        if _is_keyword(line, "BEGIN"):
            _end_of_line(line[1:], "BEGIN")
            self._index += 1
            return
        head = line[0]
        hint = "put BEGIN before the first NETWORK"
        if head.text.upper().startswith("VAR"):
            hint = (
                "declaration sections are not supported yet; remove them and use absolute addresses"
            )
        raise Mc7SyntaxError(
            f"expected BEGIN, found {head.text!r}", head.location, text=head.text, hint=hint
        )

    def _networks(self, keyword: str, end_keyword: str) -> list[ir.Network]:
        networks: list[ir.Network] = []
        while True:
            line = self._next_code_line()
            if line is None:
                raise Mc7SyntaxError(
                    f"{end_keyword} is missing",
                    self._end,
                    hint=f"close the block with {end_keyword}",
                )
            if _is_keyword(line, "NETWORK"):
                networks.append(self._network(line))
            elif _is_keyword(line, end_keyword):
                _end_of_line(line[1:], end_keyword)
                self._index += 1
                return networks
            elif _is_keyword(line, *_END_KEYWORDS):
                raise Mc7SyntaxError(
                    f"{line[0].text} does not close {keyword}",
                    line[0].location,
                    text=line[0].text,
                    hint=f"use {end_keyword}",
                )
            else:
                raise Mc7SyntaxError(
                    f"{line[0].text!r} is outside a network",
                    line[0].location,
                    text=line[0].text,
                    hint="start a network with NETWORK",
                )

    def _network(self, line: list[Token]) -> ir.Network:
        _end_of_line(line[1:], "NETWORK")
        self._index += 1
        title = self._title()
        comments: list[str] = []
        while (current := self._peek()) is not None and current[0].kind is TokenKind.COMMENT:
            comments.append(current[0].text)
            self._index += 1
        instructions: list[ir.Instruction] = []
        open_nests: list[Token] = []
        while (current := self._next_code_line()) is not None:
            if current[0].kind is TokenKind.KEYWORD:
                break
            instruction = self._statements.statement(current)
            if isinstance(instruction, ir.NestOpen):
                open_nests.append(current[0])
            elif isinstance(instruction, ir.NestClose):
                if not open_nests:
                    raise Mc7SyntaxError(
                        ") has no matching opening operation",
                        current[0].location,
                        text=")",
                        hint="open a nested expression with A(, AN(, O( or ON( first",
                    )
                open_nests.pop()
            instructions.append(instruction)
            self._index += 1
        if open_nests:
            opener = open_nests[-1]
            raise Mc7SyntaxError(
                f"{opener.text} is never closed",
                opener.location,
                text=opener.text,
                hint="add a ) before the end of the network",
            )
        return ir.Network(tuple(instructions), title, tuple(comments), location=line[0].location)


class _StatementParser:
    """Parses one statement line into an instruction."""

    def __init__(self, mnemonics: Mnemonics) -> None:
        self._german = mnemonics is Mnemonics.DE

    def statement(self, tokens: list[Token]) -> ir.Instruction:
        comment = ""
        if tokens[-1].kind is TokenKind.COMMENT:
            comment, tokens = tokens[-1].text, tokens[:-1]
        if tokens and tokens[-1].text == ";" and tokens[-1].kind is TokenKind.SYMBOL:
            tokens = tokens[:-1]
        if not tokens:
            raise Mc7SyntaxError("expected a statement", SourceLocation("<statement>", 1, 1))
        head = tokens[0]
        mnemonic = self._mnemonic(head)
        build = _BUILDERS[mnemonic]
        instruction = build(self, mnemonic, head, tokens[1:])
        return _with_comment(instruction, comment) if comment else instruction

    def _mnemonic(self, head: Token) -> str:
        written = head.text.upper()
        is_operation = head.kind is TokenKind.IDENTIFIER or (
            head.kind is TokenKind.SYMBOL and written in ("=", ")")
        )
        if not is_operation:
            raise Mc7SyntaxError(
                f"expected an operation, found {head.text!r}",
                head.location,
                text=head.text,
                hint=f"supported operations: {_SUPPORTED}",
            )
        if self._german:
            if written in _FROM_GERMAN:
                return _FROM_GERMAN[written]
            hint = "supported operations: " + " ".join(sorted(_FROM_GERMAN))
            if written in _INTERNATIONAL:
                hint = "this is international spelling; drop --mnemonics de or use the German one"
        else:
            if written in _INTERNATIONAL:
                return written
            hint = f"supported operations: {_SUPPORTED}"
            if written in _FROM_GERMAN:
                hint = "this is German spelling; use --mnemonics de"
        raise Mc7SyntaxError(
            f"unknown operation {head.text!r}", head.location, text=head.text, hint=hint
        )

    # ------------------------------------------------------------------ operands

    def _operand_text(self, head: Token, operands: list[Token], expected: str) -> tuple[str, Token]:
        """Return the operand as written (``I 0.0``) and reject anything after it."""
        if not operands:
            raise Mc7SyntaxError(f"{head.text} needs {expected}", head.location, text=head.text)
        first = operands[0]
        text, used = first.text, 1
        if (
            len(operands) > 1
            and first.kind is TokenKind.IDENTIFIER
            and operands[1].kind is TokenKind.NUMBER
        ):
            text, used = f"{text} {operands[1].text}", 2
        if len(operands) > used:
            extra = operands[used]
            raise Mc7SyntaxError(
                f"unexpected text {extra.text!r} after the operand",
                extra.location,
                text=extra.text,
                hint="write one statement per line",
            )
        return text, first

    def _address(self, text: str, token: Token) -> tuple[int | None, str, int, int | None] | None:
        """Split an address into data block, international area, byte and bit."""
        match = _ADDRESS.fullmatch(text.replace(" ", "").upper())
        if match is None:
            return None
        area = self._area(match["area"], token)
        byte = int(match["byte"])
        if byte > MAX_BYTE_ADDRESS:
            raise Mc7SyntaxError(
                f"byte address {byte} is out of range",
                token.location,
                text=text,
                hint=f"addresses go from 0 to {MAX_BYTE_ADDRESS}",
            )
        db = None
        if match["db"] is not None:
            db = int(match["db"])
            if not area.startswith("DB") or not 1 <= db <= MAX_BLOCK_NUMBER:
                raise Mc7SyntaxError(
                    f"{text!r} is not a valid data block address",
                    token.location,
                    text=text,
                    hint="a DBn. prefix goes with DBX, DBB, DBW or DBD, for example DB1.DBW 4",
                )
        bit = int(match["bit"]) if match["bit"] is not None else None
        return db, area, byte, bit

    def _area(self, written: str, token: Token) -> str:
        if self._german:
            if written in _AREAS_FROM_GERMAN:
                return _AREAS_FROM_GERMAN[written]
            hint = "this is international spelling; drop --mnemonics de or use the German one"
            known = written in GERMAN_AREAS
        else:
            if written in GERMAN_AREAS:
                return written
            hint = "this is German spelling; use --mnemonics de"
            known = written in _AREAS_FROM_GERMAN
        raise Mc7SyntaxError(
            f"unknown operand area {written!r}",
            token.location,
            text=token.text,
            hint=hint if known else "areas are I, Q, M, L, DBX, DIX and for example MW, DBD, PIB",
        )

    def _bit_address(self, head: Token, operands: list[Token]) -> ir.BitAddress:
        expected = "a bit address such as I 0.0"
        text, token = self._operand_text(head, operands, expected)
        parts = self._address(text, token)
        if parts is None or parts[1] not in _BIT_AREAS or parts[3] is None:
            raise Mc7SyntaxError(
                f"{head.text} needs {expected}, found {text!r}", token.location, text=text
            )
        db, area, byte, bit = parts[0], parts[1], parts[2], parts[3]
        if bit > 7:
            raise Mc7SyntaxError(
                f"bit number {bit} is out of range",
                token.location,
                text=text,
                hint="bits are numbered 0 to 7",
            )
        return ir.BitAddress(_BIT_AREAS[area], byte, bit, db, location=token.location)

    def _data_address(self, head: Token, text: str, token: Token) -> ir.DataAddress:
        parts = self._address(text, token)
        match = _DATA_AREA.fullmatch(parts[1]) if parts else None
        if parts is None or match is None or parts[3] is not None:
            what = (
                "an address such as MW 10"
                if head.text.upper() == "T"
                else ("a constant or an address such as MW 10")
            )
            raise Mc7SyntaxError(
                f"{head.text} needs {what}, found {text!r}", token.location, text=text
            )
        return ir.DataAddress(
            ir.Area(match[1]), ir.Width(match[2]), parts[2], parts[0], location=token.location
        )

    def _load_operand(self, head: Token, operands: list[Token]) -> ir.DataAddress | ir.Constant:
        text, token = self._operand_text(head, operands, "a constant or an address such as MW 10")
        location = token.location
        if token.kind is TokenKind.NUMBER and len(operands) == 1:
            return _number(text, location)
        if token.kind is TokenKind.LITERAL:
            return _literal(text, location)
        if text.upper() in ("TRUE", "FALSE"):
            return ir.BoolConstant(text.upper() == "TRUE", location=location)
        return self._data_address(head, text, token)

    def _counter(self, head: Token, operands: list[Token]) -> ir.CounterAddress:
        expected = "a counter such as Z 1" if self._german else "a counter such as C 1"
        text, token = self._operand_text(head, operands, expected)
        parts = self._address(text, token)
        if parts is None or parts[1] != "C" or parts[0] is not None or parts[3] is not None:
            raise Mc7SyntaxError(
                f"{head.text} needs {expected}, found {text!r}", token.location, text=text
            )
        if parts[2] > MAX_COUNTER_NUMBER:
            raise Mc7SyntaxError(
                f"counter number {parts[2]} is out of range",
                token.location,
                text=text,
                hint=f"counters go from 0 to {MAX_COUNTER_NUMBER}",
            )
        return ir.CounterAddress(parts[2], location=token.location)

    def _no_operand(self, head: Token, operands: list[Token]) -> None:
        if operands:
            raise Mc7SyntaxError(
                f"{head.text} takes no operand, found {operands[0].text!r}",
                operands[0].location,
                text=operands[0].text,
            )


def _number(text: str, location: SourceLocation) -> ir.IntConstant | ir.RealConstant:
    if _INTEGER.fullmatch(text):
        value = int(text)
        if not -0x8000 <= value <= 0x7FFF:
            raise Mc7SyntaxError(
                f"{text} does not fit a 16-bit integer",
                location,
                text=text,
                hint=f"write L#{value} for a 32-bit integer",
            )
        return ir.IntConstant(value, ir.IntWidth.INT, location=location)
    if _REAL.fullmatch(text):
        number = float(text)
        try:
            struct.pack(">f", number)
        except OverflowError:
            number = math.inf
        if math.isfinite(number):
            return ir.RealConstant(number, location=location)
        raise Mc7SyntaxError(f"{text} does not fit a 32-bit real", location, text=text)
    raise Mc7SyntaxError(
        f"malformed number {text!r}", location, text=text, hint="write it like 100, -5 or 1.5"
    )


def _literal(text: str, location: SourceLocation) -> ir.Constant:
    if match := _DINT.fullmatch(text):
        value = int(match[1])
        if not -0x80000000 <= value <= 0x7FFFFFFF:
            raise Mc7SyntaxError(f"{text} does not fit a 32-bit integer", location, text=text)
        return ir.IntConstant(value, ir.IntWidth.DINT, location=location)
    try:
        parsed = parse_constant(text)
    except NotationError as exc:
        raise Mc7SyntaxError(str(exc), location, text=text, hint=exc.hint) from exc
    if parsed is None:
        raise Mc7SyntaxError(
            f"unknown constant {text!r}",
            location,
            text=text,
            hint="known prefixes: L# B#16# W#16# DW#16# 2# C# D# S5T# T# TOD# B#( and 'text'",
        )
    notation, value, size = parsed
    return ir.TypedConstant(notation, value, size, location=location)


def _with_comment(instruction: ir.Instruction, comment: str) -> ir.Instruction:
    fields = {name: getattr(instruction, name) for name in instruction.__dataclass_fields__}
    return type(instruction)(**{**fields, "comment": comment})


Tokens = list[Token]
Builder = Callable[[_StatementParser, str, Token, Tokens], ir.Instruction]


def _bit_logic(p: _StatementParser, name: str, head: Token, rest: Tokens) -> ir.Instruction:
    return ir.BitLogic(ir.BitOp(name), p._bit_address(head, rest), location=head.location)


def _bit_write(p: _StatementParser, name: str, head: Token, rest: Tokens) -> ir.Instruction:
    return ir.BitWrite(ir.WriteOp(name), p._bit_address(head, rest), location=head.location)


def _edge(p: _StatementParser, name: str, head: Token, rest: Tokens) -> ir.Instruction:
    return ir.EdgeDetect(ir.EdgeOp(name), p._bit_address(head, rest), location=head.location)


def _load(p: _StatementParser, name: str, head: Token, rest: Tokens) -> ir.Instruction:
    return ir.Load(p._load_operand(head, rest), location=head.location)


def _transfer(p: _StatementParser, name: str, head: Token, rest: Tokens) -> ir.Instruction:
    text, token = p._operand_text(head, rest, "an address such as MW 10")
    return ir.Transfer(p._data_address(head, text, token), location=head.location)


def _counter(p: _StatementParser, name: str, head: Token, rest: Tokens) -> ir.Instruction:
    return ir.CounterControl(ir.CounterOp(name), p._counter(head, rest), location=head.location)


def _nest_open(p: _StatementParser, name: str, head: Token, rest: Tokens) -> ir.Instruction:
    p._no_operand(head, rest)
    return ir.NestOpen(ir.BitOp(name[:-1]), location=head.location)


def _nest_close(p: _StatementParser, name: str, head: Token, rest: Tokens) -> ir.Instruction:
    p._no_operand(head, rest)
    return ir.NestClose(location=head.location)


def _block_end(p: _StatementParser, name: str, head: Token, rest: Tokens) -> ir.Instruction:
    p._no_operand(head, rest)
    return ir.BlockEnd(location=head.location)


_BUILDERS: dict[str, Builder] = {
    **dict.fromkeys(("A", "AN", "O", "ON"), _bit_logic),
    **dict.fromkeys(("=", "S", "R"), _bit_write),
    **dict.fromkeys(("FP", "FN"), _edge),
    "L": _load,
    "T": _transfer,
    **dict.fromkeys(("CU", "CD", "LC"), _counter),
    **dict.fromkeys(("A(", "AN(", "O(", "ON("), _nest_open),
    ")": _nest_close,
    "BE": _block_end,
}
