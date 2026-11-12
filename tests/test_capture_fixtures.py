"""The fixture capture script only ever reads from the PLC."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, create_autospec

import pytest

from mc7 import BlockType, PlcClient, PlcRequestError
from scripts import capture_fixtures
from tests.support import make_block, reference_blocks

READ_ONLY_CALLS = {"connect", "disconnect", "__enter__", "__exit__", "list_blocks", "upload_block"}


@pytest.fixture
def plc(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    mock: MagicMock = create_autospec(PlcClient, instance=True)
    mock.__enter__.return_value = mock
    present = {BlockType.OB: [35, 1, 100], BlockType.FC: [7, 3], BlockType.DB: [20, 10]}
    mock.list_blocks.side_effect = lambda block_type: present.get(block_type, [])
    mock.upload_block.side_effect = lambda block_type, number: make_block(block_type, number)
    created: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def factory(*args: object, **kwargs: object) -> MagicMock:
        created.append((args, kwargs))
        return mock

    monkeypatch.setattr(capture_fixtures, "PlcClient", factory)
    mock.created = created
    return mock


def calls(plc: MagicMock) -> set[str]:
    return {name.split(".")[0] for name, _args, _kwargs in plc.mock_calls}


def test_default_capture_takes_ob1_the_first_fc_and_the_first_db(
    plc: MagicMock, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert capture_fixtures.main(["--host", "10.0.0.5", "-o", str(tmp_path)]) == 0
    assert plc.created == [(("10.0.0.5",), {"rack": 0, "slot": 2, "port": 102})]
    assert sorted(path.name for path in tmp_path.iterdir()) == ["DB10.mc7", "FC3.mc7", "OB1.mc7"]
    assert (tmp_path / "FC3.mc7").read_bytes() == make_block(BlockType.FC, 3)
    out = capsys.readouterr().out
    assert out.startswith(f"OB1 -> {tmp_path / 'OB1.mc7'} (87 bytes: payload 2, interface 7, ")
    assert out.count("\n") == 3


def test_capture_only_uses_read_only_client_methods(plc: MagicMock, tmp_path: Path) -> None:
    assert capture_fixtures.main(["--host", "10.0.0.5", "-o", str(tmp_path)]) == 0
    assert capture_fixtures.main(["--host", "10.0.0.5", "-o", str(tmp_path), "--force", "FB9"]) == 0
    assert calls(plc) <= READ_ONLY_CALLS
    assert {"list_blocks", "upload_block"} <= calls(plc)


def test_named_blocks_are_captured_without_listing(plc: MagicMock, tmp_path: Path) -> None:
    argv = ["--host", "10.0.0.5", "--rack", "1", "--slot", "3", "--port", "1102"]
    assert capture_fixtures.main([*argv, "-o", str(tmp_path), "ob35", "DB20"]) == 0
    assert plc.created == [(("10.0.0.5",), {"rack": 1, "slot": 3, "port": 1102})]
    assert sorted(path.name for path in tmp_path.iterdir()) == ["DB20.mc7", "OB35.mc7"]
    plc.list_blocks.assert_not_called()


def test_missing_block_types_are_skipped(
    plc: MagicMock, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plc.list_blocks.side_effect = lambda block_type: [40] if block_type is BlockType.OB else []
    assert capture_fixtures.main(["--host", "10.0.0.5", "-o", str(tmp_path)]) == 0
    assert [path.name for path in tmp_path.iterdir()] == ["OB40.mc7"]
    assert "no FC present, skipped\nno DB present, skipped\n" in capsys.readouterr().out


def test_an_empty_plc_is_an_error(
    plc: MagicMock, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plc.list_blocks.side_effect = lambda _block_type: []
    assert capture_fixtures.main(["--host", "10.0.0.5", "-o", str(tmp_path)]) == 1
    assert "reports no OB, FC or DB" in capsys.readouterr().err
    plc.upload_block.assert_not_called()


def test_existing_real_fixtures_are_not_overwritten_without_force(
    plc: MagicMock, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "FC3.mc7").write_bytes(b"keep me")
    assert capture_fixtures.main(["--host", "10.0.0.5", "-o", str(tmp_path)]) == 1
    assert "FC3.mc7 already exist(s); pass --force" in capsys.readouterr().err
    assert (tmp_path / "FC3.mc7").read_bytes() == b"keep me"
    assert [path.name for path in tmp_path.iterdir()] == ["FC3.mc7"]
    plc.upload_block.assert_not_called()

    assert capture_fixtures.main(["--host", "10.0.0.5", "-o", str(tmp_path), "--force"]) == 0
    assert (tmp_path / "FC3.mc7").read_bytes() == make_block(BlockType.FC, 3)


def test_plc_errors_are_reported(
    plc: MagicMock, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plc.upload_block.side_effect = PlcRequestError("failed to upload OB1")
    assert capture_fixtures.main(["--host", "10.0.0.5", "-o", str(tmp_path)]) == 1
    assert capsys.readouterr().err == "error: failed to upload OB1\n"


def test_unexpected_layout_is_shown_in_the_capture_summary(
    plc: MagicMock, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plc.upload_block.side_effect = lambda block_type, number: make_block(
        block_type, number, unaccounted=bytes(12)
    )
    assert capture_fixtures.main(["--host", "10.0.0.5", "-o", str(tmp_path), "DB10"]) == 0
    out = capsys.readouterr().out
    assert "trailing unknown 12)\n" in out
    assert "  note: 12 byte(s) between the declared sections and the footer" in out


def test_fake_mode_uploads_the_reference_blocks_from_the_fake_plc(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert capture_fixtures.main(["--fake", "-o", str(tmp_path)]) == 0
    produced = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    assert produced == {
        f"{block_type.value}{number}.mc7": image
        for (block_type, number), image in reference_blocks().items()
    }
    assert capsys.readouterr().out.count(" -> ") == 3


@pytest.mark.parametrize("argv", [[], ["--fake", "OB1"], ["--fake", "--host", "10.0.0.5"]])
def test_usage_errors_exit_with_code_2(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        capture_fixtures.main(argv)
    assert caught.value.code == 2


def test_default_output_directories_are_inside_the_fixture_tree() -> None:
    root = Path(__file__).parent / "fixtures" / "blocks"
    assert root == capture_fixtures.FIXTURE_ROOT
