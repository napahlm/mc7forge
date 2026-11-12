"""Optional cross-check against rz-libmc7, the decoder the opcode corpus comes from.

When Rizin's ``rz-asm`` with the ``mc7`` plugin is installed, the code of every
example is disassembled with it as well and compared with our own listing.
Without it the comparison is skipped; the plumbing is still tested with a
stand-in executable.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from mc7asm import parse_image
from mc7asm.disasm import decode_code
from scripts import build_examples

SOURCES = build_examples.sources()


def has_mc7_plugin(executable: str) -> bool:
    """Whether this ``rz-asm`` lists the mc7 architecture."""
    try:
        listing = subprocess.run(
            [executable, "-L"], capture_output=True, text=True, timeout=30, check=False
        )
    except OSError:
        return False
    return listing.returncode == 0 and any(
        "mc7" in line.split() for line in listing.stdout.splitlines()
    )


def rizin_disassemble(executable: str, code: bytes) -> list[str]:
    """Disassemble MC7 code with ``rz-asm`` and return one statement per instruction."""
    result = subprocess.run(
        [executable, "-a", "mc7", "-d", code.hex()],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def our_statements(code: bytes) -> list[str]:
    return [getattr(entry, "text", "<unknown opcode>") for entry in decode_code(code)]


def example_code(source: Path) -> bytes:
    return parse_image((build_examples.EXPECTED / f"{source.stem}.mc7").read_bytes()).payload


RZ_ASM = shutil.which("rz-asm")
RIZIN_AVAILABLE = RZ_ASM is not None and has_mc7_plugin(RZ_ASM)


@pytest.mark.skipif(
    not RIZIN_AVAILABLE, reason="rz-asm with the mc7 plugin (rz-libmc7) is not installed"
)
@pytest.mark.parametrize("source", SOURCES, ids=lambda source: source.stem)
def test_rizin_disassembles_our_code_the_same_way(source: Path) -> None:
    assert RZ_ASM is not None
    code = example_code(source)
    assert rizin_disassemble(RZ_ASM, code) == our_statements(code)


def test_missing_rizin_is_detected_without_error(tmp_path: Path) -> None:
    assert has_mc7_plugin(str(tmp_path / "no-such-rz-asm")) is False
    assert RIZIN_AVAILABLE is (RZ_ASM is not None and has_mc7_plugin(RZ_ASM))


@pytest.mark.skipif(sys.platform == "win32", reason="the stand-in is a POSIX script")
def test_the_cross_check_plumbing_with_a_stand_in(tmp_path: Path) -> None:
    """A fake ``rz-asm`` that answers with our own decoder exercises detection and parsing."""
    stand_in = tmp_path / "rz-asm"
    stand_in.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        "from mc7asm.disasm import decode_code\n"
        "if sys.argv[1:] == ['-L']:\n"
        "    print('_dAe  8 16 32 64  x86   BSD  Capstone X86 disassembler')\n"
        "    print('_dA_  32          mc7   LGPL3  Simatic S7 disassembler')\n"
        "elif sys.argv[1:4] == ['-a', 'mc7', '-d']:\n"
        "    for entry in decode_code(bytes.fromhex(sys.argv[4])):\n"
        "        print(entry.text)\n"
        "        print()\n"
        "else:\n"
        "    sys.exit(2)\n"
    )
    stand_in.chmod(0o755)
    assert has_mc7_plugin(str(stand_in))
    for source in SOURCES:
        code = example_code(source)
        assert rizin_disassemble(str(stand_in), code) == our_statements(code)

    without_plugin = tmp_path / "rz-asm-plain"
    without_plugin.write_text(f"#!{sys.executable}\nprint('_dAe  8 16 32 64  x86   BSD  x86')\n")
    without_plugin.chmod(0o755)
    assert not has_mc7_plugin(str(without_plugin))
