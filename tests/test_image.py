"""Unit tests of the block container model and its validation."""

from __future__ import annotations

import random
import struct
from dataclasses import replace
from datetime import datetime

import pytest

import mc7.blocks
from mc7asm import (
    BlockAttributes,
    BlockFooter,
    BlockHeader,
    BlockImage,
    BlockType,
    ImageFormatError,
    Mc7AsmError,
    S7Timestamp,
    Severity,
    parse_image,
    validate_image,
)
from tests.support import make_block

OB1 = make_block(
    mc7.blocks.BlockType.OB,
    1,
    mc7=bytes.fromhex("600d 6009 6500"),
    interface_entries=bytes.fromhex("0205 0505"),
)


def codes(image: BlockImage) -> list[str]:
    return [finding.code for finding in validate_image(image)]


def patched(image: bytes, offset: int, value: bytes) -> bytes:
    return image[:offset] + value + image[offset + len(value) :]


def test_header_fields_are_decoded_at_the_documented_offsets() -> None:
    header = parse_image(OB1).header
    assert header == BlockHeader(
        version=1,
        attributes=0x01,
        language=1,
        type_code=0x08,
        number=1,
        length=len(OB1),
        password=bytes(4),
        modified=S7Timestamp(milliseconds=60_000, days=1),
        interface_modified=S7Timestamp(milliseconds=0, days=0),
        interface_length=11,
        segment_table_length=6,
        local_data_length=20,
        mc7_length=6,
    )
    assert header.block_type is BlockType.OB
    assert header.name == "OB1"
    assert header.language_name == "STL"
    assert header.attribute_flags == BlockAttributes.LINKED
    assert not header.has_password


def test_every_header_field_sits_where_the_references_say() -> None:
    raw = bytes.fromhex(
        "7070"  # 0  signature
        "02"  # 2  block version
        "2b"  # 3  attributes
        "03"  # 4  language
        "0e"  # 5  block type
        "0123"  # 6  block number
        "00000048"  # 8  block length
        "a1b2c3d4"  # 12 password
        "0000ea600001"  # 16 last modified
        "05265bd83730"  # 22 last interface change
        "0000"  # 28 interface length
        "0000"  # 30 segment table length
        "0010"  # 32 local data length
        "0000"  # 34 MC7 length
    ) + bytes(36)
    header = parse_image(raw).header
    assert (header.version, header.attributes, header.language) == (2, 0x2B, 3)
    assert (header.block_type, header.number, header.length) == (BlockType.FB, 0x0123, 72)
    assert header.password == bytes.fromhex("a1b2c3d4")
    assert header.has_password
    assert header.modified.to_datetime() == datetime(1984, 1, 2, 0, 1, 0)
    assert header.interface_modified.to_datetime() == datetime(2022, 9, 6, 23, 59, 59, 960000)
    assert header.local_data_length == 0x10
    assert header.attribute_flags == (
        BlockAttributes.LINKED
        | BlockAttributes.STANDARD_BLOCK
        | BlockAttributes.KNOW_HOW_PROTECTED
        | BlockAttributes.NON_RETAIN
    )


def test_attribute_bits_match_the_toolbox_enum() -> None:
    assert {flag.name: flag.value for flag in BlockAttributes} == {
        "LINKED": 0x01,
        "STANDARD_BLOCK": 0x02,
        "KNOW_HOW_PROTECTED": 0x08,
        "NON_RETAIN": 0x20,
        "F_BLOCK": 0x40,
    }


def test_timestamp_encoding_is_milliseconds_then_days_since_1984() -> None:
    stamp = S7Timestamp.from_bytes(bytes.fromhex("0000ea600001"))
    assert stamp == S7Timestamp(milliseconds=60_000, days=1)
    assert stamp.to_datetime() == datetime(1984, 1, 2, 0, 1, 0)
    assert stamp.to_bytes() == bytes.fromhex("0000ea600001")
    assert S7Timestamp(0, 0).to_datetime() == datetime(1984, 1, 1)
    with pytest.raises(ImageFormatError, match="6 bytes"):
        S7Timestamp.from_bytes(b"\x00")


def test_sections_follow_the_header_in_documented_order() -> None:
    image = parse_image(OB1)
    assert image.payload == bytes.fromhex("600d 6009 6500")
    assert image.interface == bytes.fromhex("01 0000 0400 0000 0205 0505")
    assert image.segment_table == bytes.fromhex("0100 0400 0000")
    assert image.trailing_unknown == b""
    assert image.declared_layout_fits
    assert image.size == len(OB1) == image.header.length
    assert [(s.name, s.offset, len(s.data)) for s in image.sections()] == [
        ("header", 0, 36),
        ("payload", 36, 6),
        ("interface", 42, 11),
        ("segment_table", 53, 6),
        ("trailing_unknown", 59, 0),
        ("footer", 59, 36),
    ]
    assert validate_image(image) == []


def test_footer_is_the_last_36_bytes() -> None:
    footer = parse_image(OB1).footer
    assert footer == BlockFooter(
        author=b"AUTHOR  ",
        family=b"FAMILY  ",
        name=b"NAME    ",
        version=0x01,
        unknown_25=0x00,
        checksum=0xABCD,
        unknown_28=bytes(8),
    )
    assert (footer.author_text, footer.family_text, footer.name_text) == (
        "AUTHOR",
        "FAMILY",
        "NAME",
    )
    assert footer.version_text == "0.1"


