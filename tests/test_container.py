"""The container builder and the strict validation of generated images."""

from __future__ import annotations

import struct
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import pytest

import mc7.blocks
from mc7asm import (
    BlockAttributes,
    BlockType,
    BuiltBlock,
    ContainerError,
    ImageFormatError,
    Mnemonics,
    NotYetSupportedError,
    S7Timestamp,
    Severity,
    build_block,
    cli,
    compile_block,
    disassemble,
    parse_file,
    parse_image,
    parse_source,
    validate_generated_image,
    validate_image,
)
from tests.support import make_block

REPOSITORY = Path(__file__).parent.parent
EXAMPLES = REPOSITORY / "examples"
FIXTURES = REPOSITORY / "tests" / "fixtures"
CM7 = FIXTURES / "blocks" / "reference" / "cm7.bin"
STAMP = datetime(2024, 5, 17, 8, 30, 0)
BLOCK_END = bytes.fromhex("6500")
BUILDABLE = sorted(path.stem for path in EXAMPLES.glob("*.awl") if path.stem != "nesting")


def build(example: str, stamp: datetime = STAMP) -> BuiltBlock:
    mnemonics = Mnemonics.DE if example.endswith("_de") else Mnemonics.EN
    return build_block(compile_block(parse_file(EXAMPLES / f"{example}.awl", mnemonics)), stamp)


def build_source(statements: str, header: str = "FUNCTION FC 1 : VOID") -> BuiltBlock:
    end = "END_" + header.split()[0]
    source = f"{header}\nBEGIN\nNETWORK\n{statements}\n{end}\n"
    return build_block(compile_block(parse_source(source)), STAMP)


# ---------------------------------------------------------------------- build and validate


def test_every_example_is_either_buildable_or_refused_by_the_code_generator() -> None:
    assert len(BUILDABLE) == 13
    assert (EXAMPLES / "nesting.awl").is_file()
    with pytest.raises(NotYetSupportedError):
        build("nesting")


@pytest.mark.parametrize("example", BUILDABLE)
def test_built_image_validates(example: str) -> None:
    built = build(example)
    data = built.image.to_bytes()
    image = parse_image(data)
    assert validate_generated_image(image) == []
    assert validate_image(image) == []
    header = image.header
    assert header.length == len(data) == image.size
    assert len(data) == 36 + header.mc7_length + header.interface_length + (
        header.segment_table_length + 36
    )
    assert image.trailing_unknown == b""
    assert image.payload.endswith(BLOCK_END)
    assert built.block_end_appended
    listing = disassemble(image)
    assert listing.unknown_bytes == 0
    assert listing.findings == ()
    # The communication layer applies its own check before a download; the image passes it.
    assert mc7.blocks.parse_block(data).name == header.name


@pytest.mark.parametrize("example", BUILDABLE)
def test_build_parse_rebuild_is_byte_identical(example: str) -> None:
    built = build(example)
    data = built.image.to_bytes()
    reparsed = parse_image(data)
    assert reparsed == built.image
    assert reparsed.to_bytes() == data
    assert build(example).image.to_bytes() == data
    later = build(example, datetime(2024, 5, 18, 8, 30, 0)).image.to_bytes()
    differing = [index for index, (a, b) in enumerate(zip(data, later, strict=True)) if a != b]
    assert differing
    assert set(differing) <= set(range(16, 28))


def test_german_and_international_source_build_the_same_image() -> None:
    assert build("blink_de").image == build("blink").image


# ---------------------------------------------------------------------- the reference block


def test_building_the_reference_program_reproduces_the_reference_block() -> None:
    reference = CM7.read_bytes()
    original = parse_image(reference)
    compiled = compile_block(parse_file(EXAMPLES / "reference_ob1.awl"))
    built = build_block(
        compiled,
        original.header.modified.to_datetime(),
        original.header.interface_modified.to_datetime(),
    )
    data = built.image.to_bytes()
    checksum_offset = len(reference) - 36 + 26
    without_checksum = bytearray(reference)
    without_checksum[checksum_offset : checksum_offset + 2] = b"\x00\x00"
    assert data == bytes(without_checksum)
    differing = [index for index, (a, b) in enumerate(zip(data, reference, strict=True)) if a != b]
    assert differing == [checksum_offset, checksum_offset + 1]
    assert built.notes == ()
    assert built.block_end_appended
    assert original.footer.checksum == 0x4DE5
    assert built.image.footer.checksum == 0


