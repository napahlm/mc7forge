"""The S7 block download sequence.

python-snap7 3.x only downloads data blocks and stops before the block is
activated, so this module implements the complete sequence for every block
type. It follows the wire format of the original Snap7 C++ client
(``TSnap7MicroClient::opDownload``):

1. The client asks to download: job ``0x1A`` naming the block as ``_0TNNNNNP``
   together with the load-memory and MC7 lengths.
2. The PLC pulls the image: it sends ``0x1B`` jobs and the client answers each
   with the next slice, flagging whether more data follows.
3. The PLC sends ``0x1C`` (download ended) and the client acknowledges.
4. The client sends the PI service ``_INSE`` so the PLC links the passive copy
   into its program. Without this step the block is stored but never used.

The module only needs a way to send and receive raw S7 PDUs
(:class:`PduChannel`), which keeps it independent of python-snap7 internals and
easy to test against a scripted peer.
"""

from __future__ import annotations

import struct
from collections.abc import Callable
from typing import Protocol

from snap7.error import get_protocol_error_message

from mc7.blocks import BlockHeader
from mc7.errors import BlockTransferError

PROTOCOL_ID = 0x32
PDU_JOB = 0x01
PDU_ACK = 0x02
PDU_ACK_DATA = 0x03

FN_REQUEST_DOWNLOAD = 0x1A
FN_DOWNLOAD_BLOCK = 0x1B
FN_DOWNLOAD_ENDED = 0x1C
FN_PI_SERVICE = 0x28

JOB_HEADER_SIZE = 10
ACK_HEADER_SIZE = 12
# ACK header (12) + function and more-flag (2) + slice length and 0x00FB marker (4).
SLICE_OVERHEAD = 18

ERROR_NEED_PASSWORD = 0xD241
_PASSIVE_FILESYSTEM = b"P"
_INSERT_SERVICE = b"_INSE"
_SLICE_MARKER = 0x00FB

_FUNCTION_NAMES: dict[int, str] = {
    FN_REQUEST_DOWNLOAD: "request download",
    FN_DOWNLOAD_BLOCK: "download block",
    FN_DOWNLOAD_ENDED: "download ended",
    FN_PI_SERVICE: "insert block",
}


class PduChannel(Protocol):
    """Minimal transport needed for a download: raw S7 PDUs in both directions."""

    def send(self, pdu: bytes) -> None:
        """Send one S7 PDU to the PLC."""

    def receive(self) -> bytes:
        """Block until the next S7 PDU from the PLC arrives and return it."""


def download_block(
    channel: PduChannel,
    block: bytes,
    header: BlockHeader,
    *,
    pdu_length: int,
    next_reference: Callable[[], int],
) -> None:
    """Send a validated block image to the PLC and have it inserted.

    Args:
        channel: Raw PDU transport of an established, negotiated connection.
        block: Complete block image, sent byte for byte.
        header: Header decoded from ``block`` by :func:`mc7.blocks.parse_block`.
        pdu_length: PDU length negotiated for the connection.
        next_reference: Supplies a fresh 16-bit PDU reference per client request.

    Raises:
        BlockTransferError: If the PLC refuses a step or leaves the expected sequence.
    """
    max_slice = pdu_length - SLICE_OVERHEAD
    if max_slice <= 0:
        raise BlockTransferError(f"negotiated PDU length {pdu_length} is too small for a download")

    channel.send(build_request_download(next_reference(), header))
    _expect_ack(channel.receive(), FN_REQUEST_DOWNLOAD, header)

    _serve_slices(channel, block, header, max_slice)

    channel.send(build_insert_request(next_reference(), header))
    try:
        _expect_ack(channel.receive(), FN_PI_SERVICE, header)
    except BlockTransferError as exc:
        raise BlockTransferError(
            f"{exc}. The block was transferred but NOT activated; the previous "
            f"{header.name} (if any) is still the one in use",
            code=exc.code,
        ) from exc


def _serve_slices(channel: PduChannel, block: bytes, header: BlockHeader, max_slice: int) -> None:
    """Answer the PLC's slice requests until it reports the download as ended."""
    offset = 0
    while True:
        function, reference = _parse_job(channel.receive(), header)
        if function == FN_DOWNLOAD_BLOCK:
            if offset >= len(block):
                raise BlockTransferError(
                    f"PLC asked for more data after all {len(block)} bytes of "
                    f"{header.name} were sent"
                )
            chunk = block[offset : offset + max_slice]
            offset += len(chunk)
            channel.send(build_slice_response(reference, chunk, more=offset < len(block)))
        elif function == FN_DOWNLOAD_ENDED:
            if offset < len(block):
                raise BlockTransferError(
                    f"PLC ended the download of {header.name} after {offset} of {len(block)} bytes"
                )
            channel.send(build_download_ended_response(reference))
            return
        else:
            raise BlockTransferError(
                f"unexpected job 0x{function:02X} from the PLC while downloading {header.name}"
            )


