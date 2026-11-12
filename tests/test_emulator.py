"""End-to-end tests over real TCP against python-snap7's built-in S7 server.

These exercise the whole stack (CLI, client, python-snap7, ISO-on-TCP) without
hardware. The emulator does not model single-bit writes or block images, so
those are covered in ``test_wire.py`` instead.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from snap7.server import Server
from snap7.type import SrvArea

from mc7 import (
    Area,
    BlockType,
    CpuState,
    DataType,
    EncodingError,
    PlcClient,
    PlcConnectionError,
    PlcRequestError,
    cli,
)
from tests.support import free_port


@dataclass
class Emulator:
    port: int
    inputs: bytearray
    outputs: bytearray
    markers: bytearray
    db1: bytearray
    db2: bytearray


@pytest.fixture
def emulator() -> Iterator[Emulator]:
    server = Server(log=False)
    emu = Emulator(
        port=free_port(),
        inputs=bytearray(16),
        outputs=bytearray(16),
        markers=bytearray(64),
        db1=bytearray(128),
        db2=bytearray(2048),
    )
    server.register_area(SrvArea.PE, 0, emu.inputs)
    server.register_area(SrvArea.PA, 0, emu.outputs)
    server.register_area(SrvArea.MK, 0, emu.markers)
    server.register_area(SrvArea.DB, 1, emu.db1)
    server.register_area(SrvArea.DB, 2, emu.db2)
    server.start(tcp_port=emu.port)
    try:
        yield emu
    finally:
        server.stop()


@pytest.fixture
def plc(emulator: Emulator) -> Iterator[PlcClient]:
    with PlcClient("127.0.0.1", port=emulator.port) as client:
        yield client


def mc7(emulator: Emulator, *argv: str) -> int:
    return cli.main([*argv, "--host", "127.0.0.1", "--port", str(emulator.port)])


def test_session_is_negotiated(plc: PlcClient) -> None:
    assert plc.connected
    assert plc.pdu_length >= 240


def test_inputs_are_read_from_the_process_image(plc: PlcClient, emulator: Emulator) -> None:
    emulator.inputs[0] = 0b1000_0101
    emulator.inputs[2:4] = b"\x12\x34"
    assert [plc.read(f"I0.{bit}") for bit in range(8)] == [
        True,
        False,
        True,
        False,
        False,
        False,
        False,
        True,
    ]
    assert plc.read("IB0") == 0x85
    assert plc.read("IW2") == 0x1234
    assert plc.read("EW2") == 0x1234


def test_outputs_and_markers_round_trip(plc: PlcClient, emulator: Emulator) -> None:
    plc.write("QB1", 0xA5)
    plc.write("QW2", 0xBEEF)
    plc.write("MW10", -1234, DataType.INT)
    plc.write("MD20", 3.25, DataType.REAL)
    plc.write("MD24", -70000, DataType.DINT)
    assert bytes(emulator.outputs[1:4]) == b"\xa5\xbe\xef"
    assert bytes(emulator.markers[10:12]) == b"\xfb\x2e"
    assert plc.read("QB1") == 0xA5
    assert plc.read("Q1.0") is True
    assert plc.read("Q1.1") is False
    assert plc.read("MW10", DataType.INT) == -1234
    assert plc.read("MW10") == 0xFB2E
    assert plc.read("MD20", DataType.REAL) == 3.25
    assert plc.read("MD24", DataType.DINT) == -70000


def test_db_typed_helpers_round_trip(plc: PlcClient, emulator: Emulator) -> None:
    plc.db_write_word(1, 0, 0xCAFE)
    plc.db_write_int(1, 2, -2)
    plc.db_write_dint(1, 4, 2_000_000_000)
    plc.db_write_real(1, 8, -0.5)
    assert bytes(emulator.db1[0:12]) == b"\xca\xfe\xff\xfe\x77\x35\x94\x00\xbf\x00\x00\x00"
    assert plc.db_read_word(1, 0) == 0xCAFE
    assert plc.db_read_int(1, 2) == -2
    assert plc.db_read_dint(1, 4) == 2_000_000_000
    assert plc.db_read_real(1, 8) == -0.5
    emulator.db1[12] = 0b0100_0000
    assert plc.db_read_bool(1, 12, 6) is True
    assert plc.db_read_bool(1, 12, 5) is False
    assert plc.read("DB1.DBX12.6") is True


def test_db_strings(plc: PlcClient, emulator: Emulator) -> None:
    emulator.db1[20:25] = b"\x0a\x03abc"
    assert plc.db_read_string(1, 20) == "abc"
    plc.db_write_string(1, 20, "hello")
    assert bytes(emulator.db1[20:27]) == b"\x0a\x05hello"
    assert plc.read("DB1.DBB20", DataType.STRING) == "hello"
    plc.db_write_string(1, 20, "")
    assert plc.db_read_string(1, 20) == ""
    assert emulator.db1[20] == 0x0A
    with pytest.raises(EncodingError, match="holds at most 10"):
        plc.db_write_string(1, 20, "x" * 11)


def test_transfers_larger_than_one_pdu_are_split_and_reassembled(
    plc: PlcClient, emulator: Emulator
) -> None:
    payload = bytes(i % 251 for i in range(2000))
    assert len(payload) > 4 * plc.pdu_length
    plc.write_bytes(Area.DB, 16, payload, db_number=2)
    assert bytes(emulator.db2[16:2016]) == payload
    assert bytes(emulator.db2[:16]) == bytes(16)
    assert plc.read_bytes(Area.DB, 16, 2000, db_number=2) == payload


def test_missing_db_and_out_of_range_access_are_typed_errors(plc: PlcClient) -> None:
    with pytest.raises(PlcRequestError, match=r"failed to read 2 byte\(s\) at DB99 byte 0"):
        plc.read("DB99.DBW0")
    with pytest.raises(PlcRequestError, match="at DB1 byte 120"):
        plc.read_bytes(Area.DB, 120, 16, db_number=1)
    with pytest.raises(PlcRequestError, match=r"failed to write 4 byte\(s\) at DB1 byte 126"):
        plc.db_write_dint(1, 126, 1)
    assert plc.connected
    assert plc.db_read_word(1, 0) == 0


def test_cpu_identity_and_run_state(plc: PlcClient) -> None:
    info = plc.cpu_info()
    assert info.order_number.startswith("6ES7")
    assert info.module_type.startswith("CPU")
    assert info.firmware.count(".") == 2
    assert plc.cpu_state() is CpuState.RUN
    assert plc.stop() is True
    assert plc.cpu_state() is CpuState.STOP
    assert plc.stop() is False
    assert plc.start() is True
    assert plc.wait_for_state(CpuState.RUN, timeout=2) is CpuState.RUN


def test_block_listing(plc: PlcClient) -> None:
    assert plc.list_blocks(BlockType.DB) == [1, 2]
    assert plc.list_blocks(BlockType.OB) == []


def test_connection_refused_is_actionable() -> None:
    port = free_port()
    with pytest.raises(PlcConnectionError, match=f"cannot connect to 127.0.0.1:{port}") as caught:
        PlcClient("127.0.0.1", port=port).connect()
    assert "Check the IP address" in str(caught.value)


def test_client_can_reconnect_after_disconnect(emulator: Emulator) -> None:
    client = PlcClient("127.0.0.1", port=emulator.port)
    for value in (1, 2):
        with client:
            client.write("MB0", value)
            assert client.read("MB0") == value
        assert not client.connected


def test_cli_end_to_end(emulator: Emulator, capsys: pytest.CaptureFixture[str]) -> None:
    assert mc7(emulator, "connect") == 0
    out = capsys.readouterr().out
    assert f"Connected to 127.0.0.1:{emulator.port} (rack 0, slot 2)" in out
    assert "CPU state:  RUN" in out

    assert mc7(emulator, "write", "MW10", "-1234", "--type", "int") == 0
    assert mc7(emulator, "read", "MW10", "--type", "int") == 0
    assert mc7(emulator, "read", "MW10") == 0
    assert capsys.readouterr().out == "MW10 = -1234\n-1234\n64302\n"

    assert mc7(emulator, "write", "DB1.DBD4", "1.5", "-t", "real") == 0
    assert mc7(emulator, "read", "DB1.DBD4", "-t", "real") == 0
    assert capsys.readouterr().out == "DB1.DBD4 = 1.5\n1.5\n"

    assert mc7(emulator, "info") == 0
    out = capsys.readouterr().out
    assert "State:         RUN" in out
    assert "Order number:  6ES7" in out

    assert mc7(emulator, "blocks") == 0
    assert "DB:  1 2\n" in capsys.readouterr().out

    assert mc7(emulator, "stop", "--yes") == 0
    assert mc7(emulator, "stop", "--yes") == 0
    assert mc7(emulator, "start", "--yes") == 0
    assert capsys.readouterr().out == "CPU state: STOP\nCPU is already in STOP\nCPU state: RUN\n"

    assert mc7(emulator, "read", "DB99.DBW0") == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("error: failed to read 2 byte(s) at DB99 byte 0")


def test_installed_entry_point_runs_as_a_subprocess(emulator: Emulator) -> None:
    emulator.markers[4] = 0x7B
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mc7",
            "read",
            "MB4",
            "-H",
            "127.0.0.1",
            "--port",
            str(emulator.port),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert (result.returncode, result.stdout, result.stderr) == (0, "123\n", "")

    failed = subprocess.run(
        [sys.executable, "-m", "mc7", "read", "MB4", "-H", "127.0.0.1", "--port", str(free_port())],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert failed.returncode == 1
    assert failed.stdout == ""
    assert failed.stderr.startswith("error: cannot connect to 127.0.0.1:")
    assert "Traceback" not in failed.stderr
