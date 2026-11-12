"""The code generator: golden bodies, length accounting, row selection and refusals."""

from __future__ import annotations

import random
import re
from pathlib import Path

import pytest

from mc7asm import (
    CodegenError,
    Mc7AsmError,
    Mnemonics,
    NotYetSupportedError,
    cli,
    compile_block,
    compile_instruction,
    ir,
    parse_file,
    parse_image,
    parse_source,
    parse_statement,
)
from mc7asm.disasm import decode_code, decode_instruction
from mc7asm.notation import Notation
from mc7asm.opcodes import OPCODE_TABLE, OpcodeRow, Operand, Status
from mc7asm.printer import format_instruction

REPOSITORY = Path(__file__).parent.parent
EXAMPLES = REPOSITORY / "examples"
GOLDEN = REPOSITORY / "tests" / "fixtures" / "golden"
CM7 = REPOSITORY / "tests" / "fixtures" / "blocks" / "reference" / "cm7.bin"
LISTING_LINE = re.compile(r"\s+0x[0-9a-f]+\s+(?:[0-9a-f]{2} )*[0-9a-f]{2}\s+(.+)")


def encode(text: str) -> str:
    return compile_instruction(parse_statement(text))[1].hex(" ")


# ---------------------------------------------------------------------- golden bodies


@pytest.mark.parametrize("example", ["blink", "counter"])
def test_golden_body(example: str) -> None:
    compiled = compile_block(parse_file(EXAMPLES / f"{example}.awl"))
    golden = bytes.fromhex((GOLDEN / f"{example}.body.hex").read_text())
    assert compiled.body == golden
    assert compiled.size == len(golden)


def test_german_source_compiles_to_the_same_body() -> None:
    german = compile_block(parse_file(EXAMPLES / "blink_de.awl", Mnemonics.DE))
    assert german.body == bytes.fromhex((GOLDEN / "blink.body.hex").read_text())


def test_counter_example_is_the_code_of_the_reference_block() -> None:
    reference = parse_image(CM7.read_bytes()).payload
    assert compile_block(parse_file(EXAMPLES / "counter.awl")).body == reference


@pytest.mark.parametrize("language", ["en", "de"])
def test_assembling_the_golden_disassembly_reproduces_the_reference_block(language: str) -> None:
    listing = (GOLDEN / f"cm7.disasm.{language}.txt").read_text().splitlines()
    statements = [match[1] for line in listing if (match := LISTING_LINE.fullmatch(line))]
    assert len(statements) == 15
    assert statements[-1] == "BE"
    mnemonics = Mnemonics(language)
    body = b"".join(compile_instruction(parse_statement(text, mnemonics))[1] for text in statements)
    assert body == parse_image(CM7.read_bytes()).payload
    assert len(body) == 36


# ---------------------------------------------------------------------- accounting


def test_lengths_are_accounted_per_instruction_and_per_network() -> None:
    compiled = compile_block(parse_file(EXAMPLES / "blink.awl"))
    assert [(n.number, n.offset, n.size, len(n.instructions)) for n in compiled.networks] == [
        (1, 0, 8, 4),
        (2, 8, 42, 12),
        (3, 50, 10, 4),
    ]
    assert compiled.size == 60 == len(compiled.body)
    offset = 0
    for network in compiled.networks:
        assert network.offset == offset
        for instruction in network.instructions:
            assert instruction.offset == offset
            assert len(instruction.data) == instruction.row.length
            assert compiled.body[offset : offset + len(instruction.data)] == instruction.data
            offset += len(instruction.data)
    second = compiled.networks[1].instructions
    assert [len(item.data) for item in second] == [2, 2, 4, 2, 6, 2, 6, 4, 4, 4, 4, 2]
    assert second[4].instruction == ir.Load(ir.IntConstant(100000, ir.IntWidth.DINT))


