"""Integration tests against a real S7-300. Skipped unless ``--plc-host`` is given.

Read-only tests run with ``--plc-host`` alone. Tests that modify the PLC need
``--plc-allow-writes`` plus the option naming what they may touch:

* ``--plc-marker-byte N``: four bit-memory bytes MBn..MBn+3 that no program uses.
  They are restored afterwards.
* ``--plc-block DB100``: a block that may be uploaded and downloaded unchanged.

Nothing here changes the operating state of the CPU.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from mc7 import Area, BlockType, CpuState, DataType, PlcClient, parse_block, parse_block_spec

pytestmark = pytest.mark.integration


@pytest.fixture
def plc(request: pytest.FixtureRequest) -> Iterator[PlcClient]:
    config = request.config
    client = PlcClient(
        config.getoption("--plc-host"),
        rack=config.getoption("--plc-rack"),
        slot=config.getoption("--plc-slot"),
        port=config.getoption("--plc-port"),
    )
    with client:
        yield client


def test_identity_and_state(plc: PlcClient) -> None:
    info = plc.cpu_info()
    assert info.order_number.startswith("6ES7")
    assert info.module_type
    assert plc.cpu_state() in (CpuState.RUN, CpuState.STOP)
    assert plc.pdu_length >= 240


def test_read_process_image(plc: PlcClient) -> None:
    assert isinstance(plc.read("IB0"), int)
    assert isinstance(plc.read("Q0.0"), bool)
    assert isinstance(plc.read("MW0", DataType.INT), int)
    assert len(plc.read_bytes(Area.MARKER, 0, 16)) == 16


def test_upload_ob1(plc: PlcClient) -> None:
    assert 1 in plc.list_blocks(BlockType.OB)
    image = plc.upload_block(BlockType.OB, 1)
    header = parse_block(image)
    assert (header.block_type, header.number) == (BlockType.OB, 1)


@pytest.mark.plc_write
def test_marker_round_trip(plc: PlcClient, request: pytest.FixtureRequest) -> None:
    offset = request.config.getoption("--plc-marker-byte")
    if offset is None:
        pytest.skip("needs --plc-marker-byte")
    original = plc.read_bytes(Area.MARKER, offset, 4)
    try:
        plc.write(f"MD{offset}", -123456, DataType.DINT)
        assert plc.read(f"MD{offset}", DataType.DINT) == -123456
        plc.write(f"MD{offset}", 1.5, DataType.REAL)
        assert plc.read(f"MD{offset}", DataType.REAL) == 1.5

        plc.write(f"MB{offset}", 0b1010_0101)
        plc.write(f"M{offset}.1", True)
        plc.write(f"M{offset}.0", False)
        assert plc.read(f"MB{offset}") == 0b1010_0110
        assert plc.read(f"M{offset}.1") is True
        assert plc.read(f"M{offset}.0") is False
    finally:
        plc.write_bytes(Area.MARKER, offset, original)
    assert plc.read_bytes(Area.MARKER, offset, 4) == original


@pytest.mark.plc_write
def test_block_round_trip(plc: PlcClient, request: pytest.FixtureRequest) -> None:
    spec = request.config.getoption("--plc-block")
    if spec is None:
        pytest.skip("needs --plc-block")
    block_type, number = parse_block_spec(spec)
    image = plc.upload_block(block_type, number)
    plc.download_block(image)
    plc.verify_block(image)
