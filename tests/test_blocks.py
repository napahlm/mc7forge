from __future__ import annotations

from pathlib import Path

import pytest

from mc7.blocks import (
    BlockType,
    block_filename,
    load_block,
    parse_block,
    parse_block_spec,
    save_block,
)
from mc7.errors import BlockFormatError
from tests.support import make_block


@pytest.mark.parametrize("block_type", list(BlockType))
def test_parse_block_decodes_every_block_type(block_type: BlockType) -> None:
    image = make_block(block_type, 42, mc7=b"\x01\x02\x03\x04", language=3)
    header = parse_block(image)
    assert header.block_type is block_type
    assert header.number == 42
    assert header.name == f"{block_type.value}42"
    assert header.language == 3
    assert header.load_size == len(image)
    assert header.mc7_size == 4


def test_type_codes_match_the_s7_protocol() -> None:
    assert {t.name: t.type_code for t in BlockType} == {
        "OB": 0x38,
        "DB": 0x41,
        "SDB": 0x42,
        "FC": 0x43,
        "SFC": 0x44,
        "FB": 0x45,
        "SFB": 0x46,
    }
    assert {t.name: t.subblock_code for t in BlockType} == {
        "OB": 0x08,
        "DB": 0x0A,
        "SDB": 0x0B,
        "FC": 0x0C,
        "SFC": 0x0D,
        "FB": 0x0E,
        "SFB": 0x0F,
    }


def test_parse_block_rejects_short_data() -> None:
    with pytest.raises(BlockFormatError, match="shorter than the 36-byte header"):
        parse_block(b"pp\x01")


def test_parse_block_rejects_missing_magic() -> None:
    image = bytearray(make_block())
    image[0:2] = b"\x00\x00"
    with pytest.raises(BlockFormatError, match="instead of 7070"):
        parse_block(bytes(image))


def test_parse_block_rejects_unknown_type() -> None:
    image = bytearray(make_block())
    image[5] = 0x55
    with pytest.raises(BlockFormatError, match="unknown block type code 0x55"):
        parse_block(bytes(image))


def test_parse_block_rejects_truncated_and_padded_images() -> None:
    image = make_block()
    with pytest.raises(BlockFormatError, match="truncated or has trailing data"):
        parse_block(image[:-1])
    with pytest.raises(BlockFormatError, match="truncated or has trailing data"):
        parse_block(image + b"\x00")


def test_parse_block_rejects_mc7_length_without_footer() -> None:
    image = bytearray(make_block(mc7=b"\x00\x00"))
    image[34:36] = (len(image) - 36).to_bytes(2, "big")
    with pytest.raises(BlockFormatError, match="no room for the block footer"):
        parse_block(bytes(image))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("OB1", (BlockType.OB, 1)),
        ("fc105", (BlockType.FC, 105)),
        (" DB10 ", (BlockType.DB, 10)),
        ("FB3", (BlockType.FB, 3)),
        ("SDB0", (BlockType.SDB, 0)),
        ("SFC20", (BlockType.SFC, 20)),
        ("SFB4", (BlockType.SFB, 4)),
    ],
)
def test_parse_block_spec(text: str, expected: tuple[BlockType, int]) -> None:
    assert parse_block_spec(text) == expected


@pytest.mark.parametrize("text", ["", "OB", "1", "XB1", "OB-1", "OB1.mc7", "OB 1"])
def test_parse_block_spec_rejects_malformed_names(text: str) -> None:
    with pytest.raises(BlockFormatError, match="cannot parse block name"):
        parse_block_spec(text)


def test_parse_block_spec_rejects_out_of_range_number() -> None:
    with pytest.raises(BlockFormatError, match="out of range"):
        parse_block_spec("DB65536")


def test_block_filename() -> None:
    assert block_filename(BlockType.OB, 1) == "OB1.mc7"


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    image = make_block(BlockType.DB, 7)
    path = tmp_path / "nested" / "DB7.mc7"
    assert save_block(path, image).name == "DB7"
    data, header = load_block(path)
    assert data == image
    assert header.name == "DB7"


def test_save_refuses_to_overwrite_unless_asked(tmp_path: Path) -> None:
    path = tmp_path / "FC1.mc7"
    save_block(path, make_block(mc7=b"\x01\x01"))
    with pytest.raises(FileExistsError):
        save_block(path, make_block(mc7=b"\x02\x02"))
    save_block(path, make_block(mc7=b"\x02\x02"), overwrite=True)
    assert load_block(path)[0] == make_block(mc7=b"\x02\x02")


def test_save_rejects_invalid_images_without_touching_the_disk(tmp_path: Path) -> None:
    path = tmp_path / "bad.mc7"
    with pytest.raises(BlockFormatError):
        save_block(path, b"not a block")
    assert not path.exists()


def test_load_error_names_the_file(tmp_path: Path) -> None:
    path = tmp_path / "broken.mc7"
    path.write_bytes(make_block()[:-5])
    with pytest.raises(BlockFormatError, match=r"broken\.mc7: header declares"):
        load_block(path)
