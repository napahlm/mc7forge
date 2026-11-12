"""CLI tests with the PLC client replaced by a mock."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, create_autospec

import pytest

from mc7 import BlockType, CpuInfo, CpuState, DataType, PlcClient, PlcRequestError, cli
from mc7.addressing import parse_address
from tests.support import make_block

HOST = "10.0.0.5"


@pytest.fixture
def plc(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    mock: MagicMock = create_autospec(PlcClient, instance=True)
    mock.__enter__.return_value = mock
    mock.host, mock.rack, mock.slot, mock.port = HOST, 0, 2, 102
    opened: list[object] = []

    def open_client(args: object) -> MagicMock:
        opened.append(args)
        return mock

    monkeypatch.setattr(cli, "open_client", open_client)
    mock.opened = opened
    monkeypatch.delenv(cli.HOST_ENV, raising=False)
    return mock


def run(*argv: str) -> int:
    return cli.main(list(argv))


def test_read_prints_the_bare_value(plc: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    plc.read.return_value = -1234
    assert run("read", "mw10", "--type", "INT", "-H", HOST) == 0
    plc.read.assert_called_once_with(parse_address("MW10"), DataType.INT)
    assert capsys.readouterr().out == "-1234\n"
    plc.__exit__.assert_called_once()


@pytest.mark.parametrize(("value", "text"), [(True, "true"), (False, "false"), (1.5, "1.5")])
def test_read_formats_values(
    plc: MagicMock, capsys: pytest.CaptureFixture[str], value: object, text: str
) -> None:
    plc.read.return_value = value
    assert run("read", "MD0", "-t", "real") == 0
    assert capsys.readouterr().out == f"{text}\n"


@pytest.mark.parametrize(
    ("address", "dtype", "word", "value"),
    [
        ("Q0.0", None, "true", True),
        ("Q0.0", None, "OFF", False),
        ("Q0.0", None, "1", True),
        ("MB0", None, "0x1F", 31),
        ("MW10", "int", "-5", -5),
        ("MD0", "real", "2.5", 2.5),
        ("MD0", "dint", "-70000", -70000),
        ("DB1.DBB20", "string", "hello world", "hello world"),
    ],
)
def test_write_parses_the_value_for_the_type(
    plc: MagicMock,
    capsys: pytest.CaptureFixture[str],
    address: str,
    dtype: str | None,
    word: str,
    value: object,
) -> None:
    argv = ["write", address, word] + (["--type", dtype] if dtype else [])
    assert run(*argv) == 0
    (target, written, resolved), _ = plc.write.call_args
    assert target == parse_address(address)
    assert written == value
    assert type(written) is type(value)
    assert isinstance(resolved, DataType)
    assert capsys.readouterr().out.startswith(f"{address} = ")


@pytest.mark.parametrize(
    ("argv", "fragment"),
    [
        (["write", "Q0.0", "maybe"], "not a bit value"),
        (["write", "MW0", "abc"], "not a valid word value"),
        (["write", "MW0", "1.5"], "not a valid word value"),
        (["write", "MD0", "x", "-t", "real"], "not a valid real value"),
        (["read", "Z9"], "cannot parse address"),
        (["read", "MW0", "-t", "real"], "allowed types"),
    ],
)
def test_bad_input_fails_before_connecting(
    plc: MagicMock, capsys: pytest.CaptureFixture[str], argv: list[str], fragment: str
) -> None:
    assert run(*argv) == 1
    captured = capsys.readouterr()
    assert captured.err.startswith("error: ")
    assert fragment in captured.err
    assert captured.out == ""
    assert plc.opened == []


def test_plc_failure_is_reported_on_stderr(
    plc: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    plc.read.side_effect = PlcRequestError("failed to read 2 byte(s) at DB99 byte 0")
    assert run("read", "DB99.DBW0") == 1
    assert capsys.readouterr().err == "error: failed to read 2 byte(s) at DB99 byte 0\n"
    plc.__exit__.assert_called_once()


def test_missing_host_explains_how_to_set_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv(cli.HOST_ENV, raising=False)
    assert cli.main(["info"]) == 1
    assert "pass --host or set the MC7_HOST environment variable" in capsys.readouterr().err


def test_host_and_connection_options_reach_the_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(cli.HOST_ENV, "10.1.1.1")
    args = cli.build_parser().parse_args(["info"])
    client = cli.open_client(args)
    assert (client.host, client.rack, client.slot, client.port) == ("10.1.1.1", 0, 2, 102)
    args = cli.build_parser().parse_args(
        ["info", "-H", "10.2.2.2", "--rack", "1", "--slot", "3", "--port", "1102"]
    )
    client = cli.open_client(args)
    assert (client.host, client.rack, client.slot, client.port) == ("10.2.2.2", 1, 3, 1102)


def test_usage_errors_exit_with_code_2(plc: MagicMock) -> None:
    for argv in ([], ["bogus"], ["read"], ["read", "MW0", "--type", "float"]):
        with pytest.raises(SystemExit) as caught:
            cli.main(argv)
        assert caught.value.code == 2


def test_connect_reports_the_session(plc: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    plc.pdu_length = 240
    plc.cpu_state.return_value = CpuState.RUN
    assert run("connect") == 0
    assert capsys.readouterr().out == (
        "Connected to 10.0.0.5:102 (rack 0, slot 2)\nPDU length: 240\nCPU state:  RUN\n"
    )


def test_info_prints_an_aligned_table(plc: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    plc.cpu_state.return_value = CpuState.STOP
    plc.cpu_info.return_value = CpuInfo(
        module_type="CPU 317-2 DP",
        order_number="6ES7 317-2AK14-0AB0",
        firmware="3.3.12",
        serial_number="S C-X4U421302009",
        station_name="",
        module_name="CPU 317-2 DP",
    )
    assert run("info") == 0
    assert capsys.readouterr().out == (
        "State:         STOP\n"
        "Module type:   CPU 317-2 DP\n"
        "Order number:  6ES7 317-2AK14-0AB0\n"
        "Firmware:      V3.3.12\n"
        "Serial number: S C-X4U421302009\n"
        "Station name:  -\n"
        "Module name:   CPU 317-2 DP\n"
    )


def test_blocks_lists_each_type(plc: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    plc.list_blocks.side_effect = lambda block_type: {BlockType.OB: [1, 35]}.get(block_type, [])
    assert run("blocks") == 0
    assert capsys.readouterr().out == "OB:  1 35\nFB:  -\nFC:  -\nDB:  -\n"
    assert run("blocks", "--type", "ob", "--type", "SDB") == 0
    assert capsys.readouterr().out == "OB:  1 35\nSDB: -\n"


def test_upload_writes_validated_files(
    plc: MagicMock, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    images = {
        (BlockType.OB, 1): make_block(BlockType.OB, 1),
        (BlockType.FC, 5): make_block(BlockType.FC, 5, mc7=bytes(10)),
    }
    plc.upload_block.side_effect = lambda block_type, number: images[(block_type, number)]
    assert run("upload", "OB1", "fc5", "-o", str(tmp_path)) == 0
    assert (tmp_path / "OB1.mc7").read_bytes() == images[(BlockType.OB, 1)]
    assert (tmp_path / "FC5.mc7").read_bytes() == images[(BlockType.FC, 5)]
    assert capsys.readouterr().out == (
        f"OB1 -> {tmp_path / 'OB1.mc7'} (94 bytes)\nFC5 -> {tmp_path / 'FC5.mc7'} (102 bytes)\n"
    )


def test_upload_does_not_overwrite_without_force(
    plc: MagicMock, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    old, new = make_block(mc7=b"\x01\x01"), make_block(mc7=b"\x02\x02")
    (tmp_path / "FC1.mc7").write_bytes(old)
    plc.upload_block.return_value = new
    assert run("upload", "FC1", "-o", str(tmp_path)) == 1
    assert "already exists; pass --force" in capsys.readouterr().err
    assert (tmp_path / "FC1.mc7").read_bytes() == old
    plc.upload_block.assert_not_called()
    assert run("upload", "FC1", "-o", str(tmp_path), "--force") == 0
    assert (tmp_path / "FC1.mc7").read_bytes() == new


def test_upload_all_uploads_every_listed_block(plc: MagicMock, tmp_path: Path) -> None:
    present = {BlockType.OB: [1], BlockType.FC: [2, 3], BlockType.DB: [10]}
    plc.list_blocks.side_effect = lambda block_type: present.get(block_type, [])
    plc.upload_block.side_effect = lambda block_type, number: make_block(block_type, number)
    assert run("upload", "--all", "-o", str(tmp_path)) == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "DB10.mc7",
        "FC2.mc7",
        "FC3.mc7",
        "OB1.mc7",
    ]


@pytest.mark.parametrize("argv", [["upload"], ["upload", "OB1", "--all"]])
def test_upload_needs_block_names_or_all(
    plc: MagicMock, capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    assert run(*argv) == 1
    assert "or pass --all, not both" in capsys.readouterr().err
    assert plc.opened == []


def test_upload_rejects_bad_block_names(plc: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    assert run("upload", "OB") == 1
    assert "cannot parse block name 'OB'" in capsys.readouterr().err


def block_file(tmp_path: Path) -> tuple[Path, bytes]:
    image = make_block(BlockType.FC, 5)
    path = tmp_path / "FC5.mc7"
    path.write_bytes(image)
    return path, image


def test_download_sends_and_verifies(
    plc: MagicMock, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path, image = block_file(tmp_path)
    assert run("download", str(path), "--yes") == 0
    plc.download_block.assert_called_once_with(image)
    plc.verify_block.assert_called_once_with(image)
    assert capsys.readouterr().out == (
        f"FC5 downloaded (94 bytes)\nFC5 verified: the block in the PLC is identical to {path}\n"
    )


def test_download_can_skip_verification(plc: MagicMock, tmp_path: Path) -> None:
    path, _ = block_file(tmp_path)
    assert run("download", str(path), "-y", "--no-verify") == 0
    plc.download_block.assert_called_once()
    plc.verify_block.assert_not_called()


def test_download_refuses_without_confirmation_when_not_interactive(
    plc: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, _ = block_file(tmp_path)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert run("download", str(path)) == 1
    assert capsys.readouterr().err == (
        "error: refusing to download FC5 (94 bytes) to 10.0.0.5, replacing the block there "
        "without --yes (input is not a terminal)\n"
    )
    plc.download_block.assert_not_called()
    plc.__enter__.assert_not_called()


@pytest.mark.parametrize(
    ("answer", "sent"), [("y", True), ("YES", True), ("", False), ("n", False)]
)
def test_download_asks_interactively(
    plc: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    answer: str,
    sent: bool,
) -> None:
    path, _ = block_file(tmp_path)
    prompts: list[str] = []

    def fake_input(prompt: str) -> str:
        prompts.append(prompt)
        return answer

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", fake_input)
    assert run("download", str(path)) == (0 if sent else 1)
    assert prompts == [
        "About to download FC5 (94 bytes) to 10.0.0.5, replacing the block there. Continue? [y/N] "
    ]
    assert plc.download_block.called is sent
    if not sent:
        assert "aborted, nothing was sent" in capsys.readouterr().err


def test_download_rejects_a_corrupt_file_before_connecting(
    plc: MagicMock, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "FC5.mc7"
    path.write_bytes(make_block()[:-4])
    assert run("download", str(path), "--yes") == 1
    assert "FC5.mc7: header declares" in capsys.readouterr().err
    assert plc.opened == []


def test_download_of_a_missing_file(plc: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    assert run("download", "/nonexistent/OB1.mc7", "--yes") == 1
    assert "No such file" in capsys.readouterr().err


def test_stop_and_start(plc: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    plc.stop.return_value = True
    plc.wait_for_state.return_value = CpuState.STOP
    assert run("stop", "--yes") == 0
    plc.wait_for_state.assert_called_once_with(CpuState.STOP)
    assert capsys.readouterr().out == "CPU state: STOP\n"

    plc.start.return_value = True
    plc.wait_for_state.return_value = CpuState.RUN
    assert run("start", "--yes", "--cold") == 0
    plc.start.assert_called_once_with(cold=True)
    assert capsys.readouterr().out == "CPU state: RUN\n"


def test_stop_when_already_stopped(plc: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    plc.stop.return_value = False
    assert run("stop", "-y") == 0
    assert capsys.readouterr().out == "CPU is already in STOP\n"
    plc.wait_for_state.assert_not_called()


def test_start_that_does_not_reach_run_fails(
    plc: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    plc.start.return_value = True
    plc.wait_for_state.return_value = CpuState.STOP
    assert run("start", "-y") == 1
    assert "reports STOP instead of RUN" in capsys.readouterr().err


def test_run_state_changes_need_confirmation(
    plc: MagicMock, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert run("stop") == 1
    assert run("start") == 1
    assert capsys.readouterr().err == (
        "error: refusing to put the CPU at 10.0.0.5 into STOP without --yes "
        "(input is not a terminal)\n"
        "error: refusing to start the CPU at 10.0.0.5 (warm restart) without --yes "
        "(input is not a terminal)\n"
    )
    plc.stop.assert_not_called()
    plc.start.assert_not_called()
