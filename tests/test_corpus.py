"""The vendored opcode corpus: strict parsing, pinned identity and pinned counts."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from mc7asm.corpus import DECODE_BASE_ADDRESS, Corpus, CorpusVector, load_corpus, parse_corpus
from mc7asm.errors import CorpusFormatError, Mc7AsmError

FIXTURES = Path(__file__).parent / "fixtures"
CORPUS_FILE = FIXTURES / "corpus" / "test_simatic.c"
REFERENCE_BLOCK = FIXTURES / "blocks" / "reference" / "cm7.bin"

# Active vectors per mnemonic of the minimal subset. A mnemonic is the first
# token of the expected text, so the nesting forms "A(" and so on are separate.
SUBSET_COUNTS = {"L": 234, "T": 164, "A": 146, "AN": 143, "O": 144, "ON": 143}
SUBSET_COUNTS |= {"=": 140, "S": 123, "R": 131}


@pytest.fixture(scope="module")
def corpus() -> Corpus:
    return load_corpus(CORPUS_FILE)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_vendored_files_are_the_pinned_upstream_versions() -> None:
    assert CORPUS_FILE.stat().st_size == 160_984
    assert sha256(CORPUS_FILE) == "8a93f7ada52c6636f0eef58b9f8fb03b838bad8a766624d6273d9e264ef0d886"
    assert sha256(REFERENCE_BLOCK) == (
        "089f010eb69a6795690d40596eacd094c67f3f46e29b8e91f3e9532a93767c29"
    )
    for directory in (CORPUS_FILE.parent, REFERENCE_BLOCK.parent):
        license_text = (directory / "LGPL-3.0-only.txt").read_text()
        assert license_text.startswith("GNU LESSER GENERAL PUBLIC LICENSE\nVersion 3")
        assert "LGPL-3.0-only" in (directory / "README.md").read_text()


def test_vector_totals(corpus: Corpus) -> None:
    assert len(corpus.vectors) == 2531
    assert len(corpus.disabled) == 9
    assert sum(vector.is_invalid for vector in corpus.vectors) == 9
    # 2531 active + 9 disabled + 1 terminator is every __LINE__ token in the file.
    assert CORPUS_FILE.read_text().count("__LINE__") == 2531 + 9 + 1
    assert len({vector.line for vector in corpus.vectors}) == 2531
    assert len(corpus.mnemonic_counts()) == 154


def test_minimal_subset_counts(corpus: Corpus) -> None:
    counts = corpus.mnemonic_counts()
    assert {mnemonic: counts[mnemonic] for mnemonic in SUBSET_COUNTS} == SUBSET_COUNTS


def test_counts_reconcile_with_a_loose_count_of_the_file(corpus: Corpus) -> None:
    """A looser count gives L 237, A 147, AN 144, O 145, ON 144; this is why."""
    counts = corpus.mnemonic_counts()
    disabled_loads = [vector for vector in corpus.disabled if vector.mnemonic == "L"]
    assert [vector.stl for vector in disabled_loads] == ["L P#M2.0", "L P#M0.1", "L P#M0.2"]
    assert counts["L"] + len(disabled_loads) == 237
    assert {name: counts[name] + counts[f"{name}("] for name in ("A", "AN", "O", "ON")} == {
        "A": 147,
        "AN": 144,
        "O": 145,
        "ON": 144,
    }
    assert sorted(vector.stl for vector in corpus.disabled if vector.mnemonic != "L") == [
        "<=I",
        "<>I",
        "<I",
        "==I",
        ">=I",
        ">I",
    ]


def test_vector_fields(corpus: Corpus) -> None:
    first, last = corpus.vectors[0], corpus.vectors[-1]
    assert first == CorpusVector(18, "NOP 0", 2, 2, b"\x00\x00")
    assert last == CorpusVector(2608, "OPN [P#7.0]", 4, 4, bytes.fromhex("fbd8000e"))
    assert {vector.read for vector in corpus.vectors} == {-1, 2, 4, 6}
    assert all(vector.size == len(vector.data) for vector in corpus.vectors)
    assert all(vector.read == vector.size for vector in corpus.vectors if not vector.is_invalid)
    assert {vector.stl for vector in corpus.vectors if vector.is_invalid} == {"invalid"}
    assert DECODE_BASE_ADDRESS == 0x80000000


def test_no_byte_sequence_has_two_meanings(corpus: Corpus) -> None:
    meanings: dict[bytes, set[str]] = {}
    for vector in corpus.vectors:
        meanings.setdefault(vector.data, set()).add(vector.stl)
    assert [data.hex() for data, texts in meanings.items() if len(texts) > 1] == []


HEAD = "const s7_test_t tests[] = {"
VECTOR = '\t{ __LINE__, "NOP 0", 2, 2, { 0x00, 0x00 } },'
END = "\t{ __LINE__, NULL, -1, 0, { 0x00 } },\n};"


def source(*lines: str) -> str:
    return "\n".join(("int x;", HEAD, *lines, END, ""))


def test_parser_reads_each_line_kind() -> None:
    corpus = parse_corpus(
        source(
            "\t// section",
            VECTOR,
            '\t{ __LINE__, "invalid", -1, 2, { 0x29, 0xAb } },',
            '\t// FIXME {__LINE__, "==I",     2, 2, {0x21, 0x80}},',
        )
    )
    assert corpus.vectors == (
        CorpusVector(4, "NOP 0", 2, 2, b"\x00\x00"),
        CorpusVector(5, "invalid", -1, 2, b"\x29\xab"),
    )
    assert corpus.disabled == (CorpusVector(6, "==I", 2, 2, b"\x21\x80"),)
    assert corpus.vectors[1].is_invalid
    assert corpus.mnemonic_counts() == {"NOP": 1}


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ('\t{ __LINE__, "NOP 0", 2, 2, { 0x00, 0x0 } },', "line 3: not a test vector"),
        ('\t{ __LINE__, "NOP 0", 2, 2, { 0x00, 0x00 } }', "line 3: not a test vector"),
        ('    { __LINE__, "NOP 0", 2, 2, { 0x00, 0x00 } },', "line 3: not a test vector"),
        ("", "line 3: not a test vector"),
        ("#if 0", "line 3: not a test vector"),
        ('\t{ __LINE__, "NOP 0", 2, 3, { 0x00, 0x00 } },', "line 3: size 3 does not match"),
        ('\t{ __LINE__, "NOP 0", -1, 2, { 0x00, 0x00 } },', "line 3: inconsistent read"),
        ('\t{ __LINE__, "invalid", 2, 2, { 0x00, 0x00 } },', "line 3: inconsistent read"),
        ('\t{ __LINE__, "NOP 0", 4, 2, { 0x00, 0x00 } },', "line 3: inconsistent read"),
    ],
)
def test_parser_rejects_anything_it_does_not_understand(line: str, message: str) -> None:
    with pytest.raises(CorpusFormatError, match=message) as caught:
        parse_corpus(source(line))
    assert isinstance(caught.value, Mc7AsmError)


def test_parser_needs_the_array_and_its_terminator() -> None:
    with pytest.raises(CorpusFormatError, match="cannot find the tests"):
        parse_corpus("int main() {}\n")
    with pytest.raises(CorpusFormatError, match="does not end with the NULL terminator"):
        parse_corpus("\n".join((HEAD, VECTOR, "};", "")))
