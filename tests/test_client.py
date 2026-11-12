"""Unit tests of PlcClient against a mocked snap7 client."""

from __future__ import annotations

from unittest.mock import MagicMock, call, create_autospec

import pytest
import snap7
from snap7.error import S7ConnectionError, S7ProtocolError, S7TimeoutError
from snap7.type import Area as S7Area
from snap7.type import Block as S7Block
from snap7.type import S7CpuInfo, S7OrderCode, WordLen

from mc7 import (
    AddressError,
    Area,
    BlockFormatError,
    BlockTransferError,
    BlockType,
    BlockVerifyError,
    CpuInfo,
    CpuState,
    DataType,
    EncodingError,
    NotConnectedError,
    PlcClient,
    PlcConnectionError,
    PlcRequestError,
    PlcTimeoutError,
)
from mc7.transfer import build_insert_request, build_request_download
from tests.support import make_block
from tests.test_transfer import ack, error, job

HOST = "192.168.0.10"


@pytest.fixture
def s7() -> MagicMock:
    mock: MagicMock = create_autospec(snap7.Client, instance=True)
    mock.get_pdu_length.return_value = 240
    mock.connection = MagicMock()
    return mock


@pytest.fixture
def plc(s7: MagicMock) -> PlcClient:
    client = PlcClient(HOST, snap7_client=s7)
    client.connect()
    return client


# ------------------------------------------------------------------ connection


def test_connect_uses_s7_300_defaults(s7: MagicMock) -> None:
    client = PlcClient(HOST, snap7_client=s7)
    assert not client.connected
    client.connect()
    s7.connect.assert_called_once_with(HOST, 0, 2, 102)
    assert client.connected


def test_connect_passes_custom_rack_slot_and_port(s7: MagicMock) -> None:
    PlcClient(HOST, rack=1, slot=3, port=1102, snap7_client=s7).connect()
    s7.connect.assert_called_once_with(HOST, 1, 3, 1102)


def test_connect_twice_does_not_reconnect(plc: PlcClient, s7: MagicMock) -> None:
    plc.connect()
    assert s7.connect.call_count == 1


def test_connect_failure_is_typed_and_actionable(s7: MagicMock) -> None:
    s7.connect.side_effect = S7ConnectionError("Connection failed: refused")
    client = PlcClient(HOST, snap7_client=s7)
    with pytest.raises(
        PlcConnectionError, match=r"cannot connect to 192\.168\.0\.10:102"
    ) as caught:
        client.connect()
    assert "rack 0, slot 2" in str(caught.value)
    assert "Check the IP address" in str(caught.value)
    assert isinstance(caught.value.__cause__, S7ConnectionError)
    assert not client.connected


def test_connect_timeout_is_a_timeout_error(s7: MagicMock) -> None:
    s7.connect.side_effect = S7TimeoutError("Receive timeout")
    with pytest.raises(PlcTimeoutError):
        PlcClient(HOST, snap7_client=s7).connect()


def test_empty_host_is_rejected() -> None:
    with pytest.raises(PlcConnectionError, match="no PLC host"):
        PlcClient("  ")


def test_context_manager_connects_and_disconnects(s7: MagicMock) -> None:
    with PlcClient(HOST, snap7_client=s7) as client:
        assert client.connected
    s7.disconnect.assert_called_once_with()
    assert not client.connected


def test_context_manager_disconnects_when_the_body_raises(s7: MagicMock) -> None:
    with pytest.raises(KeyError), PlcClient(HOST, snap7_client=s7):
        raise KeyError("boom")
    s7.disconnect.assert_called_once_with()


def test_disconnect_failure_does_not_mask_the_body_exception(s7: MagicMock) -> None:
    s7.disconnect.side_effect = OSError("socket already closed")
    with pytest.raises(KeyError), PlcClient(HOST, snap7_client=s7):
        raise KeyError("boom")


