"""The documentation is a deliverable: numbers, tables and links are checked against the code."""

from __future__ import annotations

import hashlib
import re
import struct
from collections import Counter
from pathlib import Path

import pytest

from mc7asm.corpus import load_corpus
from mc7asm.disasm import decode_instruction
from mc7asm.opcodes import OPCODE_TABLE
from scripts import build_examples
from tests import test_roundtrip

REPOSITORY = Path(__file__).parent.parent
DOCS = REPOSITORY / "docs"
CM7 = REPOSITORY / "tests" / "fixtures" / "blocks" / "reference" / "cm7.bin"
REAL = REPOSITORY / "tests" / "fixtures" / "blocks" / "real"
DOCUMENTS = sorted(
    [
        REPOSITORY / "README.md",
        *DOCS.glob("*.md"),
        REPOSITORY / "examples" / "README.md",
        *(REPOSITORY / "tests" / "fixtures").rglob("README.md"),
    ]
)
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
# Struct layouts of mc7asm.image, restated here so a change on either side is noticed.
HEADER_SIZES = (2, 1, 1, 1, 1, 2, 4, 4, 6, 6, 2, 2, 2, 2)
FOOTER_SIZES = (8, 8, 8, 1, 1, 2, 8)


def table_after(text: str, heading: str) -> list[list[str]]:
    """Return the cells of the first table that follows ``heading``."""
    lines = text[text.index(heading) :].splitlines()
    start = next(index for index, line in enumerate(lines) if line.startswith("|"))
    rows = []
    for line in lines[start + 2 :]:
        if not line.startswith("|"):
            break
        rows.append([cell.strip() for cell in line.strip("|").split("|")])
    return rows


def slug(heading: str) -> str:
    """The anchor GitHub derives from a heading."""
    text = re.sub(r"[^\w\- ]", "", heading.strip().lower())
    return text.replace(" ", "-")


def test_the_expected_documents_exist() -> None:
    names = {path.name for path in DOCS.glob("*.md")}
    assert names == {
        "assembler.md",
        "container.md",
        "decisions.md",
        "mc7-structure.md",
        "opcodes.md",
    }
    assert len(DOCUMENTS) == 10


@pytest.mark.parametrize("document", DOCUMENTS, ids=lambda path: str(path.relative_to(REPOSITORY)))
def test_links_point_at_something_that_exists(document: Path) -> None:
    text = document.read_text(encoding="utf-8")
    anchors = {slug(line.lstrip("#")) for line in text.splitlines() if line.startswith("#")}
    for target in LINK.findall(text):
        if target.startswith(("http://", "https://")):
            continue
        path, _, anchor = target.partition("#")
        if not path:
            assert anchor in anchors, f"{document.name}: no heading for #{anchor}"
            continue
        assert (document.parent / path).exists(), f"{document.name}: broken link {target}"


@pytest.mark.parametrize("document", DOCUMENTS, ids=lambda path: str(path.relative_to(REPOSITORY)))
def test_documents_follow_the_house_style(document: Path) -> None:
    text = document.read_text(encoding="utf-8")
    assert "—" not in text, "use a plain dash, not an em dash"
    assert not [line for line in text.splitlines() if line != line.rstrip()]
    assert text.endswith("\n")


def test_header_field_map_matches_the_code_and_the_reference_block() -> None:
    rows = table_after((DOCS / "mc7-structure.md").read_text(), "## Header")
    assert [(int(row[0]), int(row[1])) for row in rows] == [
        (sum(HEADER_SIZES[:index]), size) for index, size in enumerate(HEADER_SIZES)
    ]
    assert struct.calcsize(">2sBBBBHI4s6s6sHHHH") == sum(HEADER_SIZES) == 36
    reference = CM7.read_bytes()
    for row in rows:
        offset, size, quoted = int(row[0]), int(row[1]), row[5].strip("`")
        assert bytes.fromhex(quoted) == reference[offset : offset + size], row[2]


