"""Communication layer for Siemens S7-300 PLCs over ISO-on-TCP (RFC 1006)."""

from mc7.addressing import Address, Area, DataType, Width, parse_address
from mc7.blocks import (
    BlockHeader,
    BlockType,
    block_filename,
    load_block,
    parse_block,
    parse_block_spec,
    save_block,
)
from mc7.client import CpuInfo, CpuState, PlcClient
from mc7.errors import (
    AddressError,
    BlockFormatError,
    BlockTransferError,
    BlockVerifyError,
    EncodingError,
    Mc7Error,
    NotConnectedError,
    PlcConnectionError,
    PlcRequestError,
    PlcTimeoutError,
)

__version__ = "0.1.0"

__all__ = [
    "Address",
    "AddressError",
    "Area",
    "BlockFormatError",
    "BlockHeader",
    "BlockTransferError",
    "BlockType",
    "BlockVerifyError",
    "CpuInfo",
    "CpuState",
    "DataType",
    "EncodingError",
    "Mc7Error",
    "NotConnectedError",
    "PlcClient",
    "PlcConnectionError",
    "PlcRequestError",
    "PlcTimeoutError",
    "Width",
    "__version__",
    "block_filename",
    "load_block",
    "parse_address",
    "parse_block",
    "parse_block_spec",
    "save_block",
]
