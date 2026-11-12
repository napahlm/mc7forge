"""The STL lexer: token kinds, exact locations and lexical errors."""

from __future__ import annotations

from pathlib import Path

import pytest

from mc7asm import Mc7AsmError, Mc7SyntaxError, SourceLocation, cli
from mc7asm.lexer import Token, TokenKind, tokenize

REPOSITORY = Path(__file__).parent.parent
GOLDEN = REPOSITORY / "tests" / "fixtures" / "golden"


def kinds_and_texts(source: str) -> list[tuple[str, str]]:
    return [
        (token.kind.value, token.text)
        for token in tokenize(source)
        if token.kind not in (TokenKind.NEWLINE, TokenKind.END)
    ]


def test_statement_tokens_carry_exact_locations() -> None:
    tokens = tokenize("      A     I 0.0;   // start", "x.awl")
    assert tokens == [
        Token(TokenKind.IDENTIFIER, "A", SourceLocation("x.awl", 1, 7)),
        Token(TokenKind.IDENTIFIER, "I", SourceLocation("x.awl", 1, 13)),
        Token(TokenKind.NUMBER, "0.0", SourceLocation("x.awl", 1, 15)),
        Token(TokenKind.SYMBOL, ";", SourceLocation("x.awl", 1, 18)),
        Token(TokenKind.COMMENT, "start", SourceLocation("x.awl", 1, 22)),
        Token(TokenKind.NEWLINE, "", SourceLocation("x.awl", 1, 30)),
        Token(TokenKind.END, "", SourceLocation("x.awl", 2, 1)),
    ]
    assert str(tokens[1].location) == "x.awl:1:13"


def test_lines_and_columns_count_from_one_and_tabs_are_one_column() -> None:
    tokens = tokenize("\n\tBE\n")
    assert [(t.kind, t.location.line, t.location.column) for t in tokens] == [
        (TokenKind.NEWLINE, 1, 1),
        (TokenKind.IDENTIFIER, 2, 2),
        (TokenKind.NEWLINE, 2, 4),
        (TokenKind.END, 3, 1),
    ]
    assert tokenize("")[0].kind is TokenKind.END


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("NETWORK", [("keyword", "NETWORK")]),
        ("network", [("keyword", "network")]),
        (
            "FUNCTION FC 1 : VOID",
            [
                ("keyword", "FUNCTION"),
                ("identifier", "FC"),
                ("number", "1"),
                ("symbol", ":"),
                ("keyword", "VOID"),
            ],
        ),
        ("A I0.0", [("identifier", "A"), ("identifier", "I0.0")]),
        ("A DB1.DBX0.0", [("identifier", "A"), ("identifier", "DB1.DBX0.0")]),
        ("A(", [("identifier", "A(")]),
        (")", [("symbol", ")")]),
        ("= Q 0.0", [("symbol", "="), ("identifier", "Q"), ("number", "0.0")]),
        ("L -28108", [("identifier", "L"), ("number", "-28108")]),
        ("L 1.5e-3", [("identifier", "L"), ("number", "1.5e-3")]),
        ("L .5", [("identifier", "L"), ("number", ".5")]),
        ("L L#-5", [("identifier", "L"), ("literal", "L#-5")]),
        ("L W#16#1F", [("identifier", "L"), ("literal", "W#16#1F")]),
        ("L TOD#1:10:3.300", [("identifier", "L"), ("literal", "TOD#1:10:3.300")]),
        ("L D#2002-10-5", [("identifier", "L"), ("literal", "D#2002-10-5")]),
        ("L B#(10, 20)", [("identifier", "L"), ("literal", "B#(10, 20)")]),
        ("L 'A B'", [("identifier", "L"), ("literal", "'A B'")]),
        ("L '//'", [("identifier", "L"), ("literal", "'//'")]),
        ("L TRUE", [("identifier", "L"), ("identifier", "TRUE")]),
        ("BE;//done", [("identifier", "BE"), ("symbol", ";"), ("comment", "done")]),
    ],
)
def test_token_kinds(source: str, expected: list[tuple[str, str]]) -> None:
    assert kinds_and_texts(source) == expected


def test_title_takes_the_rest_of_the_line_as_text() -> None:
    assert kinds_and_texts("TITLE = Latch // not a comment; = A(") == [
        ("keyword", "TITLE"),
        ("symbol", "="),
        ("text", "Latch // not a comment; = A("),
    ]
    assert kinds_and_texts("TITLE =") == [("keyword", "TITLE"), ("symbol", "="), ("text", "")]
    title = tokenize("TITLE =   Lamp  ")[2]
    assert (title.text, title.location.column) == ("Lamp", 11)
    assert kinds_and_texts("  = Q 0.0")[0] == ("symbol", "=")


@pytest.mark.parametrize(
    ("source", "column", "message", "text"),
    [
        ("  L 'AB", 5, "character constant is not closed", "'AB"),
        ("  L B#(1, 2", 5, "byte list is not closed", "B#(1, 2"),
        ("A I 0.0 @", 9, "unexpected character '@'", "@"),
        ("A I 0.0 / comment", 9, "unexpected character '/'", "/"),
        ("{", 1, "unexpected character '{'", "{"),
    ],
)
def test_lexical_errors(source: str, column: int, message: str, text: str) -> None:
    with pytest.raises(Mc7SyntaxError) as caught:
        tokenize(source, "bad.awl")
    error = caught.value
    assert error.location == SourceLocation("bad.awl", 1, column)
    assert (error.message, error.text) == (message, text)
    assert error.hint
    assert str(error) == f"bad.awl:1:{column}: {message}; {error.hint}"
    assert isinstance(error, Mc7AsmError)
    assert isinstance(error, ValueError)


def test_show_tokens_on_the_command_line(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(REPOSITORY)
    assert cli.main(["parse", "examples/counter.awl", "--show-tokens"]) == 0
    captured = capsys.readouterr()
    assert captured.out == (GOLDEN / "counter.tokens.txt").read_text()
    assert captured.out.startswith("examples/counter.awl:1:1    keyword     'FUNCTION'\n")
    assert captured.out.endswith("  end\n")
    assert all(line == line.rstrip() for line in captured.out.splitlines())
