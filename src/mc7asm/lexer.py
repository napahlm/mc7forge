"""Lexer: turns STL source text into tokens with exact locations.

The lexer is line oriented and knows nothing about mnemonics. It only decides
what kind of thing a piece of text is:

* a keyword of the block structure (``NETWORK``, ``BEGIN``, ...),
* an identifier (``A``, ``AN(``, ``I0.0``, ``DB1.DBX``),
* a number (``100``, ``-5``, ``0.0``, ``1.5``),
* a literal with a type prefix or in quotes (``W#16#1F``, ``B#(1, 2)``, ``'AB'``),
* a symbol (``=``, ``)``, ``;``, ``:``),
* the free text of a ``TITLE =`` line, or a ``//`` comment.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from mc7asm.errors import Mc7SyntaxError
from mc7asm.source import SourceLocation

KEYWORDS = frozenset(
    {
        "ORGANIZATION_BLOCK",
        "FUNCTION",
        "FUNCTION_BLOCK",
        "END_ORGANIZATION_BLOCK",
        "END_FUNCTION",
        "END_FUNCTION_BLOCK",
        "BEGIN",
        "NETWORK",
        "TITLE",
        "VOID",
    }
)
_SYMBOLS = ";:)="
_WORD_CHARACTERS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.#+-")


class TokenKind(Enum):
    """Lexical categories of STL source."""

    KEYWORD = "keyword"
    IDENTIFIER = "identifier"
    NUMBER = "number"
    LITERAL = "literal"
    SYMBOL = "symbol"
    TEXT = "text"
    COMMENT = "comment"
    NEWLINE = "newline"
    END = "end"


@dataclass(frozen=True, slots=True)
class Token:
    """One lexical unit.

    Attributes:
        kind: Lexical category.
        text: The source text of the token; for a comment the text after ``//``.
        location: Where the token starts.
    """

    kind: TokenKind
    text: str
    location: SourceLocation


def tokenize(source: str, file: str = "<source>") -> list[Token]:
    """Split STL source into tokens.

    Every source line ends with a :attr:`TokenKind.NEWLINE` token and the list
    ends with one :attr:`TokenKind.END` token.

    Raises:
        Mc7SyntaxError: For a character that cannot start a token, or a literal
            that is not closed on its line.
    """
    tokens: list[Token] = []
    lines = source.splitlines()
    for number, line in enumerate(lines, 1):
        _tokenize_line(line, number, file, tokens)
        tokens.append(Token(TokenKind.NEWLINE, "", SourceLocation(file, number, len(line) + 1)))
    tokens.append(Token(TokenKind.END, "", SourceLocation(file, len(lines) + 1, 1)))
    return tokens


def _tokenize_line(line: str, number: int, file: str, tokens: list[Token]) -> None:
    first_of_line = len(tokens)
    position = 0
    while position < len(line):
        character = line[position]
        location = SourceLocation(file, number, position + 1)
        if character in " \t":
            position += 1
        elif line.startswith("//", position):
            tokens.append(Token(TokenKind.COMMENT, line[position + 2 :].strip(), location))
            return
        elif character == "'":
            end = line.find("'", position + 1)
            if end < 0:
                raise Mc7SyntaxError(
                    "character constant is not closed",
                    location,
                    text=line[position:],
                    hint="end it with a second ' on the same line",
                )
            tokens.append(Token(TokenKind.LITERAL, line[position : end + 1], location))
            position = end + 1
        elif character in _SYMBOLS:
            tokens.append(Token(TokenKind.SYMBOL, character, location))
            position += 1
            if _is_title_line(tokens, first_of_line):
                _append_title_text(line, position, number, file, tokens)
                return
        elif character in _WORD_CHARACTERS:
            end = _word_end(line, position, location)
            text = line[position:end]
            tokens.append(Token(_classify(text), text, location))
            position = end
        else:
            raise Mc7SyntaxError(
                f"unexpected character {character!r}",
                location,
                text=character,
                hint="comments start with //",
            )


def _word_end(line: str, start: int, location: SourceLocation) -> int:
    """Return the index after the word starting at ``start``."""
    end = start
    while end < len(line) and (
        line[end] in _WORD_CHARACTERS or (line[end] == ":" and "#" in line[start:end])
    ):
        end += 1
    if end < len(line) and line[end] == "(":
        end += 1
        if line[start:end].upper() == "B#(":
            close = line.find(")", end)
            if close < 0:
                raise Mc7SyntaxError(
                    "byte list is not closed",
                    location,
                    text=line[start:],
                    hint="write it like B#(10, 20)",
                )
            end = close + 1
    return end


def _classify(text: str) -> TokenKind:
    if text.upper() in KEYWORDS:
        return TokenKind.KEYWORD
    if "#" in text:
        return TokenKind.LITERAL
    digits = text.lstrip("+-")
    if digits[:1].isdigit() or (digits[:1] == "." and digits[1:2].isdigit()):
        return TokenKind.NUMBER
    return TokenKind.IDENTIFIER


def _is_title_line(tokens: list[Token], first_of_line: int) -> bool:
    """Whether the line so far is exactly ``TITLE =``."""
    line = tokens[first_of_line:]
    return (
        len(line) == 2
        and line[0].kind is TokenKind.KEYWORD
        and line[0].text.upper() == "TITLE"
        and line[1].text == "="
    )


def _append_title_text(
    line: str, position: int, number: int, file: str, tokens: list[Token]
) -> None:
    rest = line[position:]
    start = position + len(rest) - len(rest.lstrip())
    tokens.append(Token(TokenKind.TEXT, rest.strip(), SourceLocation(file, number, start + 1)))
