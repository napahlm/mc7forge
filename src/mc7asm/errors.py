"""Exception hierarchy for the mc7asm package."""

from __future__ import annotations

from mc7asm.source import SourceLocation


class Mc7AsmError(Exception):
    """Base class for every error raised by mc7asm."""


class ImageFormatError(Mc7AsmError, ValueError):
    """Bytes are not a block container, or a field does not fit its wire size."""


class CorpusFormatError(Mc7AsmError, ValueError):
    """The decoder test table does not have the expected line structure."""


class UnsupportedBlockError(Mc7AsmError):
    """The block is of a kind this tool does not disassemble."""


class NotYetImplementedError(Mc7AsmError, NotImplementedError):
    """A pipeline step of the assembler exists as an interface only."""

    def __init__(self, feature: str) -> None:
        """Name the missing feature in the message."""
        super().__init__(
            f"{feature} is not implemented yet; mc7asm compiles STL to MC7 code but does "
            "not build block containers"
        )
        self.feature = feature


class Mc7SyntaxError(Mc7AsmError, ValueError):
    """STL source text that the lexer or parser cannot accept.

    Attributes:
        location: Where the problem starts.
        message: What is wrong, without location and hint.
        text: The offending source text.
        hint: How to fix it, ``""`` if there is nothing useful to say.
    """

    def __init__(
        self, message: str, location: SourceLocation, *, text: str = "", hint: str = ""
    ) -> None:
        """Compose ``file:line:column: message; hint``."""
        super().__init__(f"{location}: {message}" + (f"; {hint}" if hint else ""))
        self.location = location
        self.message = message
        self.text = text
        self.hint = hint


class CodegenError(Mc7AsmError):
    """An instruction of the IR cannot be turned into MC7 bytes.

    Attributes:
        location: Source location of the instruction or operand.
        message: What is wrong, without location and hint.
        hint: What to do about it, ``""`` if there is nothing useful to say.
    """

    def __init__(self, message: str, location: SourceLocation, *, hint: str = "") -> None:
        """Compose ``file:line:column: message; hint``."""
        super().__init__(f"{location}: {message}" + (f"; {hint}" if hint else ""))
        self.location = location
        self.message = message
        self.hint = hint


class NotYetSupportedError(CodegenError):
    """The instruction is valid STL but outside what the code generator covers so far."""
