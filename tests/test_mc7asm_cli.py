"""Tests of the ``mc7asm`` command line."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import mc7.blocks
from mc7asm import cli
from tests.support import make_block

FIXTURES = Path(__file__).parent / "fixtures" / "blocks"
OB1 = FIXTURES / "fake" / "OB1.mc7"

OB1_DUMP = """\
{path}: OB1, 111 bytes

Header (offset 0x0000, 36 bytes)
  off  field                  raw                decoded
    0  signature              70 70              pp
    2  block version          01                 1
    3  attributes             01                 LINKED
    4  language               01                 STL
    5  block type             08                 OB
    6  block number           00 01              1
    8  block length           00 00 00 6f        111
   12  password               00 00 00 00        not set
   16  last modified          00 00 ea 60 00 01  1984-01-02 00:01:00.000
   22  last interface change  00 00 00 00 00 00  1984-01-01 00:00:00.000
   28  interface length       00 1b              27
   30  segment table length   00 06              6
   32  local data length      00 14              20
   34  MC7 code length        00 06              6

Sections
  offset  size  section
  0x0000    36  Header
  0x0024     6  MC7 code
  0x002a    27  Interface
  0x0045     6  Segment table
  0x004b     0  Trailing unknown
  0x004b    36  Footer

MC7 code (offset 0x0024, 6 bytes)
  0024  60 0d 60 09 65 00                                 |`.`.e.|

Interface (offset 0x002a, 27 bytes)
  002a  01 00 00 14 00 00 00 40  41 42 43 44 45 46 47 48  |.......@ABCDEFGH|
  003a  49 4a 4b 4c 4d 4e 4f 50  51 52 53                 |IJKLMNOPQRS|
  sub-header: kind 0x01, number 0, declarations 20 bytes, start values 0 bytes, 0 byte(s) after them

Segment table (offset 0x0045, 6 bytes)
  0045  01 00 04 00 00 00                                 |......|

Trailing unknown (offset 0x004b, 0 bytes)
  (empty)

Footer (offset 0x004b, 36 bytes)
  off  field     raw                      decoded
   +0  author    41 55 54 48 4f 52 20 20  'AUTHOR'
   +8  family    46 41 4d 49 4c 59 20 20  'FAMILY'
  +16  name      4e 41 4d 45 20 20 20 20  'NAME'
  +24  version   01                       0.1
  +25  unknown   00
  +26  checksum  ab cd                    0xABCD
  +28  unknown   00 00 00 00 00 00 00 00

Findings
  none
"""


def test_dump_of_a_committed_fixture(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["dump", str(OB1)]) == 0
    captured = capsys.readouterr()
    assert captured.out == OB1_DUMP.format(path=OB1)
    assert captured.err == ""


def test_dump_lines_never_end_in_whitespace(capsys: pytest.CaptureFixture[str]) -> None:
    for path in sorted(FIXTURES.rglob("*.mc7")):
        assert cli.main(["dump", str(path)]) == 0
        lines = capsys.readouterr().out.splitlines()
        assert [line for line in lines if line != line.rstrip()] == []


def test_dump_of_a_data_block_names_the_body_data(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["dump", str(FIXTURES / "fake" / "DB1.mc7")]) == 0
    out = capsys.readouterr().out
    assert "   34  Data length            00 10              16\n" in out
    assert "  0x0024    16  Data\n" in out
    assert "Data (offset 0x0024, 16 bytes)\n" in out
    assert "    4  language               05                 DB\n" in out
    assert "MC7 code" not in out


def test_dump_shows_unaccounted_bytes_and_findings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "FB300.mc7"
    raw = bytearray(
        make_block(mc7.blocks.BlockType.FB, 300, mc7=bytes(4), unaccounted=bytes(range(65, 85)))
    )
    raw[3], raw[4], raw[12:16] = 0xC9, 7, b"\x00\x00\x00\x01"
    path.write_bytes(raw)
    assert cli.main(["dump", str(path)]) == 0
    out = capsys.readouterr().out
    assert f"{path}: FB300, {len(raw)} bytes\n" in out
    attributes = "LINKED | KNOW_HOW_PROTECTED | F_BLOCK | 0x80"
    assert f"    3  attributes             c9                 {attributes}\n" in out
    assert "    4  language               07                 7\n" in out
    assert "   12  password               00 00 00 01        set\n" in out
    assert (
        "Trailing unknown (offset 0x0035, 20 bytes)\n"
        "  0035  41 42 43 44 45 46 47 48  49 4a 4b 4c 4d 4e 4f 50  |ABCDEFGHIJKLMNOP|\n"
        "  0045  51 52 53 54                                       |QRST|\n"
    ) in out
    assert out.endswith(
        "Findings\n"
        "  note: 20 byte(s) between the declared sections and the footer are not accounted "
        "for by any header length field [trailing-unknown]\n"
        "  note: language code 7 is not one the references agree on [unknown-language]\n"
        "  note: attribute bits 0x80 are not documented [unknown-attribute-bits]\n"
    )


def test_dump_of_an_inconsistent_image_still_prints_everything(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    raw = bytearray(OB1.read_bytes())
    raw[28:30] = b"\x40\x00"
    path = tmp_path / "broken.mc7"
    path.write_bytes(raw)
    assert cli.main(["dump", str(path)]) == 0
    out = capsys.readouterr().out
    assert "Interface (offset 0x002a, 0 bytes)\n  (empty)\n" in out
    assert "Trailing unknown (offset 0x002a, 33 bytes)\n" in out
    assert "  error: declared sections need 16396 bytes" in out
    assert out.rstrip().endswith("[sections-overrun]")


@pytest.mark.parametrize(
    ("content", "fragment"),
    [
        (b"PK" + bytes(100), "signature is 50 4b, expected 70 70"),
        (b"pp" + bytes(10), "needs at least 72 bytes"),
        (b"", "needs at least 72 bytes"),
    ],
)
def test_dump_rejects_files_that_are_not_blocks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], content: bytes, fragment: str
) -> None:
    path = tmp_path / "thing.bin"
    path.write_bytes(content)
    assert cli.main(["dump", str(path)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith(f"error: {path}: ")
    assert fragment in captured.err


def test_dump_of_a_missing_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["dump", str(tmp_path / "nope.mc7")]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("error: ")
    assert "nope.mc7" in captured.err


@pytest.mark.parametrize("argv", [[], ["dump"], ["bogus"], ["dump", "a", "b"]])
def test_usage_errors_exit_with_code_2(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        cli.main(argv)
    assert caught.value.code == 2


def test_module_entry_point_runs_as_a_subprocess() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "mc7asm", "dump", str(OB1)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert (result.returncode, result.stderr) == (0, "")
    assert result.stdout == OB1_DUMP.format(path=OB1)
