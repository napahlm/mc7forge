"""The disassembler: whole-corpus decode, golden listings, coverage and rejections."""

from __future__ import annotations

import re
import struct
from collections import Counter
from pathlib import Path

import pytest

import mc7.blocks
from mc7asm import Mnemonics, Severity, UnsupportedBlockError, cli, disassemble, parse_image
from mc7asm.corpus import load_corpus
from mc7asm.disasm import DecodedInstruction, UnknownOpcode, decode_code, decode_instruction
from tests.support import make_block

FIXTURES = Path(__file__).parent / "fixtures"
CORPUS = load_corpus(FIXTURES / "corpus" / "test_simatic.c")
CM7 = FIXTURES / "blocks" / "reference" / "cm7.bin"
GOLDEN = FIXTURES / "golden"

# Corpus vectors per mnemonic that the table does not decode yet. Each of them
# must come out as an unknown opcode, never as a different instruction.
NOT_YET_DECODED = {
    ")": 2,
    ")MCR": 1,
    "*D": 2,
    "*I": 1,
    "*R": 1,
    "+": 5,
    "+AR1": 4,
    "+AR2": 4,
    "+D": 2,
    "+I": 2,
    "+R": 1,
    "-D": 2,
    "-I": 1,
    "-R": 1,
    "/D": 2,
    "/I": 1,
    "/R": 1,
    "<=D": 1,
    "<=I": 1,
    "<=R": 1,
    "<>D": 1,
    "<>I": 1,
    "<>R": 1,
    "<D": 1,
    "<I": 1,
    "<R": 1,
    "=": 67,
    "==D": 1,
    "==I": 1,
    "==R": 1,
    ">=D": 2,
    ">=I": 1,
    ">=R": 1,
    ">D": 1,
    ">I": 1,
    ">R": 1,
    "A": 74,
    "A(": 1,
    "ABS": 2,
    "ACOS": 2,
    "AD": 3,
    "AN": 71,
    "AN(": 1,
    "ASIN": 2,
    "ATAN": 2,
    "AW": 3,
    "BEC": 2,
    "BEU": 1,
    "BLD": 6,
    "BTD": 1,
    "BTI": 1,
    "CAD": 1,
    "CAR": 2,
    "CAW": 1,
    "CC": 20,
    "CD": 20,
    "CDB": 1,
    "CLR": 1,
    "COS": 2,
    "CU": 8,
    "DEC": 4,
    "DTB": 1,
    "DTR": 1,
    "ENT": 2,
    "EXP": 2,
    "FN": 41,
    "FP": 41,
    "FR": 31,
    "INC": 4,
    "INVD": 1,
    "INVI": 1,
    "ITB": 1,
    "ITD": 1,
    "JBI": 1,
    "JC": 1,
    "JCB": 1,
    "JCN": 1,
    "JL": 1,
    "JM": 1,
    "JMZ": 1,
    "JN": 1,
    "JNB": 1,
    "JNBI": 1,
    "JO": 1,
    "JOS": 1,
    "JP": 1,
    "JPZ": 1,
    "JU": 5,
    "JUO": 1,
    "JZ": 1,
    "L": 155,
    "LAR1": 7,
    "LAR2": 6,
    "LC": 14,
    "LEAVE": 2,
    "LN": 2,
    "LOOP": 1,
    "MCR(": 1,
    "MCRA": 1,
    "MCRD": 1,
    "MOD": 2,
    "NEGD": 1,
    "NEGI": 1,
    "NEGR": 1,
    "NOP": 4,
    "NOT": 3,
    "O": 72,
    "O(": 1,
    "OD": 3,
    "ON": 71,
    "ON(": 1,
    "OPN": 45,
    "OW": 3,
    "POP": 2,
    "PUSH": 2,
    "R": 59,
    "RLD": 7,
    "RLDA": 2,
    "RND": 1,
    "RND+": 1,
    "RND-": 2,
    "RRD": 7,
    "RRDA": 2,
    "S": 51,
    "SAVE": 2,
    "SD": 9,
    "SE": 8,
    "SET": 3,
    "SF": 11,
    "SIN": 2,
    "SLD": 2,
    "SLW": 2,
    "SP": 9,
    "SQR": 2,
    "SQRT": 2,
    "SRD": 3,
    "SRW": 2,
    "SS": 9,
    "SSD": 2,
    "SSI": 2,
    "T": 134,
    "TAK": 2,
    "TAN": 2,
    "TAR1": 23,
    "TAR2": 21,
    "TRUNC": 1,
    "UC": 17,
    "X": 117,
    "X(": 1,
    "XN": 375,
    "XN(": 2,
    "XOD": 3,
    "XOW": 3,
}