def test_reference_block_sections_decode_as_documented() -> None:
    image = parse_image(CM7.read_bytes())
    marker, number, declarations, start_values = struct.unpack_from("<BHHH", image.interface)
    assert (marker, number, declarations, start_values) == (0x01, 0, 20, 0)
    entries = image.interface[7 : 7 + declarations]
    pairs = [(entries[index], entries[index + 1]) for index in range(0, declarations, 2)]
    assert pairs == [(0x02, 0x05)] * 6 + [(0x05, 0x05)] * 3 + [(0x0E, 0x05)]
    assert image.interface[7 + declarations :] == b"\x20"
    assert 6 * 1 + 3 * 2 + 8 == image.header.local_data_length == 20
    assert struct.unpack("<3H", image.segment_table) == (1, 34, 0)
    assert image.header.mc7_length - len(BLOCK_END) == 34


# ---------------------------------------------------------------------- block closing


def test_counter_code_is_the_codegen_output_plus_the_appended_block_end() -> None:
    compiled = compile_block(parse_file(EXAMPLES / "counter.awl"))
    built = build_block(compiled, STAMP)
    image = built.image
    assert image.payload == compiled.body + BLOCK_END
    assert not compiled.body.endswith(BLOCK_END)
    assert image.header.mc7_length == compiled.size + 2 == 36
    assert image.payload == parse_image(CM7.read_bytes()).payload
    assert built.block_end_appended
    assert [network.size for network in compiled.networks] == [16, 18]
    assert image.segment_table == bytes.fromhex("0200 1000 1200 0000")
    assert image.interface == bytes.fromhex("01 0000 0000 0000 20")
    assert (image.header.interface_length, image.header.segment_table_length) == (8, 8)
    assert image.header.local_data_length == 0
    assert image.header.length == 36 + 36 + 8 + 8 + 36 == 124
    assert [note.code for note in built.notes] == [
        "generalized-interface",
        "generalized-segment-table",
    ]
    assert {note.severity for note in built.notes} == {Severity.NOTE}


def test_block_end_from_the_source_is_not_duplicated() -> None:
    built = build_source("      A I 0.0\n      = Q 0.0\n      BE")
    assert not built.block_end_appended
    assert built.image.payload == bytes.fromhex("c000 d880 6500")
    assert built.image.segment_table == bytes.fromhex("0100 0400 0000")
    assert validate_generated_image(built.image) == []


def test_a_constant_ending_in_the_same_bytes_is_not_mistaken_for_block_end() -> None:
    built = build_source("      L W#16#6500")
    assert built.block_end_appended
    assert built.image.payload == bytes.fromhex("30076500 6500")
    assert built.image.segment_table == bytes.fromhex("0100 0400 0000")


def test_empty_network_still_gets_a_block_end() -> None:
    built = build_source("")
    assert built.image.payload == BLOCK_END
    assert built.image.segment_table == bytes.fromhex("0100 0000 0000")
    assert validate_generated_image(built.image) == []


# ---------------------------------------------------------------------- header, interface, footer


@pytest.mark.parametrize(
    ("header", "block_type", "number", "interface", "local_data", "note"),
    [
        ("ORGANIZATION_BLOCK OB 1", BlockType.OB, 1, "01 0000 1400 0000", 20, None),
        ("ORGANIZATION_BLOCK OB 35", BlockType.OB, 35, "01 0000 1400 0000", 20, "OB35 gets"),
        ("FUNCTION FC 7", BlockType.FC, 7, "01 0000 0000 0000 20", 0, "follows a real FC1"),
        ("FUNCTION_BLOCK FB 300", BlockType.FB, 300, "01 0000 0000 0000 20", 0, "no real FB"),
    ],
)
def test_header_interface_and_notes_per_block_type(
    header: str,
    block_type: BlockType,
    number: int,
    interface: str,
    local_data: int,
    note: str | None,
) -> None:
    built = build_source("      A I 0.0", header)
    image = built.image
    head = image.header
    assert (head.block_type, head.number) == (block_type, number)
    assert (head.version, head.language, head.language_name) == (1, 1, "STL")
    assert head.attribute_flags == BlockAttributes.LINKED
    assert head.password == bytes(4)
    assert head.modified == head.interface_modified == S7Timestamp.from_datetime(STAMP)
    assert head.modified.to_datetime() == STAMP
    assert head.local_data_length == local_data
    assert image.interface.startswith(bytes.fromhex(interface))
    assert image.interface.endswith(b"\x20")
    assert len(image.interface) == (28 if block_type is BlockType.OB else 8)
    footer = image.footer
    assert (footer.author, footer.family, footer.name) == (bytes(8), bytes(8), bytes(8))
    assert (footer.version, footer.unknown_25, footer.checksum) == (0x10, 0, 0)
    assert footer.unknown_28 == bytes(8)
    codes = [finding.code for finding in built.notes]
    assert codes == ([] if note is None else ["generalized-interface"])
    if note:
        assert note in built.notes[0].message
    assert validate_generated_image(image) == []