def test_disconnect_failure_is_reported_when_the_body_succeeded(s7: MagicMock) -> None:
    s7.disconnect.side_effect = OSError("socket already closed")
    with pytest.raises(PlcConnectionError, match="error while disconnecting"):  # noqa: SIM117
        with PlcClient(HOST, snap7_client=s7):
            pass


def test_operations_require_a_connection(s7: MagicMock) -> None:
    client = PlcClient(HOST, snap7_client=s7)
    for operation in (
        lambda: client.read("MW0"),
        lambda: client.write("MW0", 1),
        lambda: client.write("M0.0", True),
        client.cpu_state,
        client.cpu_info,
        client.stop,
        lambda: client.list_blocks(BlockType.OB),
        lambda: client.upload_block(BlockType.OB, 1),
        lambda: client.download_block(make_block()),
        lambda: client.pdu_length,
    ):
        with pytest.raises(NotConnectedError, match="call connect"):
            operation()
    assert s7.method_calls == []


# ------------------------------------------------------------------ reading and writing


@pytest.mark.parametrize(
    ("address", "s7_area", "db"),
    [
        ("IB3", S7Area.PE, 0),
        ("QB3", S7Area.PA, 0),
        ("MB3", S7Area.MK, 0),
        ("DB7.DBB3", S7Area.DB, 7),
    ],
)
def test_areas_map_to_snap7(
    plc: PlcClient, s7: MagicMock, address: str, s7_area: S7Area, db: int
) -> None:
    s7.read_area.return_value = bytearray(b"\x2a")
    assert plc.read(address) == 42
    s7.read_area.assert_called_once_with(s7_area, db, 3, 1)


@pytest.mark.parametrize(
    ("address", "dtype", "wire", "value", "target"),
    [
        ("MW10", None, b"\xfb\x2e", 0xFB2E, (S7Area.MK, 0, 10)),
        ("MW10", DataType.INT, b"\xfb\x2e", -1234, (S7Area.MK, 0, 10)),
        ("MD20", None, b"\xff\xff\xff\xfe", 0xFFFFFFFE, (S7Area.MK, 0, 20)),
        ("MD20", DataType.DINT, b"\xff\xff\xff\xfe", -2, (S7Area.MK, 0, 20)),
        ("DB1.DBD4", DataType.REAL, b"\x40\x60\x00\x00", 3.5, (S7Area.DB, 1, 4)),
    ],
)
def test_read_and_write_scalars(
    plc: PlcClient,
    s7: MagicMock,
    address: str,
    dtype: DataType | None,
    wire: bytes,
    value: float,
    target: tuple[S7Area, int, int],
) -> None:
    s7.read_area.return_value = bytearray(wire)
    assert plc.read(address, dtype) == value
    s7.read_area.assert_called_once_with(*target, len(wire))
    plc.write(address, value, dtype)
    s7.write_area.assert_called_once_with(*target, bytearray(wire))


@pytest.mark.parametrize(("bit", "expected"), [(0, True), (1, False), (2, True), (7, True)])
def test_read_bit_masks_the_containing_byte(
    plc: PlcClient, s7: MagicMock, bit: int, expected: bool
) -> None:
    s7.read_area.return_value = bytearray(b"\x85")
    assert plc.read(f"I4.{bit}") is expected
    s7.read_area.assert_called_once_with(S7Area.PE, 0, 4, 1)


def test_write_bit_uses_the_atomic_bit_transport(plc: PlcClient, s7: MagicMock) -> None:
    plc.write("Q10.3", True)
    plc.write("DB2.DBX1.7", False)
    assert s7.write_area.call_args_list == [
        call(S7Area.PA, 0, 83, bytearray(b"\x01"), WordLen.Bit),
        call(S7Area.DB, 2, 15, bytearray(b"\x00"), WordLen.Bit),
    ]
    s7.read_area.assert_not_called()