DIRECT_BIT = re.compile(r"(A|AN|O|ON|=|S|R|FP|FN) (I|Q|M|DBX|DIX|L) \d+\.[0-7]")
DIRECT_DATA = re.compile(r"(L|T) (PI|PQ|I|Q|M|DB|DI|L)[BWD] \d+")


def test_every_corpus_vector_is_decoded_exactly_or_reported_unknown() -> None:
    """The whole corpus, not a sample: no vector may decode to anything but its text."""
    not_decoded: Counter[str] = Counter()
    decoded = 0
    for vector in CORPUS.vectors:
        result = decode_instruction(vector.data)
        if result is None:
            not_decoded[vector.mnemonic] += 1
            continue
        assert not vector.is_invalid, f"line {vector.line}: decoded bytes upstream rejects"
        assert result.text == vector.stl, f"line {vector.line}"
        assert len(result.data) == vector.read, f"line {vector.line}"
        decoded += 1
    assert not_decoded.pop("invalid") == 9
    assert dict(sorted(not_decoded.items())) == NOT_YET_DECODED
    assert decoded == 718
    assert decoded + sum(NOT_YET_DECODED.values()) + 9 == len(CORPUS.vectors) == 2531


def test_every_directly_addressed_vector_of_the_subset_decodes() -> None:
    direct = [
        vector
        for vector in CORPUS.vectors
        if DIRECT_BIT.fullmatch(vector.stl) or DIRECT_DATA.fullmatch(vector.stl)
    ]
    assert len(direct) == 662
    assert [vector.line for vector in direct if decode_instruction(vector.data) is None] == []


def test_every_typed_constant_vector_decodes_except_pointers() -> None:
    constants = [v for v in CORPUS.vectors if v.data[0] in (0x28, 0x30, 0x38) and not v.is_invalid]
    missing = [v.stl for v in constants if decode_instruction(v.data) is None]
    assert len(constants) == 51
    assert sorted(set(missing)) == ["L P#DI27187.4", "L P#M0.0"]


def test_decoded_text_for_each_operand_kind() -> None:
    samples = {
        "00101234": "A I 4660.0",
        "09e71234": "R L 4660.7",
        "8355": "A M 85.3",
        "dfd5": "= Q 85.7",
        "4ad5": "L QB 85",
        "1b55": "T MD 85",
        "7e461234": "T DBW 4660",
        "7e011234": "L PIB 4660",
        "2812": "L B#16#18",
        "30021234": "L 2#1001000110100",
        "30039234": "L -28108",
        "30050041": "L 'A'",
        "30061234": "L B#(18, 52)",
        "30071234": "L W#16#1234",
        "30080888": "L C#888",
        "300a20bd": "L D#2012-12-12",
        "300c38ff": "L S5T#2H40M50S",
        "300c0000": "L S5T#0MS",
        "38014145851f": "L 12.345000",
        "3803deadbeef": "L L#-559038737",
        "380500444546": "L 'DEF'",
        "38060a140000": "L B#(10, 20, 00, 00)",
        "3807deadbeef": "L DW#16#deadbeef",
        "3809deadbeef": "L T#3735928559MS",
        "380b00402324": "L TOD#1:10:3.300",
        "6500": "BE",
    }
    for raw, text in samples.items():
        decoded = decode_instruction(bytes.fromhex(raw))
        assert decoded is not None, raw
        assert (decoded.text, len(decoded.data)) == (text, len(raw) // 2)


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "c1",
        "30081000",
        "300c3fff",
        "300cffff",
        "30050000",
        "30050007",
        "38017f800000",
        "00181234",
        "ffff",
        "0000",
        "3003",
        "380300",
    ],
)
def test_bytes_outside_the_table_are_not_decoded(raw: str) -> None:
    assert decode_instruction(bytes.fromhex(raw)) is None


