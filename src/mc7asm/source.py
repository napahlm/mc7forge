"""Source locations, shared by the lexer, the IR and the error types."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SourceLocation:
    """A position in a source file.

    Attributes:
        file: Name of the file as given to the parser.
        line: 1-based line number.
        column: 1-based column number.
    """

    file: str
    line: int
    column: int

    def __str__(self) -> str:
        """Render as ``file:line:column``."""
        return f"{self.file}:{self.line}:{self.column}"


NO_LOCATION = SourceLocation("<generated>", 0, 0)
"""Location of IR nodes that were built in code and not parsed from a file."""