def test_footer_field_map_matches_the_code_and_the_reference_block() -> None:
    rows = table_after((DOCS / "mc7-structure.md").read_text(), "## Footer")
    assert [(int(row[0]), int(row[1])) for row in rows] == [
        (sum(FOOTER_SIZES[:index]), size) for index, size in enumerate(FOOTER_SIZES)
    ]
    assert struct.calcsize(">8s8s8sBBH8s") == sum(FOOTER_SIZES) == 36
    footer = CM7.read_bytes()[-36:]
    for row in rows:
        offset, size, quoted = int(row[0]), int(row[1]), row[4].strip("`")
        expected = bytes(size) if quoted == "zeros" else bytes.fromhex(quoted)
        assert footer[offset : offset + size] == expected, row[2]


def test_interface_and_segment_table_quoted_in_the_field_map_are_the_real_bytes() -> None:
    text = (DOCS / "mc7-structure.md").read_text()
    reference = CM7.read_bytes()
    blocks = [block.strip() for block in re.findall(r"```text\n(.*?)```", text, re.S)]
    quoted = [bytes.fromhex(block) for block in blocks if re.fullmatch(r"[0-9a-f\s]+", block)]
    from_reference = [reference[72:100], reference[100:106]]
    assert [chunk for chunk in quoted if chunk in from_reference] == from_reference
    from_captures = [chunk for chunk in quoted if chunk not in from_reference]
    assert len(from_captures) == 5
    captures = [path.read_bytes() for path in sorted(REAL.glob("*.mc7"))]
    if not captures:
        pytest.skip("the real captures are not part of this checkout")
    for chunk in from_captures:
        assert any(chunk in capture for capture in captures), chunk.hex(" ")


def test_decision_log_outcome_table_is_what_the_loop_produces() -> None:
    corpus = load_corpus(REPOSITORY / "tests" / "fixtures" / "corpus" / "test_simatic.c")
    outcomes: Counter[str] = Counter()
    for vector in corpus.vectors:
        covered = decode_instruction(vector.data) is not None
        outcome, _data = test_roundtrip.loop(vector)
        outcomes[("covered" if covered else "outside") + ": " + outcome] += 1
    rows = table_after((DOCS / "decisions.md").read_text(), "**Outcome of the full loop.**")
    assert [int(row[1].replace(",", "")) for row in rows] == [
        outcomes["covered: identical"],
        outcomes["covered: different"],
        outcomes["covered: not yet supported"],
        outcomes["outside: syntax error"],
        outcomes["outside: not yet supported"],
        len(corpus.vectors),
    ]
    assert sum(outcomes.values()) == len(corpus.vectors) == 2531
    readme = (REPOSITORY / "README.md").read_text()
    for number in ("2,531", "718", "714", "156 instruction forms"):
        assert number in readme
    assert len(OPCODE_TABLE) == 156


def test_decision_log_names_the_image_a_cpu_accepted() -> None:
    """D16 is evidence about one exact image; a changed image is no longer covered by it."""
    text = (DOCS / "decisions.md").read_text()
    entry = text[text.index("## D16.") :]
    image = build_examples.EXPECTED / "orphan.mc7"
    assert f"SHA-256 `{hashlib.sha256(image.read_bytes()).hexdigest()}`" in entry
    assert f"{image.stat().st_size} bytes" in entry


def test_examples_index_lists_every_example() -> None:
    rows = table_after((REPOSITORY / "examples" / "README.md").read_text(), "# Examples")
    listed = {row[0].strip("`"): row[3].strip("`") for row in rows}
    sources = {path.name for path in build_examples.EXAMPLES.glob("*.awl")}
    assert set(listed) == sources
    for source, image in listed.items():
        if image == "none":
            assert Path(source).stem in build_examples.REFUSED
        else:
            assert image == f"expected/{Path(source).stem}.mc7"
            assert (build_examples.EXAMPLES / image).is_file()
