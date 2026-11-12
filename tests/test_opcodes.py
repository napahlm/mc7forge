"""Invariants of the opcode table."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from mc7asm.corpus import load_corpus
from mc7asm.disasm import decode_instruction
from mc7asm.opcodes import (
    GERMAN_AREAS,
    GERMAN_MNEMONICS,
    OPCODE_TABLE,
    Operand,
    Scope,
    Status,
    find_row,
)
from scripts import gen_opcode_docs

CORPUS = load_corpus(Path(__file__).parent / "fixtures" / "corpus" / "test_simatic.c")


def test_table_size_and_scopes() -> None:
    assert len(OPCODE_TABLE) == 156
    assert Counter(row.scope for row in OPCODE_TABLE) == {
        Scope.MINIMAL: 140,
        Scope.REFERENCE_BLOCK: 16,
    }
    assert {row.mnemonic for row in OPCODE_TABLE if row.scope is Scope.MINIMAL} == set(
        ["A", "AN", "O", "ON", "=", "S", "R", "L", "T"]
    )
    assert {row.mnemonic for row in OPCODE_TABLE if row.scope is Scope.REFERENCE_BLOCK} == set(
        ["FP", "FN", "LC", "CD", "CU", "BE"]
    )


def test_no_two_rows_claim_the_same_bytes() -> None:
    assert len({row.key for row in OPCODE_TABLE}) == len(OPCODE_TABLE)
    for first in range(256):
        for second in range(256):
            claims = [row for row in OPCODE_TABLE if row.matches(first, second)]
            assert len(claims) <= 1, (first, second)
            assert find_row(first, second) is (claims[0] if claims else None)


def test_every_row_is_exercised_by_the_corpus() -> None:
    used: Counter[str] = Counter()
    for vector in CORPUS.vectors:
        decoded = decode_instruction(vector.data)
        if decoded is not None:
            used[decoded.row.key] += 1
    assert [row.key for row in OPCODE_TABLE if not used[row.key]] == []


def test_rows_are_well_formed() -> None:
    for row in OPCODE_TABLE:
        assert len(row.opcode) == len(row.mask) == 2
        assert bytes(o & m for o, m in zip(row.opcode, row.mask, strict=True)) == row.opcode
        assert row.length in (2, 4, 6)
        assert row.source.startswith("MC7toAWL.cs ")
        assert (row.area == "") == (
            row.operand is Operand.NONE
            or (row.mnemonic == "L" and row.opcode[0] in (0x28, 0x30, 0x38))
        )
        if row.status is not Status.VERIFIED:
            assert row.note


def test_disagreements_with_the_csharp_decoder_are_marked() -> None:
    by_status = Counter(row.status for row in OPCODE_TABLE)
    assert by_status == {Status.VERIFIED: 143, Status.NOTATION: 12, Status.UNVERIFIED: 1}
    (unverified,) = (row for row in OPCODE_TABLE if row.status is Status.UNVERIFIED)
    assert (unverified.opcode, unverified.operand) == (b"\x28\x00", Operand.BYTE_HEX)
    assert "B#16#18" in unverified.note


def test_german_spelling_exists_for_everything_in_the_table() -> None:
    assert {row.mnemonic for row in OPCODE_TABLE} == set(GERMAN_MNEMONICS)
    assert {row.area for row in OPCODE_TABLE if row.area} == set(GERMAN_AREAS)
    assert (GERMAN_MNEMONICS["A"], GERMAN_MNEMONICS["AN"]) == ("U", "UN")
    assert (GERMAN_AREAS["I"], GERMAN_AREAS["Q"], GERMAN_AREAS["C"]) == ("E", "A", "Z")
    assert (GERMAN_AREAS["QW"], GERMAN_AREAS["PIB"], GERMAN_AREAS["PQD"]) == ("AW", "PEB", "PAD")


def test_opcode_document_is_generated_from_the_table() -> None:
    document = gen_opcode_docs.DOCUMENT.read_text(encoding="utf-8")
    assert gen_opcode_docs.render(document) == document
    assert gen_opcode_docs.main(["--check"]) == 0
    table = gen_opcode_docs.table_markdown().splitlines()
    assert len(table) == 2 + len(OPCODE_TABLE)
    assert "| `c0 00` | `f8 80` | `A` | `I` |" in document
    assert "| unverified |" in document
