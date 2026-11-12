"""Parser: turns tokens into the intermediate representation.

Interface only in this stage; :func:`parse_source` raises
:class:`~mc7asm.errors.NotYetImplementedError`.
"""

from __future__ import annotations

from mc7asm.errors import NotYetImplementedError
from mc7asm.ir import BlockSource


def parse_source(source: str) -> BlockSource:
    """Parse the STL source of one block into its intermediate representation."""
    raise NotYetImplementedError("the STL parser")