@pytest.mark.parametrize("language", ["en", "de"])
def test_golden_disassembly_of_the_reference_block(
    language: str, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = Path(__file__).parent.parent
    monkeypatch.chdir(repository)
    relative = str(CM7.relative_to(repository))
    assert cli.main(["disasm", relative, "--mnemonics", language]) == 0
    captured = capsys.readouterr()
    golden = (GOLDEN / f"cm7.disasm.{language}.txt").read_text()
    assert captured.out == golden
    assert captured.err == ""
    assert "?? unknown opcode" not in golden
    assert "Coverage: 36 of 36 code bytes decoded, 0 unknown\n\nFindings\n  none\n" in golden


def test_reference_block_decodes_completely() -> None:
    result = disassemble(parse_image(CM7.read_bytes()))
    assert [entry.text for entry in result.entries if isinstance(entry, DecodedInstruction)] == [
        "A I 0.1",
        "FP M 0.0",
        "S Q 0.0",
        "A I 0.1",
        "FN M 0.1",
        "R Q 0.0",
        "A I 0.2",
        "CD C 0",
        "A I 0.3",
        "CU C 0",
        "LC C 0",
        "T QW 2",
        "L 13",
        "T QB 0",
        "BE",
    ]
    assert result.findings == ()
    assert (result.code_size, result.decoded_bytes, result.unknown_bytes) == (36, 36, 0)
    assert b"".join(entry.data for entry in result.entries) == result.image.payload


def test_german_mnemonics() -> None:
    german = disassemble(parse_image(CM7.read_bytes()), Mnemonics.DE)
    texts = [entry.text for entry in german.entries if isinstance(entry, DecodedInstruction)]
    assert texts[:3] == ["U E 0.1", "FP M 0.0", "S A 0.0"]
    assert texts[7:] == ["ZR Z 0", "U E 0.3", "ZV Z 0", "LC Z 0", "T AW 2", "L 13", "T AB 0", "BE"]
    assert decode_instruction(bytes.fromhex("00a01234"), Mnemonics.DE).text == "UN A 4660.0"  # type: ignore[union-attr]
    assert decode_instruction(bytes.fromhex("7e011234"), Mnemonics.DE).text == "L PEB 4660"  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("fixture", "code_size", "decoded", "unknown"),
    [
        ("blocks/reference/cm7.bin", 36, 36, 0),
        ("blocks/fake/OB1.mc7", 6, 2, 4),
        ("blocks/fake/FC1.mc7", 8, 2, 6),
    ],
)
def test_opcode_coverage_per_fixture(
    fixture: str, code_size: int, decoded: int, unknown: int
) -> None:
    result = disassemble(parse_image((FIXTURES / fixture).read_bytes()))
    assert (result.code_size, result.decoded_bytes, result.unknown_bytes) == (
        code_size,
        decoded,
        unknown,
    )
    assert sum(len(entry.data) for entry in result.entries) == code_size
    unknown_findings = [f for f in result.findings if f.code == "unknown-opcode"]
    assert len(unknown_findings) * 2 == unknown


def test_a_corrupted_byte_gives_an_explicit_unknown_opcode_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    raw = bytearray(CM7.read_bytes())
    assert raw[0x26] == 0x49
    raw[0x26] = 0x29
    path = tmp_path / "corrupt.bin"
    path.write_bytes(raw)
    assert cli.main(["disasm", str(path)]) == 0
    out = capsys.readouterr().out
    assert (
        "  0x0024  c1 00        A I 0.1\n"
        "  0x0026  29 30        ?? unknown opcode\n"
        "  0x0028  00 00        ?? unknown opcode\n"
        "  0x002a  d0 80        S Q 0.0\n"
    ) in out
    assert "Coverage: 32 of 36 code bytes decoded, 4 unknown\n" in out
    assert out.endswith(
        "Findings\n"
        "  warning: unknown opcode 29 30 at code offset 0x0002 (file offset 0x0026): "
        "no table row matches [unknown-opcode]\n"
        "  warning: unknown opcode 00 00 at code offset 0x0004 (file offset 0x0028): "
        "no table row matches [unknown-opcode]\n"
        "  warning: instruction boundaries after code offset 0x0002 are not certain: an unknown "
        "instruction may be longer than the bytes stepped over [boundaries-uncertain]\n"
    )