def test_timestamp_encoding() -> None:
    assert S7Timestamp.from_datetime(datetime(1984, 1, 2, 0, 1, 0)) == S7Timestamp(60_000, 1)
    assert S7Timestamp.from_datetime(datetime(1984, 1, 1)).to_bytes() == bytes(6)
    precise = datetime(2022, 9, 6, 15, 19, 45, 960_999)
    stamp = S7Timestamp.from_datetime(precise)
    assert stamp == S7Timestamp(55_185_960, 14_128)
    assert stamp.to_datetime() == datetime(2022, 9, 6, 15, 19, 45, 960_000)
    for moment in (datetime(1983, 12, 31), datetime(2200, 1, 1)):
        with pytest.raises(ImageFormatError, match="outside the range of a block timestamp"):
            S7Timestamp.from_datetime(moment)


def test_blocks_that_cannot_be_wrapped() -> None:
    empty = compile_block(parse_source("FUNCTION FC 1 : VOID\nBEGIN\nEND_FUNCTION"))
    with pytest.raises(ContainerError, match="FC1 has no network"):
        build_block(empty, STAMP)
    huge = build_source  # 11,000 six-byte loads are 66,000 bytes of code
    with pytest.raises(ContainerError, match="the code is 66002 bytes, the limit is 65535"):
        huge("\n".join(["      L L#1"] * 11_000))
    with pytest.raises(ImageFormatError, match="outside the range"):
        build_block(compile_block(parse_file(EXAMPLES / "counter.awl")), datetime(1970, 1, 1))


# ---------------------------------------------------------------------- corrupted images


def patch(offset: int, value: bytes) -> Callable[[bytes], bytes]:
    return lambda data: data[:offset] + value + data[offset + len(value) :]


GOOD = build("counter").image.to_bytes()
CODE_END = 36 + 36


@pytest.mark.parametrize(
    ("corrupt", "expected"),
    [
        (patch(8, struct.pack(">I", len(GOOD) + 1)), {"length-field"}),
        (patch(8, struct.pack(">I", 0)), {"length-field"}),
        (patch(34, struct.pack(">H", 38)), {"sections-overrun", "missing-block-end"}),
        (patch(34, struct.pack(">H", 34)), {"trailing-unknown", "missing-block-end"}),
        (patch(28, struct.pack(">H", 7)), {"trailing-unknown"}),
        (patch(28, struct.pack(">H", 4000)), {"sections-overrun"}),
        (patch(30, struct.pack(">H", 10)), {"sections-overrun"}),
        (patch(30, struct.pack(">H", 0)), {"trailing-unknown"}),
        (patch(5, b"\x0a"), {"not-a-code-block"}),
        (patch(5, b"\x0d"), {"not-a-code-block"}),
        (patch(5, b"\x55"), {"unknown-block-type"}),
        (patch(4, b"\x07"), {"unknown-language"}),
        (patch(3, b"\x81"), {"unknown-attribute-bits"}),
        (patch(CODE_END - 2, b"\x00\x00"), {"missing-block-end"}),
        (patch(CODE_END - 1, b"\x01"), {"missing-block-end"}),
        (lambda data: data[:-1], {"length-field", "sections-overrun"}),
        (lambda data: data + b"\x00", {"length-field", "trailing-unknown"}),
        (lambda data: data[:CODE_END] + b"\x00\x00" + data[CODE_END:], {"length-field"}),
    ],
)
def test_the_validator_catches_a_corrupted_image(
    corrupt: Callable[[bytes], bytes], expected: set[str]
) -> None:
    assert validate_generated_image(parse_image(GOOD)) == []
    findings = validate_generated_image(parse_image(corrupt(GOOD)))
    assert expected <= {finding.code for finding in findings}
    assert {finding.severity for finding in findings} == {Severity.ERROR}


@pytest.mark.parametrize(
    "corrupt", [patch(0, b"PK"), patch(1, b"\x00"), lambda data: data[:71], lambda data: b""]
)
def test_an_image_that_is_not_a_block_cannot_even_be_parsed(
    corrupt: Callable[[bytes], bytes],
) -> None:
    with pytest.raises(ImageFormatError):
        parse_image(corrupt(GOOD))


def test_the_checksum_is_never_verified() -> None:
    checksum_offset = len(GOOD) - 36 + 26
    for value in (b"\x00\x00", b"\xff\xff", b"\x4d\xe5"):
        image = parse_image(patch(checksum_offset, value)(GOOD))
        assert image.footer.checksum == int.from_bytes(value, "big")
        assert validate_generated_image(image) == []
        assert image.to_bytes()[checksum_offset : checksum_offset + 2] == value


