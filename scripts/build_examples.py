"""Rebuild the expected block images of the examples in ``examples/expected``.

Every example except the ones listed in :data:`REFUSED` is built with the
fixed :data:`TIMESTAMP`, so the result is reproducible::

    uv run python scripts/build_examples.py          # rewrite the images
    uv run python scripts/build_examples.py --check  # exit 1 if one is stale

Sources whose name ends in ``_de`` are read with German mnemonics.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from mc7asm import (
    Mnemonics,
    build_block,
    compile_block,
    parse_file,
    parse_image,
    validate_generated_image,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = REPO_ROOT / "examples"
EXPECTED = EXAMPLES / "expected"
TIMESTAMP = datetime(2024, 1, 1)
REFUSED = frozenset({"nesting"})
"""Examples that parse but are refused by the code generator; they have no image."""


def sources() -> list[Path]:
    """Return the example sources that have an expected image, in name order."""
    return sorted(path for path in EXAMPLES.glob("*.awl") if path.stem not in REFUSED)


def mnemonics_of(source: Path) -> Mnemonics:
    """Return the spelling an example is written in, by its file name."""
    return Mnemonics.DE if source.stem.endswith("_de") else Mnemonics.EN


def build_example(source: Path) -> bytes:
    """Build one example with the fixed timestamp and validate the result."""
    compiled = compile_block(parse_file(source, mnemonics_of(source)))
    data = build_block(compiled, TIMESTAMP).image.to_bytes()
    findings = validate_generated_image(parse_image(data))
    if findings:
        raise SystemExit(f"{source}: {[finding.message for finding in findings]}")
    return data


def main(argv: Sequence[str] | None = None) -> int:
    """Rewrite the expected images, or with ``--check`` report stale ones."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments not in ([], ["--check"]):
        print("usage: build_examples.py [--check]", file=sys.stderr)
        return 2
    stale = []
    for source in sources():
        target = EXPECTED / f"{source.stem}.mc7"
        data = build_example(source)
        if arguments:
            if not target.is_file() or target.read_bytes() != data:
                stale.append(target.name)
        else:
            EXPECTED.mkdir(exist_ok=True)
            target.write_bytes(data)
    if stale:
        print(f"stale expected images: {', '.join(stale)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