def test_write_rejects_values_of_the_wrong_kind_before_sending(
    plc: PlcClient, s7: MagicMock
) -> None:
    with pytest.raises(EncodingError):
        plc.write("M0.0", 1)
    with pytest.raises(EncodingError):
        plc.write("MW0", "12")
    with pytest.raises(EncodingError, match="out of range"):
        plc.write("MW0", 70000)
    with pytest.raises(EncodingError):
        plc.write("DB1.DBB0", 5, DataType.STRING)
    with pytest.raises(AddressError, match="allowed types"):
        plc.write("MW0", 1.0, DataType.REAL)
    assert s7.method_calls == [call.connect(HOST, 0, 2, 102)]


def test_raw_byte_access(plc: PlcClient, s7: MagicMock) -> None:
    s7.read_area.return_value = bytearray(b"\x01\x02\x03")
    data = plc.read_bytes(Area.DB, 8, 3, db_number=5)
    assert data == b"\x01\x02\x03"
    assert isinstance(data, bytes)
    plc.write_bytes(Area.OUTPUT, 0, b"\xff\x00")
    s7.write_area.assert_called_once_with(S7Area.PA, 0, 0, bytearray(b"\xff\x00"))


@pytest.mark.parametrize(
    ("area", "start", "size", "db", "fragment"),
    [
        (Area.MARKER, 0, 0, 0, "size must be at least 1"),
        (Area.MARKER, -1, 1, 0, "byte offset -1"),
        (Area.MARKER, 65535, 2, 0, "byte offset 65536"),
        (Area.DB, 0, 1, 0, "DB number 0"),
        (Area.MARKER, 0, 1, 3, "does not take a DB number"),
    ],
)
def test_invalid_ranges_are_rejected_before_sending(
    plc: PlcClient, s7: MagicMock, area: Area, start: int, size: int, db: int, fragment: str
) -> None:
    with pytest.raises(AddressError, match=fragment):
        plc.read_bytes(area, start, size, db_number=db)
    s7.read_area.assert_not_called()


def test_short_read_is_an_error(plc: PlcClient, s7: MagicMock) -> None:
    s7.read_area.return_value = bytearray(b"\x00")
    with pytest.raises(PlcRequestError, match=r"returned 1 byte\(s\) instead of 2"):
        plc.read("MW0")


def test_db_typed_helpers(plc: PlcClient, s7: MagicMock) -> None:
    replies = {
        (10, 1): b"\x80",
        (2, 2): b"\xff\xfe",
        (4, 4): b"\xff\xfe\xee\x90",
    }
    s7.read_area.side_effect = lambda _a, _db, start, size: bytearray(replies[(start, size)])
    assert plc.db_read_bool(3, 10, 7) is True
    assert plc.db_read_bool(3, 10, 0) is False
    assert plc.db_read_word(3, 2) == 0xFFFE
    assert plc.db_read_int(3, 2) == -2
    assert plc.db_read_dint(3, 4) == -70000
    replies[(4, 4)] = b"\x3f\xc0\x00\x00"
    assert plc.db_read_real(3, 4) == 1.5

    plc.db_write_bool(3, 10, 7, True)
    plc.db_write_word(3, 2, 0xBEEF)
    plc.db_write_int(3, 2, -2)
    plc.db_write_dint(3, 4, -70000)
    plc.db_write_real(3, 4, 1.5)
    assert s7.write_area.call_args_list == [
        call(S7Area.DB, 3, 87, bytearray(b"\x01"), WordLen.Bit),
        call(S7Area.DB, 3, 2, bytearray(b"\xbe\xef")),
        call(S7Area.DB, 3, 2, bytearray(b"\xff\xfe")),
        call(S7Area.DB, 3, 4, bytearray(b"\xff\xfe\xee\x90")),
        call(S7Area.DB, 3, 4, bytearray(b"\x3f\xc0\x00\x00")),
    ]


def test_string_read_fetches_header_then_only_the_used_characters(
    plc: PlcClient, s7: MagicMock
) -> None:
    s7.read_area.side_effect = [bytearray(b"\x14\x05"), bytearray(b"hello")]
    assert plc.db_read_string(1, 20) == "hello"
    assert s7.read_area.call_args_list == [call(S7Area.DB, 1, 20, 2), call(S7Area.DB, 1, 22, 5)]