def test_empty_block_and_empty_network() -> None:
    compiled = compile_block(
        parse_source("FUNCTION FC 1 : VOID\nBEGIN\nNETWORK\nNETWORK\nBE\nEND_FUNCTION")
    )
    assert [(n.offset, n.size) for n in compiled.networks] == [(0, 0), (0, 2)]
    assert compiled.body == bytes.fromhex("6500")
    empty = compile_block(parse_source("FUNCTION FC 1 : VOID\nBEGIN\nEND_FUNCTION"))
    assert (empty.body, empty.size, empty.networks) == (b"", 0, ())


def test_compile_on_the_command_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(REPOSITORY)
    output = tmp_path / "out.body"
    assert cli.main(["compile", "examples/blink.awl", "-o", str(output)]) == 0
    assert output.read_bytes() == bytes.fromhex((GOLDEN / "blink.body.hex").read_text())
    assert capsys.readouterr().out == (
        f"examples/blink.awl: OB1, 3 networks, 60 bytes of MC7 code -> {output}\n"
        '  network 1 "Latch the lamp": 4 instructions, 8 bytes at offset 0x0000\n'
        '  network 2 "Copy a word and load constants": 12 instructions, 42 bytes '
        "at offset 0x0008\n"
        "  network 3: 4 instructions, 10 bytes at offset 0x0032\n"
    )


def test_compile_defaults_to_a_body_file_next_to_the_source(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "counter.awl"
    source.write_text((EXAMPLES / "counter.awl").read_text())
    assert cli.main(["compile", str(source)]) == 0
    assert (tmp_path / "counter.body").read_bytes() == parse_image(CM7.read_bytes()).payload
    assert "1 network," not in capsys.readouterr().out
    german = tmp_path / "blink_de.awl"
    german.write_text((EXAMPLES / "blink_de.awl").read_text())
    assert cli.main(["compile", str(german), "--mnemonics", "de"]) == 0
    assert (tmp_path / "blink_de.body").stat().st_size == 60


def test_nothing_is_written_when_compilation_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(REPOSITORY)
    output = tmp_path / "out.body"
    assert cli.main(["compile", "examples/nesting.awl", "-o", str(output)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "error: examples/nesting.awl:5:7: A( is not yet supported: nesting operations are "
        "not in the opcode table; write the expression without parentheses for now\n"
    )
    assert not output.exists()


# ---------------------------------------------------------------------- row selection


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("A M 255.7", "87 ff"),
        ("A M 256.7", "00 37 01 00"),
        ("A I 127.0", "c0 7f"),
        ("A I 128.0", "00 10 00 80"),
        ("A Q 127.1", "c1 ff"),
        ("= Q 128.1", "41 21 00 80"),
        ("R Q 0.0", "f0 80"),
        ("A L 0.0", "00 60 00 00"),
        ("A DBX 0.0", "00 40 00 00"),
        ("FP M 0.0", "49 30 00 00"),
        ("L MB 255", "0a ff"),
        ("L MB 256", "7e 31 01 00"),
        ("T QD 127", "5b ff"),
        ("T QD 128", "7e 27 00 80"),
        ("L PIB 0", "7e 01 00 00"),
        ("T PQD 65535", "7e 07 ff ff"),
        ("L LW 2", "7e 62 00 02"),
        ("CU C 255", "6c ff"),
        ("L -1", "30 03 ff ff"),
        ("L L#-1", "38 03 ff ff ff ff"),
        ("L 1.5", "38 01 3f c0 00 00"),
        ("L 2#0", "30 02 00 00"),
        ("L 2#10000000000000000", "38 02 00 01 00 00"),
        ("L 'AB'", "30 05 41 42"),
        ("L 'ABC'", "38 05 00 41 42 43"),
        ("L C#123", "30 08 01 23"),
        ("L S5T#100MS", "30 0c 00 10"),
        ("L S5T#1S", "30 0c 01 00"),
        ("L S5T#10S", "30 0c 11 00"),
        ("L S5T#2H46M30S", "30 0c 39 99"),
        ("L D#1990-1-2", "30 0a 00 01"),
        ("L T#1MS", "38 09 00 00 00 01"),
        ("L TOD#0:0:1.000", "38 0b 00 00 03 e8"),
        ("L B#(1, 2)", "30 06 01 02"),
        ("L DW#16#1", "38 07 00 00 00 01"),
        ("BE", "65 00"),
    ],
)
def test_the_shortest_fitting_row_is_used(text: str, expected: str) -> None:
    assert encode(text) == expected


