"""The STL parser: golden IR trees, typed operands, locations and every expected error."""

from __future__ import annotations

from pathlib import Path

import pytest

from mc7asm import (
    BlockType,
    Mc7SyntaxError,
    Mnemonics,
    SourceLocation,
    cli,
    ir,
    parse_file,
    parse_source,
    parse_statement,
)
from mc7asm.notation import Notation
from mc7asm.printer import format_instruction

REPOSITORY = Path(__file__).parent.parent
EXAMPLES = REPOSITORY / "examples"
GOLDEN = REPOSITORY / "tests" / "fixtures" / "golden"
EXPECTED_ERRORS = sorted((REPOSITORY / "tests" / "expected_errors").glob("*.awl"))


@pytest.mark.parametrize("example", ["blink", "counter", "nesting"])
def test_golden_ir_tree(
    example: str, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(REPOSITORY)
    assert cli.main(["parse", f"examples/{example}.awl"]) == 0
    captured = capsys.readouterr()
    assert captured.out == (GOLDEN / f"{example}.ir.txt").read_text()
    assert captured.err == ""


def test_block_structure() -> None:
    block = parse_file(EXAMPLES / "blink.awl")
    assert (block.block_type, block.number, block.name) == (BlockType.OB, 1, "OB1")
    assert block.title == "Lamp control"
    assert [network.title for network in block.networks] == [
        "Latch the lamp",
        "Copy a word and load constants",
        "",
    ]
    assert block.networks[0].comment == (
        "The start button sets the lamp, the stop button resets it.",
    )
    assert [len(network.instructions) for network in block.networks] == [4, 12, 3]
    assert block.networks[0].instructions[0].comment == "start button"
    assert str(block.networks[1].location) == f"{EXAMPLES / 'blink.awl'}:11:1"


def test_german_source_gives_the_same_ir() -> None:
    german = parse_file(EXAMPLES / "blink_de.awl", Mnemonics.DE)
    international = parse_file(EXAMPLES / "blink.awl")
    assert german == international
    assert german.networks[0].instructions[1] == ir.BitWrite(
        ir.WriteOp.SET, ir.BitAddress(ir.Area.Q, 0, 0)
    )


@pytest.mark.parametrize(
    ("source", "block_type", "number"),
    [
        ("ORGANIZATION_BLOCK OB1\nBEGIN\nEND_ORGANIZATION_BLOCK", BlockType.OB, 1),
        ("organization_block ob 35\nbegin\nend_organization_block", BlockType.OB, 35),
        ("FUNCTION FC 7\nBEGIN\nEND_FUNCTION", BlockType.FC, 7),
        ("FUNCTION FC7 : VOID // main\nBEGIN\nEND_FUNCTION // end\n// bye", BlockType.FC, 7),
        ("// header\n\nFUNCTION_BLOCK FB 65535\nBEGIN\nEND_FUNCTION_BLOCK", BlockType.FB, 65535),
    ],
)
def test_block_headers(source: str, block_type: BlockType, number: int) -> None:
    block = parse_source(source)
    assert (block.block_type, block.number, block.networks, block.title) == (
        block_type,
        number,
        (),
        "",
    )


def test_empty_networks_and_comment_lines_between_statements() -> None:
    block = parse_source(
        "FUNCTION FC 1 : VOID\nBEGIN\nNETWORK\nNETWORK\nTITLE =\n// note\n"
        "A I 0.0\n// in between\n= Q 0.0\nEND_FUNCTION"
    )
    first, second = block.networks
    assert (first.instructions, first.title, first.comment) == ((), "", ())
    assert (second.title, second.comment) == ("", ("note",))
    assert [format_instruction(i) for i in second.instructions] == ["A I 0.0", "= Q 0.0"]


BIT = ir.BitAddress
DATA = ir.DataAddress
TYPED = ir.TypedConstant


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("A I 0.0", ir.BitLogic(ir.BitOp.A, BIT(ir.Area.I, 0, 0))),
        ("AN I0.7", ir.BitLogic(ir.BitOp.AN, BIT(ir.Area.I, 0, 7))),
        ("o q 65535.1", ir.BitLogic(ir.BitOp.O, BIT(ir.Area.Q, 65535, 1))),
        ("ON M 10.3;", ir.BitLogic(ir.BitOp.ON, BIT(ir.Area.M, 10, 3))),
        ("A L 2.0", ir.BitLogic(ir.BitOp.A, BIT(ir.Area.L, 2, 0))),
        ("A DBX 4.5", ir.BitLogic(ir.BitOp.A, BIT(ir.Area.DB, 4, 5))),
        ("A DIX4.5", ir.BitLogic(ir.BitOp.A, BIT(ir.Area.DI, 4, 5))),
        ("A DB1.DBX0.0", ir.BitLogic(ir.BitOp.A, BIT(ir.Area.DB, 0, 0, db=1))),
        ("A DB12.DBX 3.4", ir.BitLogic(ir.BitOp.A, BIT(ir.Area.DB, 3, 4, db=12))),
        ("= Q 0.0", ir.BitWrite(ir.WriteOp.ASSIGN, BIT(ir.Area.Q, 0, 0))),
        ("S M 1.1", ir.BitWrite(ir.WriteOp.SET, BIT(ir.Area.M, 1, 1))),
        ("R M 1.1", ir.BitWrite(ir.WriteOp.RESET, BIT(ir.Area.M, 1, 1))),
        ("FP M 0.0", ir.EdgeDetect(ir.EdgeOp.FP, BIT(ir.Area.M, 0, 0))),
        ("FN M 0.1", ir.EdgeDetect(ir.EdgeOp.FN, BIT(ir.Area.M, 0, 1))),
        ("A(", ir.NestOpen(ir.BitOp.A)),
        ("ON(", ir.NestOpen(ir.BitOp.ON)),
        (")", ir.NestClose()),
        ("BE", ir.BlockEnd()),
        ("CU C 5", ir.CounterControl(ir.CounterOp.CU, ir.CounterAddress(5))),
        ("CD C0", ir.CounterControl(ir.CounterOp.CD, ir.CounterAddress(0))),
        ("LC C 255", ir.CounterControl(ir.CounterOp.LC, ir.CounterAddress(255))),
        ("L MB 1", ir.Load(DATA(ir.Area.M, ir.Width.BYTE, 1))),
        ("L QW4", ir.Load(DATA(ir.Area.Q, ir.Width.WORD, 4))),
        ("L ID 8", ir.Load(DATA(ir.Area.I, ir.Width.DWORD, 8))),
        ("L PIB 256", ir.Load(DATA(ir.Area.PI, ir.Width.BYTE, 256))),
        ("L LW 2", ir.Load(DATA(ir.Area.L, ir.Width.WORD, 2))),
        ("L DBD 4", ir.Load(DATA(ir.Area.DB, ir.Width.DWORD, 4))),
        ("L DIB 4", ir.Load(DATA(ir.Area.DI, ir.Width.BYTE, 4))),
        ("L DB1.DBD4", ir.Load(DATA(ir.Area.DB, ir.Width.DWORD, 4, db=1))),
        ("T MW 10", ir.Transfer(DATA(ir.Area.M, ir.Width.WORD, 10))),
        ("T PQW 4", ir.Transfer(DATA(ir.Area.PQ, ir.Width.WORD, 4))),
        ("L TRUE", ir.Load(ir.BoolConstant(True))),
        ("L false", ir.Load(ir.BoolConstant(False))),
        ("L 100", ir.Load(ir.IntConstant(100))),
        ("L -32768", ir.Load(ir.IntConstant(-32768))),
        ("L +7", ir.Load(ir.IntConstant(7))),
        ("L L#100000", ir.Load(ir.IntConstant(100000, ir.IntWidth.DINT))),
        ("L l#-5", ir.Load(ir.IntConstant(-5, ir.IntWidth.DINT))),
        ("L 1.5", ir.Load(ir.RealConstant(1.5))),
        ("L -2.5e3", ir.Load(ir.RealConstant(-2500.0))),
        ("L 100.000000", ir.Load(ir.RealConstant(100.0))),
        ("L B#16#1F", ir.Load(TYPED(Notation.BYTE_HEX, 0x1F, 1))),
        ("L W#16#1f", ir.Load(TYPED(Notation.HEX_WORD, 0x1F, 2))),
        ("L DW#16#DEADBEEF", ir.Load(TYPED(Notation.HEX_DWORD, 0xDEADBEEF, 4))),
        ("L 2#1010", ir.Load(TYPED(Notation.BINARY, 10, 2))),
        ("L 2#1111_0000_1111_0000_1", ir.Load(TYPED(Notation.BINARY, 0x1E1E1, 4))),
        ("L 'A'", ir.Load(TYPED(Notation.CHARS, 0x41, 2))),
        ("L 'a b'", ir.Load(TYPED(Notation.CHARS, 0x612062, 4))),
        ("L B#(10, 20)", ir.Load(TYPED(Notation.BYTES, 0x0A14, 2))),
        ("L B#(1,2,03,255)", ir.Load(TYPED(Notation.BYTES, 0x010203FF, 4))),
        ("L C#999", ir.Load(TYPED(Notation.COUNTER, 999, 2))),
        ("L D#1990-1-1", ir.Load(TYPED(Notation.DATE, 0, 2))),
        ("L D#2012-12-12", ir.Load(TYPED(Notation.DATE, 8381, 2))),
        ("L S5T#2H46M30S", ir.Load(TYPED(Notation.S5TIME, 9_990_000, 2))),
        ("L s5t#100ms", ir.Load(TYPED(Notation.S5TIME, 100, 2))),
        ("L S5T#5M", ir.Load(TYPED(Notation.S5TIME, 300_000, 2))),
        ("L T#1500MS", ir.Load(TYPED(Notation.TIME, 1500, 4))),
        ("L TOD#1:10:3.300", ir.Load(TYPED(Notation.TIME_OF_DAY, 4_203_300, 4))),
    ],
)
def test_statements(text: str, expected: ir.Instruction) -> None:
    assert parse_statement(text) == expected