def test_empty_string_needs_a_single_read(plc: PlcClient, s7: MagicMock) -> None:
    s7.read_area.return_value = bytearray(b"\x14\x00")
    assert plc.read("DB1.DBB20", DataType.STRING) == ""
    assert s7.read_area.call_count == 1


def test_string_write_preserves_the_declared_max_length(plc: PlcClient, s7: MagicMock) -> None:
    s7.read_area.return_value = bytearray(b"\x0a\x03")
    plc.db_write_string(1, 20, "hey")
    s7.write_area.assert_called_once_with(S7Area.DB, 1, 21, bytearray(b"\x03hey"))


def test_string_write_enforces_the_declared_max_length(plc: PlcClient, s7: MagicMock) -> None:
    s7.read_area.return_value = bytearray(b"\x04\x00")
    with pytest.raises(EncodingError, match="holds at most 4"):
        plc.db_write_string(1, 20, "hello")
    s7.write_area.assert_not_called()


def test_string_at_a_non_string_offset_is_reported_with_its_location(
    plc: PlcClient, s7: MagicMock
) -> None:
    s7.read_area.return_value = bytearray(b"\x02\x09")
    with pytest.raises(EncodingError, match="DB1 byte 20: invalid STRING header"):
        plc.db_read_string(1, 20)


# ------------------------------------------------------------------ error translation


def test_plc_rejection_becomes_a_request_error(plc: PlcClient, s7: MagicMock) -> None:
    s7.read_area.side_effect = S7ProtocolError("Object does not exist (0x0a)", error_code=0x0A)
    with pytest.raises(PlcRequestError) as caught:
        plc.read("DB99.DBW0")
    message = str(caught.value)
    assert "failed to read 2 byte(s) at DB99 byte 0" in message
    assert "192.168.0.10:102" in message
    assert "Object does not exist" in message
    assert caught.value.code == 0x0A
    assert isinstance(caught.value.__cause__, S7ProtocolError)
    assert plc.connected


def test_runtime_error_from_snap7_is_translated(plc: PlcClient, s7: MagicMock) -> None:
    s7.get_cpu_state.side_effect = RuntimeError("Read SZL failed")
    with pytest.raises(PlcRequestError, match="failed to read the CPU state") as caught:
        plc.cpu_state()
    assert caught.value.code is None


@pytest.mark.parametrize("failure", [S7ConnectionError("Send failed"), BrokenPipeError("pipe")])
def test_lost_connection_marks_the_client_disconnected(
    plc: PlcClient, s7: MagicMock, failure: Exception
) -> None:
    s7.write_area.side_effect = failure
    with pytest.raises(PlcConnectionError, match="failed to write 2 byte"):
        plc.write("MW0", 1)
    assert not plc.connected
    with pytest.raises(NotConnectedError):
        plc.read("MW0")


@pytest.mark.parametrize("failure", [S7TimeoutError("Receive timeout"), TimeoutError("timed out")])
def test_timeouts_are_timeout_errors(plc: PlcClient, s7: MagicMock, failure: Exception) -> None:
    s7.read_area.side_effect = failure
    with pytest.raises(PlcTimeoutError, match="failed to read"):
        plc.read("MW0")


def test_programming_errors_are_not_swallowed(plc: PlcClient, s7: MagicMock) -> None:
    s7.read_area.side_effect = TypeError("bug")
    with pytest.raises(TypeError):
        plc.read("MW0")


# ------------------------------------------------------------------ CPU


@pytest.mark.parametrize(
    ("raw", "state"),
    [
        ("S7CpuStatusRun", CpuState.RUN),
        ("S7CpuStatusStop", CpuState.STOP),
        ("S7CpuStatusUnknown", CpuState.UNKNOWN),
        ("something new", CpuState.UNKNOWN),
    ],
)
def test_cpu_state_mapping(plc: PlcClient, s7: MagicMock, raw: str, state: CpuState) -> None:
    s7.get_cpu_state.return_value = raw
    assert plc.cpu_state() is state


