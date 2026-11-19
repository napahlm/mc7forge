"""End to end: source -> assemble -> validate -> disassemble -> re-assemble, per example.

Every example in ``examples/`` that has an expected image goes through the
whole chain. The built image must match the committed image field for field,
the disassembly must assemble back to the same code, and the source printed
from the IR must build the same image again.
"""

from __future__ import annotations

import struct
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

from mc7asm import (
    BlockImage,
    BlockType,
    Mnemonics,
    build_block,
    compile_block,
    compile_instruction,
    disassemble,
    parse_file,
    parse_image,
    parse_source,
    parse_statement,
    validate_generated_image,
    validate_image,
)
from mc7asm.disasm import DecodedInstruction, Entry, decode_code
from mc7asm.printer import format_source
from scripts import build_examples

REPOSITORY = Path(__file__).parent.parent
CM7 = REPOSITORY / "tests" / "fixtures" / "blocks" / "reference" / "cm7.bin"
SOURCES = build_examples.sources()
BLOCK_END = bytes.fromhex("6500")


def expected_image(source: Path) -> bytes:
    return (build_examples.EXPECTED / f"{source.stem}.mc7").read_bytes()


def field_map(image: BlockImage) -> dict[str, object]:
    """Every header field, section and footer field of an image under its own name."""
    header, footer = image.header, image.footer
    fields: dict[str, object] = {
        f"header.{name}": getattr(header, name) for name in header.__dataclass_fields__
    }
    fields |= {
        "code": image.payload,
        "interface": image.interface,
        "segment_table": image.segment_table,
        "trailing_unknown": image.trailing_unknown,
    }
    fields |= {f"footer.{name}": getattr(footer, name) for name in footer.__dataclass_fields__}
    return fields


def differing_fields(left: BlockImage, right: BlockImage) -> list[str]:
    a, b = field_map(left), field_map(right)
    return [name for name in a if a[name] != b[name]]


def texts(entries: Sequence[Entry]) -> list[str]:
    """The statements of a listing; an unknown opcode fails the test."""
    assert all(isinstance(entry, DecodedInstruction) for entry in entries)
    return [entry.text for entry in entries if isinstance(entry, DecodedInstruction)]


def source_id(source: Path) -> str:
    return source.stem


def test_every_example_has_exactly_one_expected_image() -> None:
    assert len(SOURCES) == 14
    images = sorted(path.stem for path in build_examples.EXPECTED.glob("*.mc7"))
    assert images == [source.stem for source in SOURCES]
    assert build_examples.main(["--check"]) == 0
    refused = sorted(path.stem for path in build_examples.EXAMPLES.glob("*.awl"))
    assert sorted([*images, *build_examples.REFUSED]) == refused


@pytest.mark.parametrize("source", SOURCES, ids=source_id)
def test_built_image_matches_the_committed_image_field_for_field(source: Path) -> None:
    built = parse_image(build_examples.build_example(source))
    committed = parse_image(expected_image(source))
    assert differing_fields(built, committed) == []
    assert built.to_bytes() == expected_image(source)
    assert validate_generated_image(built) == []
    assert validate_image(committed) == []


@pytest.mark.parametrize("source", SOURCES, ids=source_id)
def test_disassembly_assembles_back_to_the_same_code(source: Path) -> None:
    mnemonics = build_examples.mnemonics_of(source)
    image = parse_image(expected_image(source))
    listing = disassemble(image, mnemonics)
    assert listing.unknown_bytes == 0
    assert listing.findings == ()
    statements = texts(listing.entries)
    assert statements[-1] == "BE"
    reassembled = b"".join(
        compile_instruction(parse_statement(text, mnemonics))[1] for text in statements
    )
    assert reassembled == image.payload
    # A second pass changes nothing: the loop has reached a fixed point.
    assert texts(decode_code(reassembled, mnemonics)) == statements


@pytest.mark.parametrize("source", SOURCES, ids=source_id)
def test_source_printed_from_the_ir_builds_the_same_image(source: Path) -> None:
    mnemonics = build_examples.mnemonics_of(source)
    block = parse_file(source, mnemonics)
    for spelling in Mnemonics:
        text = format_source(block, spelling)
        again = parse_source(text, "printed.awl", spelling)
        assert again == block
        assert [network.comment for network in again.networks] == [
            network.comment for network in block.networks
        ]
        assert format_source(again, spelling) == text
        rebuilt = build_block(compile_block(again), build_examples.TIMESTAMP)
        assert rebuilt.image.to_bytes() == expected_image(source)


