"""Capture reference blocks for the test corpus in ``tests/fixtures/blocks``.

The script is read-only towards the PLC: it connects, lists blocks and uploads
them. It never writes, downloads or changes the operating state.

Real blocks, saved to ``tests/fixtures/blocks/real``::

    uv run python scripts/capture_fixtures.py --host 192.168.0.10
    uv run python scripts/capture_fixtures.py --host 192.168.0.10 OB1 FC5 DB10

Without block names it takes OB1, the lowest-numbered FC and the
lowest-numbered DB.

Synthetic stand-ins, saved to ``tests/fixtures/blocks/fake``::

    uv run python scripts/capture_fixtures.py --fake

This runs the same upload path against the fake PLC of the test suite, so the
default test run needs no hardware.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol

from mc7 import BlockType, Mc7Error, PlcClient, block_filename, parse_block_spec
from mc7asm import Mc7AsmError, parse_image, validate_image

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "blocks"
DEFAULT_TYPES = (BlockType.OB, BlockType.FC, BlockType.DB)

BlockSpec = tuple[BlockType, int]


class BlockReader(Protocol):
    """The read-only part of :class:`mc7.PlcClient` this script is allowed to use."""

    def list_blocks(self, block_type: BlockType) -> list[int]:
        """Return the numbers of the blocks of one type."""

    def upload_block(self, block_type: BlockType, number: int) -> bytes:
        """Return the complete image of one block."""


class CaptureError(Mc7Error):
    """The capture cannot proceed for a reason that is not a PLC failure."""


def main(argv: Sequence[str] | None = None) -> int:
    """Run the capture and return the process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.fake and args.blocks:
        parser.error("block names cannot be combined with --fake")
    try:
        if args.fake:
            output = args.output or FIXTURE_ROOT / "fake"
            with fake_reader() as (reader, specs):
                capture(reader, specs, output, overwrite=True)
        else:
            output = args.output or FIXTURE_ROOT / "real"
            requested = [parse_block_spec(text) for text in args.blocks]
            with PlcClient(args.host, rack=args.rack, slot=args.slot, port=args.port) as plc:
                specs = requested or select_default_blocks(plc)
                capture(plc, specs, output, overwrite=args.force)
    except (Mc7Error, Mc7AsmError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        description="Upload reference blocks into the test fixture directory (read-only)."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--fake", action="store_true", help="build the synthetic stand-ins")
    source.add_argument("--host", help="IP address of the PLC to read real blocks from")
    parser.add_argument("--rack", type=int, default=0, help="CPU rack (%(default)s)")
    parser.add_argument("--slot", type=int, default=2, help="CPU slot (%(default)s)")
    parser.add_argument("--port", type=int, default=102, help="TCP port (%(default)s)")
    parser.add_argument(
        "-o", "--output", type=Path, help="target directory (default: tests/fixtures/blocks/...)"
    )
    parser.add_argument(
        "--force", action="store_true", help="overwrite existing fixtures of a real capture"
    )
    parser.add_argument(
        "blocks",
        nargs="*",
        metavar="BLOCK",
        help="blocks to capture, for example OB1 FC5 DB10 (default: OB1, first FC, first DB)",
    )
    return parser


def select_default_blocks(reader: BlockReader) -> list[BlockSpec]:
    """Pick OB1 (or the first OB), the lowest-numbered FC and the lowest-numbered DB."""
    specs: list[BlockSpec] = []
    for block_type in DEFAULT_TYPES:
        numbers = sorted(reader.list_blocks(block_type))
        if not numbers:
            print(f"no {block_type.value} present, skipped")
            continue
        preferred = 1 if block_type is BlockType.OB and 1 in numbers else numbers[0]
        specs.append((block_type, preferred))
    if not specs:
        raise CaptureError("the PLC reports no OB, FC or DB to capture")
    return specs


def capture(
    reader: BlockReader, specs: Sequence[BlockSpec], directory: Path, *, overwrite: bool
) -> list[Path]:
    """Upload each block and save it; nothing is uploaded if a target file is in the way.

    Returns:
        The paths written, in the order of ``specs``.

    Raises:
        CaptureError: If a fixture exists and ``overwrite`` is false.
    """
    targets = [directory / block_filename(block_type, number) for block_type, number in specs]
    if not overwrite:
        existing = [str(path) for path in targets if path.exists()]
        if existing:
            raise CaptureError(f"{', '.join(existing)} already exist(s); pass --force to overwrite")
    directory.mkdir(parents=True, exist_ok=True)
    for (block_type, number), path in zip(specs, targets, strict=True):
        data = reader.upload_block(block_type, number)
        path.write_bytes(data)
        print(describe(path, data))
    return targets


def describe(path: Path, data: bytes) -> str:
    """Summarise the layout of a captured block, including anything unexpected."""
    image = parse_image(data)
    header = image.header
    lines = [
        f"{header.name} -> {_display(path)} ({len(data)} bytes: payload {len(image.payload)}, "
        f"interface {len(image.interface)}, segment table {len(image.segment_table)}, "
        f"trailing unknown {len(image.trailing_unknown)})"
    ]
    lines += [
        f"  {finding.severity.value}: {finding.message} [{finding.code}]"
        for finding in validate_image(image)
    ]
    return "\n".join(lines)


def _display(path: Path) -> str:
    """Show a path relative to the working directory when it lies below it."""
    try:
        return str(path.resolve().relative_to(Path.cwd()))
    except ValueError:
        return str(path)


@contextmanager
def fake_reader() -> Iterator[tuple[BlockReader, list[BlockSpec]]]:
    """Serve the synthetic reference blocks from the fake PLC of the test suite."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from tests.support import FakePlc, reference_blocks

    blocks = reference_blocks()
    with FakePlc() as fake:
        for (block_type, number), image in blocks.items():
            fake.add(block_type, number, image)
        with PlcClient("127.0.0.1", port=fake.port) as plc:
            yield plc, list(blocks)
    if fake.failures:
        raise CaptureError(f"the fake PLC saw protocol errors: {fake.failures}")


if __name__ == "__main__":
    sys.exit(main())
