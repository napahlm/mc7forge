"""Every block fixture must survive a parse and re-serialize unchanged.

The blocks in ``real/`` were uploaded from a CPU. They are confidential and not
in the repository, so the tests on blocks from a CPU also run on the reference
block alone. The synthetic blocks in ``fake/`` say nothing about the layout of
a real block and are not held to those tests.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from mc7asm import BlockImage, BlockType, Severity, parse_image, validate_image
from scripts import capture_fixtures
from tests.support import reference_blocks

FIXTURES = Path(__file__).parent / "fixtures" / "blocks"
ALL_FIXTURES = sorted([*FIXTURES.rglob("*.mc7"), *FIXTURES.rglob("*.bin")])
NAMED_FIXTURES = [path for path in ALL_FIXTURES if path.suffix == ".mc7"]
FAKE_FIXTURES = sorted((FIXTURES / "fake").glob("*.mc7"))
REAL_FIXTURES = sorted((FIXTURES / "real").glob("*.mc7"))
CPU_BLOCKS = [FIXTURES / "reference" / "cm7.bin", *REAL_FIXTURES]
BLOCK_END = bytes.fromhex("6500")
CODE_BLOCK_TYPES = (BlockType.OB, BlockType.FC, BlockType.FB)


def load(path: Path) -> BlockImage:
    return parse_image(path.read_bytes())


CPU_CODE_BLOCKS = [path for path in CPU_BLOCKS if load(path).header.block_type in CODE_BLOCK_TYPES]
CPU_DATA_BLOCKS = [path for path in CPU_BLOCKS if load(path).header.block_type is BlockType.DB]


def fixture_id(path: Path) -> str:
    return str(path.relative_to(FIXTURES))


def test_the_fake_corpus_is_committed() -> None:
    assert [path.name for path in FAKE_FIXTURES] == ["DB1.mc7", "FC1.mc7", "OB1.mc7"]
    assert set(FAKE_FIXTURES) <= set(ALL_FIXTURES)


@pytest.mark.parametrize("path", ALL_FIXTURES, ids=fixture_id)
def test_fixture_reserializes_byte_for_byte(path: Path) -> None:
    raw = path.read_bytes()
    image = parse_image(raw)
    assert image.to_bytes() == raw
    assert b"".join(section.data for section in image.sections()) == raw
    assert image.size == len(raw)


@pytest.mark.parametrize("path", NAMED_FIXTURES, ids=fixture_id)
def test_fixture_name_matches_its_header(path: Path) -> None:
    assert parse_image(path.read_bytes()).header.name == path.stem


@pytest.mark.parametrize("path", FAKE_FIXTURES, ids=fixture_id)
def test_fake_fixture_has_exactly_the_documented_layout(path: Path) -> None:
    image = parse_image(path.read_bytes())
    assert validate_image(image) == []
    assert image.declared_layout_fits
    assert image.trailing_unknown == b""
    assert image.header.length == image.size


@pytest.mark.parametrize("path", ALL_FIXTURES, ids=fixture_id)
def test_fixture_sections_fit_between_header_and_footer(path: Path) -> None:
    findings = validate_image(parse_image(path.read_bytes()))
    assert [f for f in findings if f.severity is Severity.ERROR] == []


def test_fake_fixtures_are_what_the_capture_script_produces(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert capture_fixtures.main(["--fake", "--output", str(tmp_path)]) == 0
    produced = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    committed = {path.name: path.read_bytes() for path in FAKE_FIXTURES}
    assert produced == committed
    assert set(committed.values()) == set(reference_blocks().values())
    assert capsys.readouterr().out.count("trailing unknown 0)") == 3


def test_reference_block_has_exactly_the_documented_layout() -> None:
    path = FIXTURES / "reference" / "cm7.bin"
    assert path in ALL_FIXTURES
    image = parse_image(path.read_bytes())
    header = image.header
    assert (header.name, header.length, image.size) == ("OB1", 142, 142)
    assert (header.mc7_length, header.interface_length, header.segment_table_length) == (36, 28, 6)
    assert validate_image(image) == []
    assert image.payload[-2:] == bytes.fromhex("6500")
    assert image.interface[:6] == bytes.fromhex("010000140000")
    assert image.segment_table == bytes.fromhex("010022000000")


# ---------------------------------------------------------------------- blocks from a CPU


@pytest.mark.parametrize("path", CPU_BLOCKS, ids=fixture_id)
def test_cpu_block_adds_up_with_no_byte_left_over(path: Path) -> None:
    image = load(path)
    header = image.header
    assert header.length == image.size == path.stat().st_size
    assert image.size == (
        36 + header.mc7_length + header.interface_length + header.segment_table_length + 36
    )
    assert image.declared_layout_fits
    assert image.trailing_unknown == b""
    assert validate_image(image) == []


@pytest.mark.parametrize("path", CPU_BLOCKS, ids=fixture_id)
def test_cpu_block_interface_follows_its_sub_header(path: Path) -> None:
    image = load(path)
    parts = image.interface_parts
    assert parts is not None
    is_data = image.header.block_type is BlockType.DB
    assert parts.header.kind == (0x05 if is_data else 0x01)
    assert len(parts.declarations) == parts.header.declarations_length
    assert parts.start_values == b"", (
        "a block with start values: TODO(real-db-fixture) can be settled"
    )
    assert len(parts.rest) == 1, "every block seen so far has one byte after the declarations"
    if not is_data:
        assert parts.header.number == 0


@pytest.mark.parametrize("path", CPU_CODE_BLOCKS, ids=fixture_id)
def test_cpu_code_block_ends_with_block_end_outside_its_networks(path: Path) -> None:
    image = load(path)
    code = image.payload
    assert code[-2:] == BLOCK_END
    assert len(image.segment_table) % 2 == 0
    words = struct.unpack(f"<{len(image.segment_table) // 2}H", image.segment_table)
    count = words[0]
    lengths, tail = words[1 : 1 + count], words[1 + count :]
    assert count >= 1
    assert len(lengths) == count
    assert sum(lengths) + len(BLOCK_END) == image.header.mc7_length
    # After the lengths: a count of positions, the positions, and in the blocks
    # written in FBD one more word of unknown meaning.
    positions = tail[1 : 1 + tail[0]]
    assert len(positions) == tail[0]
    assert len(tail) - 1 - tail[0] in (0, 1)
    assert len(set(positions)) == len(positions)
    assert all(2 * position < len(code) for position in positions)


@pytest.mark.parametrize("path", CPU_DATA_BLOCKS, ids=fixture_id)
def test_cpu_data_block_is_values_then_declarations(path: Path) -> None:
    image = load(path)
    header = image.header
    assert (header.segment_table_length, header.local_data_length) == (0, 0)
    assert header.language == 5
    assert len(image.payload) == header.mc7_length
    assert image.segment_table == b""