# ---------------------------------------------------------------------- refusals


@pytest.mark.parametrize(
    ("text", "fragment", "hint"),
    [
        ("A(", "A( is not yet supported: nesting operations", "without parentheses"),
        (")", ") is not yet supported: nesting operations", "without parentheses"),
        ("A DB1.DBX 0.0", "a fully qualified data block address needs OPN DB", "DBX without"),
        ("L DB1.DBD 4", "a fully qualified data block address needs OPN DB", "DBD without"),
        ("L TRUE", "L TRUE is not yet supported: TRUE and FALSE have no row", ""),
        ("L B#16#1F", "L B#16#1F is not yet supported: its opcode row is unverified", "docs/"),
        ("T PIB 0", "the opcode table has no row for T on PIB", ""),
        ("L PQW 0", "the opcode table has no row for L on PQW", ""),
    ],
)
def test_valid_stl_outside_the_table_is_refused(text: str, fragment: str, hint: str) -> None:
    instruction = parse_statement(text, file="demo.awl")
    with pytest.raises(NotYetSupportedError, match=re.escape(fragment)) as caught:
        compile_instruction(instruction)
    error = caught.value
    assert str(error).startswith("demo.awl:1:")
    assert hint in error.hint
    assert isinstance(error, CodegenError)
    assert isinstance(error, Mc7AsmError)


def test_unverified_rows_are_never_used() -> None:
    unverified = [row for row in OPCODE_TABLE if row.status is Status.UNVERIFIED]
    assert [row.operand for row in unverified] == [Operand.BYTE_HEX]
    with pytest.raises(NotYetSupportedError, match="decimal after B#16#"):
        compile_instruction(ir.Load(ir.TypedConstant(Notation.BYTE_HEX, 0x12, 1)))


BIT = ir.BitAddress


@pytest.mark.parametrize(
    ("instruction", "fragment"),
    [
        (ir.BitLogic(ir.BitOp.A, BIT(ir.Area.I, 0, 8)), "A I 0.8: bit number 8 is out of range"),
        (ir.BitLogic(ir.BitOp.A, BIT(ir.Area.I, 70000, 0)), "address 70000 is out of range"),
        (ir.BitWrite(ir.WriteOp.SET, BIT(ir.Area.M, -1, 0)), "address -1 is out of range"),
        (
            ir.CounterControl(ir.CounterOp.CU, ir.CounterAddress(300)),
            "CU C 300: address 300 is out of range",
        ),
        (ir.Load(ir.IntConstant(40000)), "L 40000: 40000 does not fit INT"),
        (ir.Load(ir.IntConstant(2**31, ir.IntWidth.DINT)), "does not fit DINT"),
        (ir.Load(ir.RealConstant(1e40)), "the value does not fit a 32-bit real"),
        (ir.Load(ir.TypedConstant(Notation.S5TIME, 1005, 2)), "the value cannot be encoded"),
        (ir.Load(ir.TypedConstant(Notation.COUNTER, 1000, 2)), "the value cannot be encoded"),
        (ir.Load(ir.TypedConstant(Notation.HEX_WORD, 0x10000, 2)), "the value cannot be encoded"),
    ],
)
def test_operands_that_cannot_be_encoded_are_rejected(
    instruction: ir.Instruction, fragment: str
) -> None:
    with pytest.raises(CodegenError, match=re.escape(fragment)) as caught:
        compile_instruction(instruction)
    assert not isinstance(caught.value, NotYetSupportedError)
    assert str(caught.value).startswith("<generated>:0:0: ")


def test_constant_of_an_unknown_shape_is_refused() -> None:
    with pytest.raises(NotYetSupportedError, match="this constant has no row"):
        compile_instruction(ir.Load(ir.TypedConstant(Notation.HEX_WORD, 1, 4)))


# ---------------------------------------------------------------------- property test


