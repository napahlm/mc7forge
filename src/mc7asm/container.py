"""Container writer: wraps assembled code into a complete block image.

The reading direction lives in :mod:`mc7asm.image`. This module will build a
new :class:`~mc7asm.image.BlockImage` from assembler output: fill the header
length fields, the interface, the segment table and the footer.

Interface only in this stage; :func:`build_image` raises
:class:`~mc7asm.errors.NotYetImplementedError`.
"""

from __future__ import annotations

from mc7asm.errors import NotYetImplementedError
from mc7asm.image import BlockImage
from mc7asm.ir import BlockSource


def build_image(block: BlockSource, mc7: bytes) -> BlockImage:
    """Build the block image for ``block`` around its encoded MC7 code."""
    raise NotYetImplementedError("building a block container")
