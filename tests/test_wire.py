"""End-to-end tests over real TCP against the fake PLC in ``tests/support.py``.

They cover what python-snap7's emulator cannot: block upload and download for
every block type, the round-trip integrity check, and the exact bytes of a
single-bit write.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from mc7 import (
    BlockTransferError,
    BlockType,
    BlockVerifyError,
    PlcClient,
    PlcRequestError,
    cli,
    load_block,
)
from tests.support import FakePlc, make_block

BIG_FC = make_block(BlockType.FC, 105, mc7=bytes(i % 251 for i in range(700)))


@pytest.fixture
def fake() -> Iterator[FakePlc]:
    with FakePlc() as plc:
        yield plc
    assert plc.failures == []


@pytest.fixture
def plc(fake: FakePlc) -> Iterator[PlcClient]:
    with PlcClient("127.0.0.1", port=fake.port) as client:
        yield client


def test_pdu_length_is_negotiated_with_the_plc(plc: PlcClient) -> None:
    assert plc.pdu_length == 240


def test_upload_reassembles_a_block_spanning_several_pdus(fake: FakePlc, plc: PlcClient) -> None:
    fake.add(BlockType.FC, 105, BIG_FC)
    assert len(BIG_FC) > 3 * 240
    assert plc.upload_block(BlockType.FC, 105) == BIG_FC


def test_upload_of_a_missing_block(plc: PlcClient) -> None:
    with pytest.raises(PlcRequestError, match="failed to upload OB1") as caught:
        plc.upload_block(BlockType.OB, 1)
    assert caught.value.code == 0xD209
    assert plc.connected


@pytest.mark.parametrize("block_type", [BlockType.OB, BlockType.FC, BlockType.FB, BlockType.DB])
def test_download_inserts_every_block_type(
    fake: FakePlc, plc: PlcClient, block_type: BlockType
) -> None:
    image = make_block(block_type, 12, mc7=bytes(range(200)) * 3)
    header = plc.download_block(image)
    assert header.name == f"{block_type.value}12"
    assert fake.inserted == [(block_type.type_code, 12)]
    assert fake.get(block_type, 12) == image
    assert plc.verify_block(image) == header


def test_round_trip_leaves_the_block_unchanged(fake: FakePlc, plc: PlcClient) -> None:
    fake.add(BlockType.FC, 105, BIG_FC)
    uploaded = plc.upload_block(BlockType.FC, 105)
    plc.download_block(uploaded)
    plc.verify_block(uploaded)
    assert fake.get(BlockType.FC, 105) == BIG_FC
    assert plc.upload_block(BlockType.FC, 105) == BIG_FC


def test_download_replaces_an_existing_block(fake: FakePlc, plc: PlcClient) -> None:
    old = make_block(BlockType.DB, 3, mc7=b"\x00" * 8)
    new = make_block(BlockType.DB, 3, mc7=b"\x11" * 8)
    fake.add(BlockType.DB, 3, old)
    with pytest.raises(BlockVerifyError, match="differs from the reference at byte offset 36"):
        plc.verify_block(new)
    plc.download_block(new)
    plc.verify_block(new)


def test_protected_cpu_refuses_the_download_and_keeps_the_session(fake: FakePlc) -> None:
    fake.add(BlockType.FC, 105, BIG_FC)
    fake.download_error = 0xD241
    with PlcClient("127.0.0.1", port=fake.port) as plc:
        with pytest.raises(BlockTransferError, match="protection level") as caught:
            plc.download_block(BIG_FC)
        assert caught.value.code == 0xD241
        assert plc.upload_block(BlockType.FC, 105) == BIG_FC
    assert fake.inserted == []


def test_refused_insert_keeps_the_previous_block_active(fake: FakePlc) -> None:
    old = make_block(BlockType.FC, 7, mc7=b"\x01" * 4)
    new = make_block(BlockType.FC, 7, mc7=b"\x02" * 4)
    fake.add(BlockType.FC, 7, old)
    fake.insert_error = 0xD240
    with PlcClient("127.0.0.1", port=fake.port) as plc:
        with pytest.raises(BlockTransferError, match="NOT activated") as caught:
            plc.download_block(new)
        assert caught.value.code == 0xD240
        assert plc.upload_block(BlockType.FC, 7) == old


def test_single_bit_write_on_the_wire(fake: FakePlc, plc: PlcClient) -> None:
    plc.write("M10.3", True)
    plc.write("DB2.DBX1.7", False)
    assert [pdu.hex(" ") for pdu in fake.writes] == [
        # write var, 1 item, S7ANY: transport BIT, count 1, no DB, area M (0x83),
        # bit address 10*8+3 = 0x53; data: transport BIT (0x03), 1 bit, value 1
        "05 01 12 0a 10 01 00 01 00 00 83 00 00 53 00 03 00 01 01",
        # DB2 (0x84), bit address 1*8+7 = 0x0f, value 0
        "05 01 12 0a 10 01 00 01 00 02 84 00 00 0f 00 03 00 01 00",
    ]


def test_cli_upload_then_download_round_trip(
    fake: FakePlc, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.add(BlockType.FC, 105, BIG_FC)
    fake.add(BlockType.OB, 1, make_block(BlockType.OB, 1))
    target = ["--host", "127.0.0.1", "--port", str(fake.port)]

    assert cli.main(["upload", "FC105", "OB1", "-o", str(tmp_path), *target]) == 0
    path = tmp_path / "FC105.mc7"
    assert load_block(path)[0] == BIG_FC
    assert capsys.readouterr().out == (
        f"FC105 -> {path} ({len(BIG_FC)} bytes)\nOB1 -> {tmp_path / 'OB1.mc7'} (87 bytes)\n"
    )

    assert cli.main(["download", str(path), "--yes", *target]) == 0
    assert capsys.readouterr().out == (
        f"FC105 downloaded ({len(BIG_FC)} bytes)\n"
        f"FC105 verified: the block in the PLC is identical to {path}\n"
    )
    assert fake.inserted == [(BlockType.FC.type_code, 105)]

    fake.download_error = 0xD241
    assert cli.main(["download", str(path), "--yes", *target]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("error: PLC refused 'request download' for FC105: ")
    assert "0xD241" in captured.err
