"""Exception hierarchy for the mc7 package.

Every failure raised by this package derives from :class:`Mc7Error`, so callers
can catch one type at the boundary and still branch on the specific cause.
"""

from __future__ import annotations


class Mc7Error(Exception):
    """Base class for every error raised by mc7."""


class AddressError(Mc7Error, ValueError):
    """An address string or address field is malformed or out of range."""


class EncodingError(Mc7Error, ValueError):
    """A value cannot be converted to or from its S7 wire representation."""


class BlockFormatError(Mc7Error, ValueError):
    """A byte sequence or file is not a well-formed S7 block."""


class PlcConnectionError(Mc7Error):
    """The connection to the PLC could not be established or was lost."""


class NotConnectedError(PlcConnectionError):
    """An operation was attempted before connecting (or after disconnecting)."""


class PlcTimeoutError(Mc7Error):
    """The PLC did not answer in time."""


class PlcRequestError(Mc7Error):
    """The PLC rejected a request or answered with something unexpected.

    Attributes:
        code: The 16-bit S7 error word when the PLC supplied one, else ``None``.
    """

    def __init__(self, message: str, *, code: int | None = None) -> None:
        """Store the message and the optional S7 error word."""
        super().__init__(message)
        self.code = code


class BlockTransferError(PlcRequestError):
    """A block download sequence failed part-way through."""


class BlockVerifyError(Mc7Error):
    """A block read back from the PLC differs from the expected bytes."""