def instruction_for(row: OpcodeRow, generator: random.Random, *, at_limit: bool) -> ir.Instruction:
    """Build an IR instruction that the given row (or a shorter sibling) encodes."""
    limits = {
        Operand.BIT_LONG: 0xFFFF,
        Operand.BIT_SHORT_8: 0xFF,
        Operand.BIT_SHORT_7: 0x7F,
        Operand.ADDRESS_16: 0xFFFF,
        Operand.ADDRESS_8: 0xFF,
        Operand.ADDRESS_7: 0x7F,
    }
    if row.operand is Operand.NONE:
        return parse_statement(row.mnemonic)
    if row.operand in limits:
        limit = limits[row.operand]
        address = limit if at_limit else generator.randint(0, limit)
        bit = f".{generator.randint(0, 7)}" if row.operand.name.startswith("BIT") else ""
        return parse_statement(f"{row.mnemonic} {row.area} {address}{bit}")
    bits16, bits32 = generator.getrandbits(16), generator.getrandbits(32)
    word = "".join(chr(generator.randint(0x41, 0x5A)) for _ in range(generator.randint(1, 2)))
    text = {
        Operand.BINARY_16: f"2#{bits16:b}",
        Operand.BINARY_32: f"2#{bits32 | 1 << 16:b}",
        Operand.INT_16: str(bits16 - 0x8000),
        Operand.INT_32: f"L#{bits32 - 0x80000000}",
        Operand.CHARS_16: f"'{word}'",
        Operand.CHARS_32: f"'{word}xy'",
        Operand.BYTES_16: f"B#({bits16 >> 8}, {bits16 & 0xFF})",
        Operand.BYTES_32: "B#(" + ", ".join(str(b) for b in bits32.to_bytes(4, "big")) + ")",
        Operand.HEX_16: f"W#16#{bits16:X}",
        Operand.HEX_32: f"DW#16#{bits32:x}",
        Operand.COUNTER_BCD: f"C#{generator.randint(0, 999)}",
        Operand.DATE: f"D#{generator.randint(1990, 2160)}-{generator.randint(1, 12)}-"
        f"{generator.randint(1, 28)}",
        Operand.S5TIME: f"S5T#{generator.randint(1, 999) * generator.choice((10, 100, 1000))}MS",
        Operand.REAL: str(generator.randint(-(10**6), 10**6) / 64),
        Operand.TIME: f"T#{bits32}MS",
        Operand.TIME_OF_DAY: f"TOD#{generator.randint(0, 23)}:{generator.randint(0, 59)}:"
        f"{generator.randint(0, 59)}.{generator.randint(0, 999):03d}",
    }[row.operand]
    return parse_statement(f"{row.mnemonic} {text}")


def test_disassembling_generated_code_gives_back_the_ir() -> None:
    """Property: disasm(codegen(ir)) == ir, for random operands on every usable row."""
    generator = random.Random(20261112)
    usable = [row for row in OPCODE_TABLE if row.status is not Status.UNVERIFIED]
    assert len(usable) == len(OPCODE_TABLE) - 1
    selected: set[str] = set()
    program: list[ir.Instruction] = []
    for row in usable:
        for round_number in range(12):
            instruction = instruction_for(row, generator, at_limit=round_number == 0)
            used_row, data = compile_instruction(instruction)
            selected.add(used_row.key)
            assert len(data) == used_row.length
            decoded = decode_instruction(data)
            assert decoded is not None, format_instruction(instruction)
            assert decoded.row is used_row
            assert decoded.text == format_instruction(instruction)
            assert parse_statement(decoded.text) == instruction
            assert parse_statement(decode_instruction(data, Mnemonics.DE).text, Mnemonics.DE) == (  # type: ignore[union-attr]
                instruction
            )
            program.append(instruction)
    assert selected == {row.key for row in usable}

    # The same holds for a whole body: decoding it yields the instructions back, in order.
    body = b"".join(compile_instruction(instruction)[1] for instruction in program)
    entries = decode_code(body)
    assert [parse_statement(entry.text) for entry in entries] == program  # type: ignore[union-attr]
    assert sum(len(entry.data) for entry in entries) == len(body)
