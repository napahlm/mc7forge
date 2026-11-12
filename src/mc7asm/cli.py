"""Command line interface of the assembler toolchain.

Exit codes: 0 success, 1 the operation failed, 2 invalid command line.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import TextIO

from mc7asm import __version__
from mc7asm.codegen import compile_block
from mc7asm.container import build_block
from mc7asm.disasm import disassemble
from mc7asm.errors import Mc7AsmError
from mc7asm.image import BlockImage, parse_image
from mc7asm.lexer import tokenize
from mc7asm.opcodes import Mnemonics
from mc7asm.parser import parse_file
from mc7asm.printer import render_tokens, render_tree
from mc7asm.report import render_disassembly, render_dump
from mc7asm.validate import Finding, validate_generated_image, validate_image

EXIT_OK = 0
EXIT_FAILURE = 1

Handler = Callable[[argparse.Namespace], int]


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return the process exit code."""
    args = build_parser().parse_args(argv)
    handler: Handler = args.handler
    try:
        return handler(args)
    except (Mc7AsmError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_FAILURE


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with all sub-commands."""
    parser = argparse.ArgumentParser(
        prog="mc7asm",
        description=(
            "Inspect and disassemble S7-300 MC7 block images, compile and build blocks from STL. "
            "Works on files only, never on a PLC."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(
        title="commands", dest="command", required=True, metavar="COMMAND"
    )
    summary = "Print every header and footer field of a block file and a hex dump of its sections."
    dump = commands.add_parser("dump", help=summary, description=summary)
    dump.add_argument("file", type=Path, help="block image, for example one saved by 'mc7 upload'")
    dump.set_defaults(handler=_cmd_dump)

    summary = "Disassemble the MC7 code of an OB, FC or FB file into STL statements."
    disasm = commands.add_parser("disasm", help=summary, description=summary)
    disasm.add_argument(
        "file", type=Path, help="block image, for example one saved by 'mc7 upload'"
    )
    _add_mnemonics_option(disasm)
    disasm.set_defaults(handler=_cmd_disasm)

    summary = "Parse an STL source file and print its intermediate representation."
    parse = commands.add_parser("parse", help=summary, description=summary)
    parse.add_argument("file", type=Path, help="STL source file with one block")
    parse.add_argument("--show-tokens", action="store_true", help="print the tokens instead")
    _add_mnemonics_option(parse)
    parse.set_defaults(handler=_cmd_parse)

    summary = "Compile an STL source file to the raw MC7 code of its block."
    compile_ = commands.add_parser("compile", help=summary, description=summary)
    compile_.add_argument("file", type=Path, help="STL source file with one block")
    compile_.add_argument(
        "-o",
        "--output",
        type=Path,
        help="file for the MC7 body (default: the source name with the suffix .body)",
    )
    _add_mnemonics_option(compile_)
    compile_.set_defaults(handler=_cmd_compile)

    summary = (
        "Compile an STL source file and wrap the code into a complete block image. "
        "Nothing is written unless the image passes validation."
    )
    build = commands.add_parser("build", help=summary, description=summary)
    build.add_argument("file", type=Path, help="STL source file with one block")
    build.add_argument(
        "-o",
        "--output",
        type=Path,
        help="file for the block image (default: the block name with .mc7 next to the source)",
    )
    build.add_argument(
        "--timestamp",
        type=datetime.fromisoformat,
        metavar="ISO",
        help="time stored in the block header, for example 2024-05-17T08:30:00 (default: now)",
    )
    _add_mnemonics_option(build)
    build.set_defaults(handler=_cmd_build)
    return parser


def _add_mnemonics_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--mnemonics",
        choices=[item.value for item in Mnemonics],
        default=Mnemonics.EN.value,
        help="en: international (A I 0.0), de: German (U E 0.0); default: %(default)s",
    )


def _load(path: Path) -> BlockImage:
    try:
        return parse_image(path.read_bytes())
    except Mc7AsmError as exc:
        raise Mc7AsmError(f"{path}: {exc}") from exc


def _cmd_dump(args: argparse.Namespace) -> int:
    image = _load(args.file)
    sys.stdout.write(render_dump(str(args.file), image, validate_image(image)))
    return EXIT_OK


def _cmd_disasm(args: argparse.Namespace) -> int:
    image = _load(args.file)
    try:
        disassembly = disassemble(image, Mnemonics(args.mnemonics))
    except Mc7AsmError as exc:
        raise Mc7AsmError(f"{args.file}: {exc}") from exc
    sys.stdout.write(render_disassembly(str(args.file), disassembly))
    return EXIT_OK


def _cmd_parse(args: argparse.Namespace) -> int:
    path: Path = args.file
    if args.show_tokens:
        sys.stdout.write(render_tokens(tokenize(path.read_text(encoding="utf-8"), str(path))))
    else:
        sys.stdout.write(render_tree(parse_file(path, Mnemonics(args.mnemonics))))
    return EXIT_OK


def _cmd_compile(args: argparse.Namespace) -> int:
    path: Path = args.file
    compiled = compile_block(parse_file(path, Mnemonics(args.mnemonics)))
    output: Path = args.output or path.with_suffix(".body")
    output.write_bytes(compiled.body)
    count = len(compiled.networks)
    print(
        f"{path}: {compiled.block.name}, {count} network{'s' if count != 1 else ''}, "
        f"{compiled.size} bytes of MC7 code -> {output}"
    )
    for network in compiled.networks:
        title = f' "{network.network.title}"' if network.network.title else ""
        print(
            f"  network {network.number}{title}: {len(network.instructions)} instructions, "
            f"{network.size} bytes at offset 0x{network.offset:04x}"
        )
    return EXIT_OK


def _cmd_build(args: argparse.Namespace) -> int:
    path: Path = args.file
    compiled = compile_block(parse_file(path, Mnemonics(args.mnemonics)))
    built = build_block(compiled, args.timestamp or datetime.now())
    data = built.image.to_bytes()
    # Validate what would be written, not the model it was written from.
    image = parse_image(data)
    findings = validate_generated_image(image)
    if findings:
        _print_findings(findings, sys.stderr)
        raise Mc7AsmError(f"{path}: the built image failed validation, nothing was written")
    header = image.header
    output: Path = args.output or path.with_name(f"{header.name}.mc7")
    output.write_bytes(data)
    closing = "BE appended" if built.block_end_appended else "BE from the source"
    print(f"{path}: {header.name}, {len(data)} bytes -> {output}")
    print(
        f"  code {header.mc7_length} bytes ({closing}), interface {header.interface_length}, "
        f"segment table {header.segment_table_length}, local data {header.local_data_length}"
    )
    _print_findings(built.notes, sys.stdout)
    return EXIT_OK


def _print_findings(findings: Sequence[Finding], stream: TextIO) -> None:
    for finding in findings:
        print(f"  {finding.severity.value}: {finding.message} [{finding.code}]", file=stream)