def test_cpu_info_combines_identification_and_order_code(plc: PlcClient, s7: MagicMock) -> None:
    info = S7CpuInfo()
    info.ModuleTypeName = b"CPU 317-2 DP"
    info.SerialNumber = b"S C-X4U421302009"
    info.ASName = b"SIMATIC 300 Station "
    info.ModuleName = b"CPU 317-2 DP"
    order = S7OrderCode()
    order.OrderCode = b"6ES7 317-2AK14-0AB0 "
    order.V1, order.V2, order.V3 = 3, 3, 12
    s7.get_cpu_info.return_value = info
    s7.get_order_code.return_value = order
    assert plc.cpu_info() == CpuInfo(
        module_type="CPU 317-2 DP",
        order_number="6ES7 317-2AK14-0AB0",
        firmware="3.3.12",
        serial_number="S C-X4U421302009",
        station_name="SIMATIC 300 Station",
        module_name="CPU 317-2 DP",
    )


def test_stop_and_start_send_the_command_only_when_needed(plc: PlcClient, s7: MagicMock) -> None:
    s7.get_cpu_state.return_value = "S7CpuStatusRun"
    assert plc.start() is False
    assert plc.stop() is True
    s7.plc_stop.assert_called_once_with()

    s7.get_cpu_state.return_value = "S7CpuStatusStop"
    assert plc.stop() is False
    assert plc.start() is True
    assert plc.start(cold=True) is True
    s7.plc_hot_start.assert_called_once_with()
    s7.plc_cold_start.assert_called_once_with()
    assert s7.plc_stop.call_count == 1


def test_refused_run_state_change_explains_what_to_check(plc: PlcClient, s7: MagicMock) -> None:
    s7.get_cpu_state.return_value = "S7CpuStatusStop"
    s7.plc_hot_start.side_effect = S7ProtocolError("PLC control failed", error_code=0x8104)
    with pytest.raises(PlcRequestError, match="failed to start the CPU") as caught:
        plc.start()
    assert "mode selector and protection level" in str(caught.value)
    assert caught.value.code == 0x8104


