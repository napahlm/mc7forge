"""Package-level guarantees: what is still an interface, and no PLC code in mc7asm."""

from __future__ import annotations

import importlib
import subprocess
import sys

import pytest

import mc7asm
from mc7asm import BlockType, Mc7AsmError, NotYetImplementedError, container, ir

MODULES: tuple[str, ...] = (
    "cli",
    "codegen",
    "container",
    "corpus",
    "disasm",
    "errors",
    "image",
    "ir",
    "lexer",
    "notation",
    "opcodes",
    "parser",
    "printer",
    "report",
    "source",
    "validate",
)

BLOCK = ir.Block(
    BlockType.FC,
    1,
    (ir.Network((ir.BitLogic(ir.BitOp.A, ir.BitAddress(ir.Area.I, 0, 0)), ir.BlockEnd())),),
)


def test_building_a_block_container_is_still_an_interface() -> None:
    with pytest.raises(NotYetImplementedError, match="is not implemented yet") as caught:
        container.build_image(BLOCK, b"\xc0\x00\x65\x00")
    assert caught.value.feature == "building a block container"
    assert str(caught.value).startswith("building a block container")
    assert isinstance(caught.value, Mc7AsmError)
    assert isinstance(caught.value, NotImplementedError)


def test_ir_is_plain_immutable_data() -> None:
    instruction = BLOCK.networks[0].instructions[0]
    assert instruction == ir.BitLogic(ir.BitOp.A, ir.BitAddress(ir.Area.I, 0, 0))
    assert (instruction.mnemonic, BLOCK.networks[0].instructions[1].mnemonic) == ("A", "BE")
    assert BLOCK.name == "FC1"
    with pytest.raises(AttributeError):
        BLOCK.number = 2  # type: ignore[misc]
    with pytest.raises(AttributeError):
        instruction.op = ir.BitOp.O  # type: ignore[misc]
    with pytest.raises(NotImplementedError):
        _ = ir.Instruction().mnemonic


def test_every_module_is_importable_and_documented() -> None:
    for name in MODULES:
        module = importlib.import_module(f"mc7asm.{name}")
        assert module.__doc__, name
    assert mc7asm.__version__


def test_importing_the_package_never_loads_the_plc_communication_layer() -> None:
    imports = "; ".join(f"import mc7asm.{name}" for name in MODULES)
    check = (
        f"{imports}; import sys; "
        "loaded = sorted(m for m in sys.modules if m.split('.')[0] in ('mc7', 'snap7', 'socket')); "
        "print(loaded); sys.exit(1 if loaded else 0)"
    )
    result = subprocess.run(
        [sys.executable, "-c", check], capture_output=True, text=True, timeout=30, check=False
    )
    assert (result.returncode, result.stdout.strip()) == (0, "[]"), result.stderr