@pytest.mark.parametrize(
    ("german", "international"),
    [
        ("U E 0.0", "A I 0.0"),
        ("UN A 1.2", "AN Q 1.2"),
        ("O M 0.0", "O M 0.0"),
        ("= A 4.0", "= Q 4.0"),
        ("U(", "A("),
        ("UN(", "AN("),
        ("L EB 1", "L IB 1"),
        ("T AW 4", "T QW 4"),
        ("L PEW 256", "L PIW 256"),
        ("T PAD 4", "T PQD 4"),
        ("ZV Z 1", "CU C 1"),
        ("ZR Z 1", "CD C 1"),
        ("LC Z 1", "LC C 1"),
        ("L W#16#1F", "L W#16#1F"),
    ],
)
def test_german_statements(german: str, international: str) -> None:
    parsed = parse_statement(german, Mnemonics.DE)
    assert parsed == parse_statement(international)
    assert format_instruction(parsed, Mnemonics.DE) == german.replace("W#16#1F", "W#16#1f")
    assert format_instruction(parsed) == international.replace("W#16#1F", "W#16#1f")


def test_nodes_carry_locations_that_do_not_affect_equality() -> None:
    instruction = parse_statement("   L   DB1.DBW 4  // note", file="x.awl")
    operand = ir.operand_of(instruction)
    assert instruction.location == SourceLocation("x.awl", 1, 4)
    assert operand is not None
    assert operand.location == SourceLocation("x.awl", 1, 8)
    assert instruction.comment == "note"
    assert instruction == ir.Load(ir.DataAddress(ir.Area.DB, ir.Width.WORD, 4, db=1))
    assert instruction != ir.Load(ir.DataAddress(ir.Area.DB, ir.Width.WORD, 5, db=1))
    assert ir.operand_of(ir.BlockEnd()) is None
    assert ir.BlockEnd().location.file == "<generated>"