def test_footer_text_drops_nul_padding_and_version_uses_nibbles() -> None:
    raw = (
        OB1[:-36]
        + b"ab\x00\x00\x00\x00\x00\x00"
        + bytes(16)
        + bytes.fromhex("10 5a 4de5")
        + b"12345678"
    )
    footer = parse_image(raw).footer
    assert (footer.author_text, footer.family_text, footer.name_text) == ("ab", "", "")
    assert footer.version_text == "1.0"
    assert (footer.unknown_25, footer.checksum, footer.unknown_28) == (0x5A, 0x4DE5, b"12345678")
    assert parse_image(raw).to_bytes() == raw


@pytest.mark.parametrize("block_type", list(mc7.blocks.BlockType))
def test_every_block_type_round_trips(block_type: mc7.blocks.BlockType) -> None:
    raw = make_block(block_type, 77, mc7=bytes(range(50)), interface_entries=bytes(range(9)))
    image = parse_image(raw)
    assert image.to_bytes() == raw
    assert image.header.block_type is BlockType[block_type.name]
    assert image.header.name == f"{block_type.value}77"
    assert validate_image(image) == []


def test_block_type_codes_agree_with_the_communication_layer() -> None:
    assert {t.name: t.value for t in BlockType} == {
        t.name: t.subblock_code for t in mc7.blocks.BlockType
    }
    assert [t.name for t in BlockType if t.is_data] == ["DB", "SDB"]


def test_unaccounted_bytes_are_kept_as_trailing_unknown() -> None:
    extra = bytes(range(100, 120))
    raw = make_block(mc7=bytes(range(10)), unaccounted=extra)
    image = parse_image(raw)
    assert image.trailing_unknown == extra
    assert image.declared_layout_fits
    assert image.to_bytes() == raw
    (finding,) = validate_image(image)
    assert (finding.severity, finding.code) == (Severity.NOTE, "trailing-unknown")
    assert "20 byte(s)" in finding.message


def test_length_field_mismatch_is_reported_not_rejected() -> None:
    raw = patched(OB1, 8, struct.pack(">I", len(OB1) + 20))
    image = parse_image(raw)
    assert image.to_bytes() == raw
    (finding,) = validate_image(image)
    assert (finding.severity, finding.code) == (Severity.WARNING, "length-field")
    assert f"says {len(OB1) + 20} bytes, the image is {len(OB1)} bytes" in finding.message


def test_bytes_appended_after_the_declared_length_stay_in_the_image() -> None:
    raw = OB1[:-36] + bytes(5) + OB1[-36:]
    image = parse_image(raw)
    assert image.trailing_unknown == bytes(5)
    assert image.to_bytes() == raw
    assert codes(image) == ["length-field", "trailing-unknown"]


@pytest.mark.parametrize(
    ("offset", "kept"),
    [(34, ("", "", "")), (28, ("payload", "", "")), (30, ("payload", "interface", ""))],
)
def test_sections_that_do_not_fit_are_left_raw(offset: int, kept: tuple[str, ...]) -> None:
    good = parse_image(OB1)
    raw = patched(OB1, offset, struct.pack(">H", 0x4000))
    image = parse_image(raw)
    expected = [getattr(good, name) if name else b"" for name in kept]
    assert [image.payload, image.interface, image.segment_table] == expected
    assert not image.declared_layout_fits
    assert image.to_bytes() == raw
    assert len(image.trailing_unknown) == len(raw) - 72 - sum(len(part) for part in expected)
    (finding,) = validate_image(image)
    assert (finding.severity, finding.code) == (Severity.ERROR, "sections-overrun")


def test_unknown_codes_are_preserved_and_reported() -> None:
    raw = patched(OB1, 3, bytes((0x95, 0x07, 0x55)))
    image = parse_image(raw)
    header = image.header
    assert image.to_bytes() == raw
    assert header.block_type is None
    assert header.name == "type 0x55 #1"
    assert header.language_name == "7"
    assert header.attributes == 0x95
    assert BlockAttributes.LINKED in header.attribute_flags
    assert int(header.attribute_flags) == 0x95
    assert codes(image) == ["unknown-block-type", "unknown-language", "unknown-attribute-bits"]
    assert "0x94" in validate_image(image)[2].message


@pytest.mark.parametrize("size", [0, 1, 36, 71])
def test_too_short_data_is_rejected(size: int) -> None:
    with pytest.raises(ImageFormatError, match="at least 72 bytes") as caught:
        parse_image((b"pp" + bytes(100))[:size])
    assert isinstance(caught.value, Mc7AsmError)
    assert isinstance(caught.value, ValueError)


def test_smallest_possible_image() -> None:
    raw = patched(make_block()[:36], 28, bytes(8)) + bytes(36)
    image = parse_image(raw)
    assert (image.payload, image.interface, image.segment_table, image.trailing_unknown) == (
        b"",
        b"",
        b"",
        b"",
    )
    assert image.to_bytes() == raw


def test_wrong_signature_is_rejected() -> None:
    with pytest.raises(ImageFormatError, match=r"signature is 50 4b, expected 70 70"):
        parse_image(b"PK" + OB1[2:])


def test_out_of_range_fields_cannot_be_serialized() -> None:
    image = parse_image(OB1)
    with pytest.raises(ImageFormatError, match="header field out of range"):
        replace(image, header=replace(image.header, number=70_000)).to_bytes()
    with pytest.raises(ImageFormatError, match="password must be exactly 4 bytes"):
        replace(image, header=replace(image.header, password=b"abc")).to_bytes()
    with pytest.raises(ImageFormatError, match="author must be exactly 8 bytes"):
        replace(image, footer=replace(image.footer, author=b"too long!")).to_bytes()


def test_any_input_with_the_signature_round_trips() -> None:
    generator = random.Random(20261112)
    for _ in range(500):
        raw = b"pp" + generator.randbytes(generator.randint(70, 400))
        assert parse_image(raw).to_bytes() == raw