def test_unknown_entries_keep_every_byte_and_explain_themselves() -> None:
    entries = decode_code(bytes.fromhex("c100 ffff 30081000 3003 12"))
    assert [(type(e).__name__, e.offset, e.data.hex()) for e in entries] == [
        ("DecodedInstruction", 0, "c100"),
        ("UnknownOpcode", 2, "ffff"),
        ("UnknownOpcode", 4, "3008"),
        ("UnknownOpcode", 6, "1000"),
        ("UnknownOpcode", 8, "300312"),
    ]
    reasons = [entry.reason for entry in entries if isinstance(entry, UnknownOpcode)]
    assert reasons == [
        "no table row matches",
        "the operand value is one the corpus rejects",
        "no table row matches",
        "L needs 4 bytes, only 3 are left",
    ]
    assert decode_code(b"\xc1")[0] == UnknownOpcode(0, b"\xc1", "a single byte is left over")
    assert decode_code(b"") == ()


def test_an_unknown_opcode_at_the_very_end_does_not_question_boundaries() -> None:
    image = parse_image(make_block(mc7=bytes.fromhex("c100 ffff")))
    assert [finding.code for finding in disassemble(image).findings] == ["unknown-opcode"]


@pytest.mark.parametrize(
    ("block_type", "message"),
    [
        (mc7.blocks.BlockType.DB, "DB7 is a data block: its body holds values, not MC7 code"),
        (mc7.blocks.BlockType.SDB, "SDB7 is a system data block"),
        (mc7.blocks.BlockType.SFC, "SFC7 is a system block that lives in the CPU firmware"),
        (mc7.blocks.BlockType.SFB, "SFB7 is a system block that lives in the CPU firmware"),
    ],
)
def test_blocks_without_user_code_are_rejected(
    block_type: mc7.blocks.BlockType, message: str
) -> None:
    with pytest.raises(UnsupportedBlockError, match=message) as caught:
        disassemble(parse_image(make_block(block_type, 7)))
    assert "only OB, FC and FB can be disassembled" in str(caught.value)


def test_unknown_block_type_is_rejected() -> None:
    raw = bytearray(make_block())
    raw[5] = 0x55
    with pytest.raises(UnsupportedBlockError, match="type 0x55 #1 has an undocumented block type"):
        disassemble(parse_image(bytes(raw)))


def test_data_block_rejection_on_the_command_line(capsys: pytest.CaptureFixture[str]) -> None:
    path = FIXTURES / "blocks" / "fake" / "DB1.mc7"
    assert cli.main(["disasm", str(path)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        f"error: {path}: DB1 is a data block: its body holds values, not MC7 code; only OB, FC "
        "and FB can be disassembled (use 'mc7asm dump' to inspect the block)\n"
    )


@pytest.mark.parametrize("block_type", [mc7.blocks.BlockType.OB, mc7.blocks.BlockType.FB])
def test_layout_violations_are_reported_and_the_code_is_decoded_anyway(
    block_type: mc7.blocks.BlockType,
) -> None:
    raw = bytearray(make_block(block_type, 3, mc7=bytes.fromhex("c100 6500"), unaccounted=bytes(5)))
    struct.pack_into(">I", raw, 8, len(raw) + 7)
    result = disassemble(parse_image(bytes(raw)))
    assert [finding.code for finding in result.findings] == ["length-field", "trailing-unknown"]
    assert [finding.severity for finding in result.findings] == [Severity.WARNING, Severity.NOTE]
    assert [entry.data.hex() for entry in result.entries] == ["c100", "6500"]
    assert result.unknown_bytes == 0


def test_mnemonics_option_is_validated() -> None:
    with pytest.raises(SystemExit) as caught:
        cli.main(["disasm", str(CM7), "--mnemonics", "fr"])
    assert caught.value.code == 2
