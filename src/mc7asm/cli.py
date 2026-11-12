"""Command line interface of the assembler toolchain.

Exit codes: 0 success, 1 the operation failed, 2 invalid command line.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from mc7asm import __version__
from mc7asm.errors import Mc7AsmError
from mc7asm.image import parse_image
from mc7asm.report import render_dump
from mc7asm.validate import validate_image

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
        description="Inspect S7-300 MC7 block images. Works on files only, never on a PLC.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(
        title="commands", dest="command", required=True, metavar="COMMAND"
    )
    summary = "Print every header and footer field of a block file and a hex dump of its sections."
    dump = commands.add_parser("dump", help=summary, description=summary)
    dump.add_argument("file", type=Path, help="block image, for example one saved by 'mc7 upload'")
    dump.set_defaults(handler=_cmd_dump)
    return parser


def _cmd_dump(args: argparse.Namespace) -> int:
    path: Path = args.file
    try:
        image = parse_image(path.read_bytes())
    except Mc7AsmError as exc:
        raise Mc7AsmError(f"{path}: {exc}") from exc
    sys.stdout.write(render_dump(str(path), image, validate_image(image)))
    return EXIT_OK