@pytest.mark.parametrize("text", ["", "   ", "// only a comment", "A I 0.0\nA I 0.1"])
def test_parse_statement_needs_exactly_one_statement(text: str) -> None:
    with pytest.raises(Mc7SyntaxError):
        parse_statement(text)


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("L 2#", "malformed binary constant"),
        ("L 2#2", "malformed binary constant"),
        ("L 2#" + "1" * 33, "needs 1 to 32 digits"),
        ("L B#16#100", "malformed byte constant"),
        ("L DW#16#123456789", "malformed double word constant"),
        ("L B#(1, 2, 3)", "needs 2 or 4 values from 0 to 255"),
        ("L B#(1, 256)", "needs 2 or 4 values from 0 to 255"),
        ("L 'ABCDE'", "malformed character constant"),
        ("L ''", "malformed character constant"),
        ("L D#2001-2-30", "is not a calendar date"),
        ("L D#1989-12-31", "is outside D#1990-1-1"),
        ("L S5T#", "malformed S5TIME constant"),
        ("L S5T#3H", "cannot be represented exactly"),
        ("L T#1S", "malformed TIME constant"),
        ("L T#4294967296MS", "does not fit 32 bits"),
        ("L TOD#1:60:0.000", "is out of range"),
        ("L TOD#1:10:3.3", "malformed time of day constant"),
        ("L L#2147483648", "does not fit a 32-bit integer"),
        ("L 1e40", "does not fit a 32-bit real"),
        ("L 1.2.3", "malformed number"),
        ("L -32769", "does not fit a 16-bit integer"),
        ("A DB0.DBX 0.0", "is not a valid data block address"),
        ("CU C 1.0", "needs a counter such as C 1"),
        ("CU T 1", "unknown operand area 'T'"),
        ("A I 0.0.0", "needs a bit address"),
        ("A 0.0", "needs a bit address"),
        ("1 A", "expected an operation, found '1'"),
        ("; A", "expected an operation, found ';'"),
    ],
)
def test_statement_errors(text: str, fragment: str) -> None:
    with pytest.raises(Mc7SyntaxError, match=fragment) as caught:
        parse_statement(text)
    assert caught.value.location.file == "<statement>"
    assert caught.value.location.line == 1


