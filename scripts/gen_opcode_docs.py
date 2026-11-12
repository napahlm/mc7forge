"""Regenerate the opcode table inside ``docs/opcodes.md`` from the table and the corpus.

The hand-written parts of the document stay untouched; only the block between
the two marker comments is replaced::

    uv run python scripts/gen_opcode_docs.py          # rewrite the document
    uv run python scripts/gen_opcode_docs.py --check  # exit 1 if it is stale
"""

from __future__ import annotations

import sys
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

from mc7asm.corpus import load_corpus
from mc7asm.disasm import decode_instruction
from mc7asm.opcodes import OPCODE_TABLE

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = REPO_ROOT / "docs" / "opcodes.md"
CORPUS_FILE = REPO_ROOT / "tests" / "fixtures" / "corpus" / "test_simatic.c"
BEGIN = "<!-- BEGIN GENERATED OPCODE TABLE -->"
END = "<!-- END GENERATED OPCODE TABLE -->"

_COLUMNS = (
    "Bytes",
    "Mask",
    "Mnemonic",
    "Area",
    "Operand",
    "Length",
    "Scope",
    "Corpus vectors",
    "C# decoder",
    "Status",
    "Note",
)


def table_markdown() -> str:
    """Render one table row per opcode row, with its corpus evidence."""
    lines_by_row: dict[str, list[int]] = defaultdict(list)
    for vector in load_corpus(CORPUS_FILE).vectors:
        decoded = decode_instruction(vector.data)
        if decoded is not None:
            lines_by_row[decoded.row.key].append(vector.line)
    rows = ["| " + " | ".join(_COLUMNS) + " |", "|" + " --- |" * len(_COLUMNS)]
    for row in OPCODE_TABLE:
        lines = lines_by_row[row.key]
        evidence = f"{len(lines)}, first at line {lines[0]}" if lines else "none"
        cells = (
            f"`{row.opcode.hex(' ')}`",
            f"`{row.mask.hex(' ')}`",
            f"`{row.mnemonic}`",
            f"`{row.area}`" if row.area else "",
            row.operand.value,
            str(row.length),
            row.scope.value,
            evidence,
            row.source.removeprefix("MC7toAWL.cs "),
            row.status.value,
            row.note,
        )
        rows.append("| " + " | ".join(cells) + " |")
    return "\n".join(rows)


def render(document: str) -> str:
    """Return ``document`` with the generated block replaced."""
    head, _, rest = document.partition(BEGIN)
    _, _, tail = rest.partition(END)
    if not rest or END not in rest:
        raise SystemExit(f"{DOCUMENT}: marker comments not found")
    return f"{head}{BEGIN}\n\n{table_markdown()}\n\n{END}{tail}"


def main(argv: Sequence[str] | None = None) -> int:
    """Rewrite the document, or with ``--check`` only report whether it is current."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    current = DOCUMENT.read_text(encoding="utf-8")
    updated = render(current)
    if arguments == ["--check"]:
        if updated != current:
            print(f"{DOCUMENT} is stale; run scripts/gen_opcode_docs.py", file=sys.stderr)
            return 1
        return 0
    if arguments:
        print("usage: gen_opcode_docs.py [--check]", file=sys.stderr)
        return 2
    DOCUMENT.write_text(updated, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