def test_wait_for_state_polls_until_reached(
    plc: PlcClient, s7: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("mc7.client.time.sleep", lambda _seconds: None)
    s7.get_cpu_state.side_effect = ["S7CpuStatusStop", "S7CpuStatusStop", "S7CpuStatusRun"]
    assert plc.wait_for_state(CpuState.RUN) is CpuState.RUN
    assert s7.get_cpu_state.call_count == 3


def test_wait_for_state_returns_the_last_state_on_timeout(plc: PlcClient, s7: MagicMock) -> None:
    s7.get_cpu_state.return_value = "S7CpuStatusStop"
    assert plc.wait_for_state(CpuState.RUN, timeout=0.0) is CpuState.STOP


# ------------------------------------------------------------------ blocks


def test_list_blocks_is_sorted(plc: PlcClient, s7: MagicMock) -> None:
    s7.list_blocks_of_type.return_value = [100, 1, 35]
    assert plc.list_blocks(BlockType.OB) == [1, 35, 100]
    assert s7.list_blocks_of_type.call_args.args[0] is S7Block.OB


@pytest.mark.parametrize("block_type", [BlockType.OB, BlockType.FC, BlockType.FB, BlockType.DB])
def test_upload_block_returns_the_full_image(
    plc: PlcClient, s7: MagicMock, block_type: BlockType
) -> None:
    image = make_block(block_type, 5)
    s7.full_upload.return_value = (bytearray(image), len(image))
    uploaded = plc.upload_block(block_type, 5)
    assert uploaded == image
    assert isinstance(uploaded, bytes)
    s7.full_upload.assert_called_once_with(S7Block[block_type.name], 5)


def test_upload_rejects_an_image_of_a_different_block(plc: PlcClient, s7: MagicMock) -> None:
    image = make_block(BlockType.FC, 6)
    s7.full_upload.return_value = (bytearray(image), len(image))
    with pytest.raises(PlcRequestError, match="asked the PLC for FC5 but received FC6"):
        plc.upload_block(BlockType.FC, 5)


def test_upload_rejects_a_corrupt_image(plc: PlcClient, s7: MagicMock) -> None:
    s7.full_upload.return_value = (bytearray(make_block(BlockType.FC, 5)[:-3]), 0)
    with pytest.raises(PlcRequestError, match="invalid image for FC5"):
        plc.upload_block(BlockType.FC, 5)


def test_upload_of_a_missing_block_names_the_block(plc: PlcClient, s7: MagicMock) -> None:
    s7.full_upload.side_effect = S7ProtocolError("block not found", error_code=0xD209)
    with pytest.raises(PlcRequestError, match="failed to upload OB99") as caught:
        plc.upload_block(BlockType.OB, 99)
    assert caught.value.code == 0xD209


def test_download_block_runs_the_sequence_on_the_raw_connection(
    plc: PlcClient, s7: MagicMock
) -> None:
    image = make_block(BlockType.FC, 5)
    s7.get_pdu_length.return_value = 480
    s7.connection.receive_data.side_effect = [
        ack(1, 0x1A),
        job(0x4001, 0x1B),
        job(0x4002, 0x1C),
        ack(2, 0x28),
    ]
    header = plc.download_block(image)
    assert header.name == "FC5"
    sent = [c.args[0] for c in s7.connection.send_data.call_args_list]
    assert sent[0] == build_request_download(1, header)
    assert sent[1][18:] == image
    assert sent[3] == build_insert_request(2, header)
    s7.download.assert_not_called()


def test_download_rejects_invalid_images_without_sending(plc: PlcClient, s7: MagicMock) -> None:
    with pytest.raises(BlockFormatError):
        plc.download_block(make_block()[:-1])
    s7.connection.send_data.assert_not_called()


def test_download_refusal_is_a_transfer_error(plc: PlcClient, s7: MagicMock) -> None:
    s7.connection.receive_data.side_effect = [error(1, 0xD241)]
    with pytest.raises(BlockTransferError, match="protection level") as caught:
        plc.download_block(make_block())
    assert caught.value.code == 0xD241
    assert plc.connected


def test_download_with_a_dropped_connection(plc: PlcClient, s7: MagicMock) -> None:
    s7.connection.receive_data.side_effect = S7ConnectionError("Receive failed")
    with pytest.raises(PlcConnectionError, match="failed to download FC1"):
        plc.download_block(make_block())
    assert not plc.connected


def test_verify_block_accepts_an_identical_block(plc: PlcClient, s7: MagicMock) -> None:
    image = make_block(BlockType.DB, 9, language=5)
    s7.full_upload.return_value = (bytearray(image), len(image))
    assert plc.verify_block(image).name == "DB9"


def test_verify_block_reports_the_first_difference(plc: PlcClient, s7: MagicMock) -> None:
    image = make_block(BlockType.DB, 9, mc7=b"\x00\x01\x02\x03")
    changed = bytearray(image)
    changed[38] = 0xEE
    s7.full_upload.return_value = (changed, len(changed))
    with pytest.raises(
        BlockVerifyError, match=r"DB9 .* byte offset 38 \(expected 0x02, found 0xEE\)"
    ):
        plc.verify_block(image)


def test_verify_block_reports_a_size_difference(plc: PlcClient, s7: MagicMock) -> None:
    image = make_block(BlockType.DB, 9, mc7=b"\x00\x01")
    other = make_block(BlockType.DB, 9, mc7=b"\x00\x01\x02\x03")
    s7.full_upload.return_value = (bytearray(other), len(other))
    with pytest.raises(BlockVerifyError, match=r"is 96 byte\(s\), the reference is 94"):
        plc.verify_block(image)