@pytest.mark.parametrize("source", SOURCES, ids=source_id)
def test_code_is_the_compiled_body_plus_block_end(source: Path) -> None:
    compiled = compile_block(parse_file(source, build_examples.mnemonics_of(source)))
    image = parse_image(expected_image(source))
    assert image.payload == compiled.body + BLOCK_END
    assert image.header.mc7_length == compiled.size + 2


# ---------------------------------------------------------------------- structure


def code_block_images() -> list[tuple[str, BlockImage]]:
    images = [(source.stem, parse_image(expected_image(source))) for source in SOURCES]
    return [*images, ("cm7.bin", parse_image(CM7.read_bytes()))]


@pytest.mark.parametrize(("name", "image"), code_block_images(), ids=lambda value: str(value)[:24])
def test_container_structure_is_the_one_of_the_reference_block(
    name: str, image: BlockImage
) -> None:
    header = image.header
    assert (
        header.length
        == image.size
        == 36 + header.mc7_length + header.interface_length + (header.segment_table_length + 36)
    )
    assert (header.version, header.attributes, header.language) == (1, 1, 1)
    assert header.password == bytes(4)
    assert image.trailing_unknown == b""
    assert image.payload.endswith(BLOCK_END)

    marker, number, declared, start_values = struct.unpack_from("<BHHH", image.interface)
    is_ob = header.block_type is BlockType.OB
    assert (marker, number, start_values) == (0x01, 0, 0)
    assert len(image.interface) == 7 + declared + 1
    assert image.interface[-1:] == b"\x20"
    assert declared == header.local_data_length == (20 if is_ob else 0)

    words = struct.unpack(f"<{len(image.segment_table) // 2}H", image.segment_table)
    count, lengths, terminator = words[0], words[1:-1], words[-1]
    assert (count, terminator) == (len(lengths), 0)
    assert sum(lengths) + len(BLOCK_END) == header.mc7_length

    footer = image.footer
    assert (footer.author, footer.family, footer.name) == (bytes(8), bytes(8), bytes(8))
    assert (footer.version, footer.unknown_25, footer.unknown_28) == (0x10, 0, bytes(8))
    assert footer.checksum == (0x4DE5 if name == "cm7.bin" else 0)


def test_rebuilt_reference_block_differs_from_the_fixture_in_one_field_only() -> None:
    reference = parse_image(CM7.read_bytes())
    source = build_examples.EXAMPLES / "reference_ob1.awl"
    rebuilt = build_block(
        compile_block(parse_file(source)),
        reference.header.modified.to_datetime(),
        reference.header.interface_modified.to_datetime(),
    ).image
    assert differing_fields(rebuilt, reference) == ["footer.checksum"]
    committed = parse_image(expected_image(source))
    assert differing_fields(committed, reference) == [
        "header.modified",
        "header.interface_modified",
        "footer.checksum",
    ]


# ---------------------------------------------------------------------- as a user would run it


def run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "mc7asm", *arguments],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        cwd=REPOSITORY,
    )


def test_the_whole_chain_from_the_command_line(tmp_path: Path) -> None:
    image = tmp_path / "FC14.mc7"
    built = run(
        "build", "examples/constants.awl", "-o", str(image), "--timestamp", "2024-01-01T00:00:00"
    )
    assert (built.returncode, built.stderr) == (0, "")
    assert built.stdout.startswith(f"examples/constants.awl: FC14, 186 bytes -> {image}\n")
    assert image.read_bytes() == expected_image(build_examples.EXAMPLES / "constants.awl")

    listing = run("disasm", str(image))
    assert (listing.returncode, listing.stderr) == (0, "")
    size = parse_image(image.read_bytes()).header.mc7_length
    assert size == 96
    assert f"Coverage: {size} of {size} code bytes decoded, 0 unknown" in listing.stdout
    statements = [
        line.split(None, 1)[1].split("  ")[-1].strip()
        for line in listing.stdout.splitlines()
        if line.startswith("  0x")
    ]
    assert statements[:2] == ["L 100", "L -5"]

    # Write the listing back as source, build it again, and get the same code.
    source = tmp_path / "again.awl"
    body = "\n".join(f"      {text}" for text in statements[:-1])
    source.write_text(f"FUNCTION FC 14 : VOID\nBEGIN\nNETWORK\n{body}\nEND_FUNCTION\n")
    again = tmp_path / "again.mc7"
    rebuilt = run("build", str(source), "-o", str(again), "--timestamp", "2024-01-01T00:00:00")
    assert (rebuilt.returncode, rebuilt.stderr) == (0, "")
    assert parse_image(again.read_bytes()).payload == parse_image(image.read_bytes()).payload

    dump = run("dump", str(image))
    assert dump.returncode == 0
    assert dump.stdout.endswith("Findings\n  none\n")