def test_the_expected_error_corpus_is_complete() -> None:
    assert len(EXPECTED_ERRORS) == 38
    assert all(path.with_suffix(".txt").is_file() for path in EXPECTED_ERRORS)
    german = [path.name for path in EXPECTED_ERRORS if path.name.endswith(".de.awl")]
    assert len(german) == 2


@pytest.mark.parametrize("path", EXPECTED_ERRORS, ids=lambda path: path.stem)
def test_malformed_input_raises_with_the_expected_location_and_message(path: Path) -> None:
    expected = path.with_suffix(".txt").read_text().rstrip("\n")
    mnemonics = Mnemonics.DE if path.name.endswith(".de.awl") else Mnemonics.EN
    with pytest.raises(Mc7SyntaxError) as caught:
        parse_source(path.read_text(), path.name, mnemonics)
    error = caught.value
    assert str(error) == expected
    file, line, column, _rest = expected.split(":", 3)
    assert error.location == SourceLocation(file, int(line), int(column))
    assert error.message in expected
    if error.hint:
        assert expected.endswith(f"; {error.hint}")
    if error.text:
        source_line = path.read_text().splitlines()[error.location.line - 1]
        assert source_line[error.location.column - 1 :].startswith(error.text.split(" ")[0])


def test_syntax_errors_on_the_command_line(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(REPOSITORY)
    path = "tests/expected_errors/bit_number_out_of_range.awl"
    for command in ("parse", "compile"):
        assert cli.main([command, path]) == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == (
            f"error: {path}:4:9: bit number 8 is out of range; bits are numbered 0 to 7\n"
        )
    assert not Path(path).with_suffix(".body").exists()
    assert cli.main(["parse", "examples/blink.awl", "--mnemonics", "de"]) == 1
    assert "this is international spelling" in capsys.readouterr().err
    assert cli.main(["parse", "examples/blink_de.awl", "--mnemonics", "de"]) == 0
    assert cli.main(["parse", "examples/missing.awl"]) == 1
