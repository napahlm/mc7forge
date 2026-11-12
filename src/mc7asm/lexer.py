"""Lexer: turns STL source text into tokens.

Interface only in this stage; :func:`tokenize` raises
:class:`~mc7asm.errors.NotYetImplementedError`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from mc7asm.errors import NotYetImplementedError


class TokenKind(Enum):
    """Lexical categories of STL source."""

    IDENTIFIER = "identifier"
    NUMBER = "number"
    PUNCTUATION = "punctuation"
    COMMENT = "comment"
    NEWLINE = "newline"
    END = "end"


@dataclass(frozen=True, slots=True)
class Token:
    """One lexical unit with its position.

    Attributes:
        kind: Lexical category.
        text: The exact source text of the token.
        line: 1-based source line.
        column: 1-based column of the first character.
    """

    kind: TokenKind
    text: str
    line: int
    column: int


def tokenize(source: str) -> list[Token]:
    """Split STL source into tokens, ending with one :attr:`TokenKind.END` token."""
    raise NotYetImplementedError("the STL lexer")
