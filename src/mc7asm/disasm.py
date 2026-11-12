"""Disassembler: turns the MC7 code of a block image back into the intermediate representation.

Interface only in this stage; :func:`disassemble` raises
:class:`~mc7asm.errors.NotYetImplementedError`.
"""

from __future__ import annotations

from mc7asm.errors import NotYetImplementedError
from mc7asm.image import BlockImage
from mc7asm.ir import BlockSource


def disassemble(image: BlockImage) -> BlockSource:
    """Decode the MC7 code of a code block into networks of instructions."""
    raise NotYetImplementedError("the MC7 disassembler")