def test_real_blocks_keep_their_tolerant_validation() -> None:
    reference = parse_image(CM7.read_bytes())
    assert validate_image(reference) == []
    assert validate_generated_image(reference) == []
    real_with_extra_bytes = parse_image(
        make_block(mc7=bytes.fromhex("c0006500"), unaccounted=b"\x01")
    )
    (tolerant,) = validate_image(real_with_extra_bytes)
    assert (tolerant.severity, tolerant.code) == (Severity.NOTE, "trailing-unknown")
    (strict,) = validate_generated_image(real_with_extra_bytes)
    assert (strict.severity, strict.code) == (Severity.ERROR, "trailing-unknown")
    data_block = parse_image(make_block(mc7.blocks.BlockType.DB, 1))
    assert validate_image(data_block) == []
    assert {finding.code for finding in validate_generated_image(data_block)} == {
        "not-a-code-block"
    }


# ---------------------------------------------------------------------- command line


def test_build_on_the_command_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(REPOSITORY)
    output = tmp_path / "FC1.mc7"
    argv = [
        "build",
        "examples/counter.awl",
        "-o",
        str(output),
        "--timestamp",
        "2024-05-17T08:30:00",
    ]
    assert cli.main(argv) == 0
    assert output.read_bytes() == GOOD
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == (
        f"examples/counter.awl: FC1, 124 bytes -> {output}\n"
        "  code 36 bytes (BE appended), interface 8, segment table 8, local data 0\n"
        "  note: the interface sub-header of an FC follows a real FC1; an FC without "
        "declarations and its local data length of 0 are generalized [generalized-interface]\n"
        "  note: the segment table for 2 networks has the count and the lengths that real "
        "multi-network blocks show; whether an STL block needs more than the zero word after "
        "them is not known [generalized-segment-table]\n"
    )
    assert cli.main(["dump", str(output)]) == 0
    assert capsys.readouterr().out.endswith("Findings\n  none\n")
    assert cli.main(["disasm", str(output)]) == 0
    listing = capsys.readouterr().out
    assert "  0x0046  65 00        BE\n" in listing
    assert "Coverage: 36 of 36 code bytes decoded, 0 unknown" in listing


def test_build_defaults_to_the_block_name_next_to_the_source(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in ("reference_ob1.awl", "blink_de.awl"):
        (tmp_path / name).write_text((EXAMPLES / name).read_text())
    assert cli.main(["build", str(tmp_path / "reference_ob1.awl")]) == 0
    out = capsys.readouterr().out
    assert out.splitlines() == [
        f"{tmp_path / 'reference_ob1.awl'}: OB1, 142 bytes -> {tmp_path / 'OB1.mc7'}",
        "  code 36 bytes (BE appended), interface 28, segment table 6, local data 20",
    ]
    built = parse_image((tmp_path / "OB1.mc7").read_bytes())
    age = datetime.now() - built.header.modified.to_datetime()
    assert 0 <= age.total_seconds() < 60
    assert cli.main(["build", str(tmp_path / "blink_de.awl"), "--mnemonics", "de"]) == 0
    assert parse_image((tmp_path / "OB1.mc7").read_bytes()).header.mc7_length == 60


def test_build_writes_nothing_it_cannot_validate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(REPOSITORY)
    output = tmp_path / "FC1.mc7"

    def broken(*_arguments: object) -> BuiltBlock:
        good = build("counter")
        image = parse_image(patch(CODE_END - 2, b"\x00\x00")(good.image.to_bytes()))
        return BuiltBlock(image, True, ())

    monkeypatch.setattr(cli, "build_block", broken)
    assert cli.main(["build", "examples/counter.awl", "-o", str(output)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "  error: the code section does not end with BE (65 00): its last bytes are 00 00 "
        "[missing-block-end]\n"
        "error: examples/counter.awl: the built image failed validation, nothing was written\n"
    )
    assert not output.exists()


def test_build_failures_leave_no_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(REPOSITORY)
    output = tmp_path / "out.mc7"
    assert cli.main(["build", "examples/nesting.awl", "-o", str(output)]) == 1
    assert "A( is not yet supported" in capsys.readouterr().err
    bad = "tests/expected_errors/bit_number_out_of_range.awl"
    assert cli.main(["build", bad, "-o", str(output)]) == 1
    assert "bit number 8 is out of range" in capsys.readouterr().err
    assert (
        cli.main(["build", "examples/counter.awl", "-o", str(output), "--timestamp", "1970-01-01"])
        == 1
    )
    assert "outside the range of a block timestamp" in capsys.readouterr().err
    assert not output.exists()
    with pytest.raises(SystemExit) as caught:
        cli.main(["build", "examples/counter.awl", "--timestamp", "yesterday"])
    assert caught.value.code == 2
