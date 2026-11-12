"""The assembler pipeline exists as interfaces, and the package stays free of PLC code."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable

import pytest

import mc7asm
from mc7asm import (
    BlockType,
    Mc7AsmError,
    NotYetImplementedError,
    container,
    disasm,
    lexer,
    opcodes,
    parse_image,
)
from mc7asm import parser as stl_parser
from mc7asm.ir import BlockSource, Instruction, Network
from tests.support import make_block

MODULES: tuple[str, ...] = (
    "cli",
    "container",
    "disasm",
    "errors",
    "image",
    "ir",
    "lexer",
    "opcodes",
    "parser",
    "report",
    "validate",
)

BLOCK = BlockSource(
    BlockType.FC,
    1,
    (Network((Instruction("A", "I 0.0", line=1), Instruction("BE", line=2)), title="demo"),),
)


@pytest.mark.parametrize(
    ("call", "feature"),
    [
        (lambda: lexer.tokenize("A I 0.0"), "the STL lexer"),
        (lambda: stl_parser.parse_source("A I 0.0"), "the STL parser"),
        (lambda: opcodes.encode_instruction(Instruction("BE")), "MC7 instruction encoding"),
        (lambda: opcodes.decode_instruction(b"\x65\x00", 0), "MC7 instruction decoding"),
        (lambda: container.build_image(BLOCK, b"\x65\x00"), "building a block container"),
        (lambda: disasm.disassemble(parse_image(make_block())), "the MC7 disassembler"),
    ],
)
def test_pipeline_steps_say_that_they_are_not_implemented(
    call: Callable[[], object], feature: str
) -> None:
    with pytest.raises(NotYetImplementedError, match="is not implemented yet") as caught:
        call()
    assert caught.value.feature == feature
    assert str(caught.value).startswith(feature)
    assert isinstance(caught.value, Mc7AsmError)
    assert isinstance(caught.value, NotImplementedError)


def test_ir_is_plain_immutable_data() -> None:
    assert BLOCK.networks[0].instructions[0] == Instruction("A", "I 0.0", None, 1)
    assert BLOCK.networks[0].title == "demo"
    assert Instruction("BE") == Instruction("BE", operand=None, label=None, line=0)
    with pytest.raises(AttributeError):
        BLOCK.number = 2  # type: ignore[misc]
    assert lexer.Token(lexer.TokenKind.IDENTIFIER, "A", 1, 1).text == "A"


def test_every_module_is_importable_and_documented() -> None:
    import importlib

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