def block_file_id(header: BlockHeader) -> bytes:
    """Return the 8-byte block identifier ``0TNNNNNP`` used inside download requests."""
    if header.number > 99_999:
        raise BlockTransferError(f"block number {header.number} does not fit the 5-digit field")
    return (
        b"0"
        + bytes((header.block_type.type_code,))
        + f"{header.number:05d}".encode("ascii")
        + _PASSIVE_FILESYSTEM
    )


def build_request_download(reference: int, header: BlockHeader) -> bytes:
    """Build the job that announces a block download (function ``0x1A``)."""
    if header.load_size > 999_999 or header.mc7_size > 999_999:
        raise BlockTransferError(f"{header.name} is too large for the 6-digit length fields")
    file_name = b"_" + block_file_id(header)
    lengths = f"1{header.load_size:06d}{header.mc7_size:06d}".encode("ascii")
    params = (
        bytes((FN_REQUEST_DOWNLOAD, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00))
        + bytes((len(file_name),))
        + file_name
        + bytes((len(lengths),))
        + lengths
    )
    return _job_header(reference, len(params)) + params


def build_insert_request(reference: int, header: BlockHeader) -> bytes:
    """Build the PI service request ``_INSE`` that activates a downloaded block."""
    argument = bytes((0x01, 0x00)) + block_file_id(header)
    params = (
        bytes((FN_PI_SERVICE, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xFD))
        + struct.pack(">H", len(argument))
        + argument
        + bytes((len(_INSERT_SERVICE),))
        + _INSERT_SERVICE
    )
    return _job_header(reference, len(params)) + params


def build_slice_response(reference: int, chunk: bytes, *, more: bool) -> bytes:
    """Build the answer to a ``0x1B`` job carrying one slice of the block."""
    params = bytes((FN_DOWNLOAD_BLOCK, 0x01 if more else 0x00))
    data = struct.pack(">HH", len(chunk), _SLICE_MARKER) + chunk
    return _ack_header(reference, len(params), len(data)) + params + data


def build_download_ended_response(reference: int) -> bytes:
    """Build the acknowledgement of the PLC's ``0x1C`` (download ended) job."""
    return _ack_header(reference, 1, 0) + bytes((FN_DOWNLOAD_ENDED,))


def _job_header(reference: int, param_length: int) -> bytes:
    return struct.pack(">BBHHHH", PROTOCOL_ID, PDU_JOB, 0, reference & 0xFFFF, param_length, 0)


def _ack_header(reference: int, param_length: int, data_length: int) -> bytes:
    return struct.pack(
        ">BBHHHHH", PROTOCOL_ID, PDU_ACK_DATA, 0, reference & 0xFFFF, param_length, data_length, 0
    )


def _expect_ack(pdu: bytes, function: int, header: BlockHeader) -> None:
    """Require a successful acknowledgement of ``function``."""
    step = _FUNCTION_NAMES[function]
    if len(pdu) < ACK_HEADER_SIZE or pdu[0] != PROTOCOL_ID or pdu[1] not in (PDU_ACK, PDU_ACK_DATA):
        raise BlockTransferError(
            f"malformed reply to '{step}' for {header.name}: {pdu[:16].hex(' ')}"
        )
    _raise_on_error_word(pdu, step, header)
    if len(pdu) <= ACK_HEADER_SIZE or pdu[ACK_HEADER_SIZE] != function:
        raise BlockTransferError(
            f"PLC did not confirm '{step}' for {header.name}: {pdu[:16].hex(' ')}"
        )


def _parse_job(pdu: bytes, header: BlockHeader) -> tuple[int, int]:
    """Return ``(function, reference)`` of a job the PLC sent during a download."""
    if len(pdu) <= JOB_HEADER_SIZE or pdu[0] != PROTOCOL_ID:
        raise BlockTransferError(
            f"malformed PDU from the PLC while downloading {header.name}: {pdu[:16].hex(' ')}"
        )
    if pdu[1] in (PDU_ACK, PDU_ACK_DATA) and len(pdu) >= ACK_HEADER_SIZE:
        _raise_on_error_word(pdu, "download block", header)
    if pdu[1] != PDU_JOB:
        raise BlockTransferError(
            f"expected a job from the PLC while downloading {header.name}, "
            f"got PDU type {pdu[1]}: {pdu[:16].hex(' ')}"
        )
    reference: int = struct.unpack_from(">H", pdu, 4)[0]
    return pdu[JOB_HEADER_SIZE], reference


def _raise_on_error_word(pdu: bytes, step: str, header: BlockHeader) -> None:
    """Raise when the error class/code word of an acknowledgement is non-zero."""
    code: int = struct.unpack_from(">H", pdu, 10)[0]
    if code == 0:
        return
    hint = ""
    if code == ERROR_NEED_PASSWORD:
        hint = "; the CPU is write-protected (protection level or password)"
    raise BlockTransferError(
        f"PLC refused '{step}' for {header.name}: "
        f"{get_protocol_error_message(code)} (0x{code:04X}){hint}",
        code=code,
    )
