"""Exception hierarchy for the mc7asm package."""

from __future__ import annotations


class Mc7AsmError(Exception):
    """Base class for every error raised by mc7asm."""


class ImageFormatError(Mc7AsmError, ValueError):
    """Bytes are not a block container, or a field does not fit its wire size."""


class NotYetImplementedError(Mc7AsmError, NotImplementedError):
    """A pipeline step of the assembler exists as an interface only."""

    def __init__(self, feature: str) -> None:
        """Name the missing feature in the message."""
        super().__init__(
            f"{feature} is not implemented yet; mc7asm currently provides the block "
            "image model, its validation and the dump command only"
        )
        self.feature = feature
