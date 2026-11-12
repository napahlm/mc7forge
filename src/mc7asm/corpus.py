"""The rz-libmc7 decoder test table as a typed corpus.

``unit/test_simatic.c`` of rz-libmc7 holds one table of test vectors: the bytes
of one MC7 instruction, the text the decoder must produce and the number of
bytes it must consume. That table is the opcode ground truth of this project.
The file is vendored verbatim under ``tests/fixtures/corpus`` and parsed here
directly, so there is exactly one copy of the data.

The parser is deliberately strict. Every line inside the ``tests[]`` array must
be one of four kinds: an active vector, a vector upstream disabled with
``// FIXME``, a section comment or the terminator. Anything else is an error
with its line number, so a vector can neither be skipped nor picked up by
accident.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from mc7asm.errors import CorpusFormatError

DECODE_BASE_ADDRESS = 0x80000000
"""Address the upstream test passes to the decoder; jump targets are relative to it."""

INVALID_TEXT = "invalid"
"""Expected text of a vector whose bytes the decoder must reject."""

_HEX_BYTES = r"0x[0-9a-fA-F]{2}(?:, 0x[0-9a-fA-F]{2})*"
_TEXT = r'"(?P<stl>[^"\\]*)"'
_ARRAY_START = "const s7_test_t tests[] = {"
_ARRAY_END = "};"
_TERMINATOR = "\t{ __LINE__, NULL, -1, 0, { 0x00 } },"
_ACTIVE = re.compile(
    rf"\t\{{ __LINE__, {_TEXT}, (?P<read>-?\d+), (?P<size>\d+), \{{ (?P<data>{_HEX_BYTES}) \}} \}},"
)
_DISABLED = re.compile(
    rf"\t// FIXME \{{__LINE__, {_TEXT}, +(?P<read>-?\d+), (?P<size>\d+), "
    rf"\{{(?P<data>{_HEX_BYTES})\}}\}},"
)
_COMMENT = re.compile(r"\t// (?!FIXME \{).*")


@dataclass(frozen=True, slots=True)
class CorpusVector:
    """One test vector.

    Attributes:
        line: Source line of the vector in the C file. It is what ``__LINE__``
            expands to, so it matches the line upstream reports on a failure.
        stl: Text the decoder must produce, or :data:`INVALID_TEXT`.
        read: Number of bytes the decoder must consume, or -1 for a rejection.
        size: Number of bytes handed to the decoder.
        data: The instruction bytes.
    """

    line: int
    stl: str
    read: int
    size: int
    data: bytes

    @property
    def is_invalid(self) -> bool:
        """Whether the decoder is expected to reject the bytes."""
        return self.read < 0

    @property
    def mnemonic(self) -> str:
        """The first token of the expected text, for example ``A`` or ``A(``."""
        return self.stl.split(" ", 1)[0]


@dataclass(frozen=True, slots=True)
class Corpus:
    """All vectors of the test table.

    Attributes:
        vectors: The active vectors, in file order.
        disabled: Vectors upstream commented out with ``// FIXME``. They are
            not verified by upstream and must not be used as ground truth.
    """

    vectors: tuple[CorpusVector, ...]
    disabled: tuple[CorpusVector, ...]

    def mnemonic_counts(self) -> Counter[str]:
        """Count the active, valid vectors per mnemonic."""
        return Counter(vector.mnemonic for vector in self.vectors if not vector.is_invalid)


def load_corpus(path: Path) -> Corpus:
    """Read and parse the vendored C file."""
    return parse_corpus(path.read_text(encoding="ascii"))


def parse_corpus(text: str) -> Corpus:
    """Parse the ``tests[]`` array of ``test_simatic.c``.

    Raises:
        CorpusFormatError: If the array is missing or any line inside it is
            not one of the four known kinds, or a vector is inconsistent.
    """
    lines = text.split("\n")
    try:
        start = lines.index(_ARRAY_START)
        end = lines.index(_ARRAY_END, start)
    except ValueError as exc:
        raise CorpusFormatError("cannot find the tests[] array") from exc
    if end - start < 2 or lines[end - 1] != _TERMINATOR:
        raise CorpusFormatError(f"line {end}: the array does not end with the NULL terminator")

    vectors: list[CorpusVector] = []
    disabled: list[CorpusVector] = []
    for index in range(start + 1, end - 1):
        line = lines[index]
        number = index + 1
        if match := _ACTIVE.fullmatch(line):
            vectors.append(_vector(number, match))
        elif match := _DISABLED.fullmatch(line):
            disabled.append(_vector(number, match))
        elif not _COMMENT.fullmatch(line):
            raise CorpusFormatError(f"line {number}: not a test vector or comment: {line!r}")
    return Corpus(tuple(vectors), tuple(disabled))


def _vector(number: int, match: re.Match[str]) -> CorpusVector:
    data = bytes(int(item, 16) for item in match["data"].split(", "))
    vector = CorpusVector(number, match["stl"], int(match["read"]), int(match["size"]), data)
    if vector.size != len(data):
        raise CorpusFormatError(
            f"line {number}: size {vector.size} does not match its {len(data)} data bytes"
        )
    if vector.is_invalid != (vector.stl == INVALID_TEXT) or vector.read > vector.size:
        raise CorpusFormatError(f"line {number}: inconsistent read length {vector.read}")
    return vector
