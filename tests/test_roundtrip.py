"""The correctness loop over the whole corpus: bytes -> disasm -> parse -> codegen -> bytes.

Every one of the 2,531 corpus vectors is put through the loop and must end in
exactly one of these outcomes, each of them pinned:

* the bytes come back identical (the vectors the opcode table covers),
* the parser rejects the text with a syntax error (text outside the STL subset),
* the code generator refuses with "not yet supported" (parsed, but no usable row),
* the bytes come back different because the vector is not the canonical
  encoding of its text. These few vectors are listed with the bytes the
  assembler produces instead.

Nothing may crash and nothing may assemble to bytes that no vector asked for.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from mc7asm import (
    Mc7SyntaxError,
    Mnemonics,
    NotYetSupportedError,
    compile_instruction,
    parse_statement,
)
from mc7asm.corpus import CorpusVector, load_corpus
from mc7asm.disasm import decode_instruction
from mc7asm.opcodes import Scope
from mc7asm.printer import format_instruction

CORPUS = load_corpus(Path(__file__).parent / "fixtures" / "corpus" / "test_simatic.c")

# Source line -> (vector bytes, bytes the assembler produces for the same text).
NOT_CANONICAL = {
    # The digits 8, F, F are not decimal; 9650 s is written canonically as 965 x 10 s.
    463: ("300c38ff", "300c3965"),
    # A 32-bit binary constant whose value fits 16 bits; the text does not show the width.
    480: ("380200000000", "30020000"),
}
# Source lines of the two B#16# vectors, whose row is unverified and therefore refused.
REFUSED_UNVERIFIED = {443, 2435}


def loop(vector: CorpusVector) -> tuple[str, bytes | None]:
    """Run one vector through parse and codegen and classify the outcome."""
    try:
        instruction = parse_statement(vector.stl)
    except Mc7SyntaxError:
        return "syntax error", None
    try:
        _row, data = compile_instruction(instruction)
    except NotYetSupportedError:
        return "not yet supported", None
    assert format_instruction(instruction) == vector.stl, f"line {vector.line}"
    return ("identical" if data == vector.data else "different"), data


def test_every_decodable_vector_goes_round_the_loop() -> None:
    outcomes: Counter[str] = Counter()
    different: dict[int, tuple[str, str]] = {}
    refused: set[int] = set()
    for vector in CORPUS.vectors:
        decoded = decode_instruction(vector.data)
        if decoded is None:
            continue
        assert decoded.text == vector.stl
        outcome, data = loop(vector)
        outcomes[outcome] += 1
        if outcome == "different":
            assert data is not None
            different[vector.line] = (vector.data.hex(), data.hex())
        elif outcome == "not yet supported":
            refused.add(vector.line)
    assert outcomes == {"identical": 714, "different": 2, "not yet supported": 2}
    assert different == NOT_CANONICAL
    assert refused == REFUSED_UNVERIFIED
    assert sum(outcomes.values()) == 718


def test_the_minimal_subset_round_trips_except_for_the_listed_vectors() -> None:
    exceptions = set(NOT_CANONICAL) | REFUSED_UNVERIFIED
    checked = 0
    for vector in CORPUS.vectors:
        decoded = decode_instruction(vector.data)
        if decoded is None or decoded.row.scope is not Scope.MINIMAL:
            continue
        checked += 1
        if vector.line in exceptions:
            continue
        outcome, data = loop(vector)
        assert (outcome, data) == ("identical", vector.data), f"line {vector.line}: {vector.stl}"
    assert checked == 614
    assert checked - len(exceptions) == 610


def test_vectors_outside_the_table_never_assemble() -> None:
    outcomes: Counter[str] = Counter()
    parsed: Counter[str] = Counter()
    for vector in CORPUS.vectors:
        if decode_instruction(vector.data) is not None:
            continue
        outcome, _data = loop(vector)
        outcomes[outcome] += 1
        if outcome != "syntax error":
            parsed[vector.stl] += 1
    assert outcomes == {"syntax error": 1807, "not yet supported": 6}
    assert parsed == {"A(": 1, "AN(": 1, "O(": 1, "ON(": 1, ")": 2}
    assert sum(outcomes.values()) + 718 == len(CORPUS.vectors) == 2531


def test_not_canonical_vectors_assemble_to_a_decodable_equivalent() -> None:
    for line, (original, produced) in NOT_CANONICAL.items():
        vector = next(v for v in CORPUS.vectors if v.line == line)
        assert vector.data.hex() == original
        mine = decode_instruction(bytes.fromhex(produced))
        assert mine is not None
        assert mine.text == vector.stl
        assert len(produced) <= len(original)


def test_german_text_goes_round_the_loop_too() -> None:
    checked = 0
    for vector in CORPUS.vectors:
        german = decode_instruction(vector.data, Mnemonics.DE)
        if german is None or vector.line in set(NOT_CANONICAL) | REFUSED_UNVERIFIED:
            continue
        instruction = parse_statement(german.text, Mnemonics.DE)
        assert compile_instruction(instruction)[1] == vector.data, f"line {vector.line}"
        assert format_instruction(instruction, Mnemonics.DE) == german.text
        checked += 1
    assert checked == 714
