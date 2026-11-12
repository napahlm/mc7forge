"""Byte-level tests of the download sequence against a scripted PLC.

The expected PDUs are spelled out in hex and follow the layout used by the
original Snap7 C++ client, so a change in the wire format cannot go unnoticed.
"""

from __future__ import annotations

import itertools
import struct
from collections.abc import Callable

import pytest

from mc7.blocks import BlockType, parse_block
from mc7.errors import BlockTransferError
from mc7.transfer import (
    build_download_ended_response,
    build_insert_request,
    build_request_download,
    build_slice_response,
    download_block,
)
from tests.support import make_block

FC5 = make_block(BlockType.FC, 5, mc7=bytes(range(40)))
FC5_HEADER = parse_block(FC5)


def ack(reference: int, function: int) -> bytes:
    return struct.pack(">BBHHHHHB", 0x32, 0x03, 0, reference, 1, 0, 0, function)


def error(reference: int, code: int) -> bytes:
    return struct.pack(">BBHHHHH", 0x32, 0x02, 0, reference, 0, 0, code)


def job(reference: int, function: int, name: bytes = b"_0C00005P") -> bytes:
    params = bytes((function,)) + bytes(7) + b"\x09" + name
    return struct.pack(">BBHHHH", 0x32, 0x01, 0, reference, len(params), 0) + params


class ScriptedChannel:
    """Replays PLC PDUs in order and records everything the client sends."""

    def __init__(self, replies: list[bytes]) -> None:
        self._replies = list(replies)
        self.sent: list[bytes] = []

    def send(self, pdu: bytes) -> None:
        self.sent.append(pdu)

    def receive(self) -> bytes:
        assert self._replies, "client waited for a PDU the script does not contain"
        return self._replies.pop(0)

    @property
    def exhausted(self) -> bool:
        return not self._replies


def references() -> Callable[[], int]:
    counter = itertools.count(1)
    return lambda: next(counter)


def run(channel: ScriptedChannel, pdu_length: int = 240, block: bytes = FC5) -> None:
    download_block(
        channel, block, parse_block(block), pdu_length=pdu_length, next_reference=references()
    )


def test_request_download_layout() -> None:
    pdu = build_request_download(0x0102, FC5_HEADER)
    assert pdu.hex(" ") == (
        "32 01 00 00 01 02 00 20 00 00 "  # job header: 32 parameter bytes, no data
        "1a 00 01 00 00 00 00 00 "  # function, fixed bytes, download id
        "09 5f 30 43 30 30 30 30 35 50 "  # length 9, "_0C00005P"
        "0d 31 "  # length 13, "1"
        "30 30 30 31 32 35 "  # load memory length "000125"
        "30 30 30 30 34 30"  # MC7 length "000040"
    )


def test_insert_request_layout() -> None:
    pdu = build_insert_request(0x0003, FC5_HEADER)
    assert pdu.hex(" ") == (
        "32 01 00 00 00 03 00 1a 00 00 "  # job header: 26 parameter bytes
        "28 00 00 00 00 00 00 fd "  # PI service
        "00 0a 01 00 30 43 30 30 30 30 35 50 "  # argument: one block, "0C00005P"
        "05 5f 49 4e 53 45"  # "_INSE"
    )


def test_slice_response_layout() -> None:
    assert build_slice_response(0x4001, b"\xaa\xbb\xcc", more=True).hex(" ") == (
        "32 03 00 00 40 01 00 02 00 07 00 00 1b 01 00 03 00 fb aa bb cc"
    )
    assert build_slice_response(0x4002, b"\xdd", more=False).hex(" ") == (
        "32 03 00 00 40 02 00 02 00 05 00 00 1b 00 00 01 00 fb dd"
    )


def test_download_ended_response_layout() -> None:
    assert (
        build_download_ended_response(0x4003).hex(" ") == "32 03 00 00 40 03 00 01 00 00 00 00 1c"
    )


@pytest.mark.parametrize("block_type", list(BlockType))
def test_file_name_carries_the_block_type(block_type: BlockType) -> None:
    header = parse_block(make_block(block_type, 123))
    request = build_request_download(1, header)
    assert request[19:28] == b"_0" + bytes((block_type.type_code,)) + b"00123P"
    insert = build_insert_request(1, header)
    assert insert[22:30] == b"0" + bytes((block_type.type_code,)) + b"00123P"


def test_full_sequence_in_a_single_slice() -> None:
    channel = ScriptedChannel([ack(1, 0x1A), job(0x4001, 0x1B), job(0x4002, 0x1C), ack(2, 0x28)])
    run(channel, pdu_length=480)
    assert channel.exhausted
    assert channel.sent == [
        build_request_download(1, FC5_HEADER),
        build_slice_response(0x4001, FC5, more=False),
        build_download_ended_response(0x4002),
        build_insert_request(2, FC5_HEADER),
    ]


def test_block_is_split_by_the_negotiated_pdu_length() -> None:
    pdu_length = 68  # leaves 50 payload bytes per slice
    assert len(FC5) == 125
    channel = ScriptedChannel(
        [
            ack(1, 0x1A),
            job(0x4001, 0x1B),
            job(0x4002, 0x1B),
            job(0x4003, 0x1B),
            job(0x4004, 0x1C),
            ack(2, 0x28),
        ]
    )
    run(channel, pdu_length=pdu_length)
    slices = channel.sent[1:4]
    assert all(len(pdu) <= pdu_length for pdu in slices)
    assert [pdu[13] for pdu in slices] == [1, 1, 0]
    assert b"".join(pdu[18:] for pdu in slices) == FC5
    assert [struct.unpack_from(">H", pdu, 4)[0] for pdu in slices] == [0x4001, 0x4002, 0x4003]


def test_refused_request_reports_the_s7_error_and_sends_nothing_else() -> None:
    channel = ScriptedChannel([error(1, 0xD241)])
    with pytest.raises(BlockTransferError, match=r"refused 'request download' for FC5") as caught:
        run(channel)
    assert caught.value.code == 0xD241
    assert "0xD241" in str(caught.value)
    assert "password" in str(caught.value)
    assert len(channel.sent) == 1


def test_refused_insert_says_the_block_is_not_active() -> None:
    channel = ScriptedChannel(
        [ack(1, 0x1A), job(0x4001, 0x1B), job(0x4002, 0x1C), error(2, 0xD209)]
    )
    with pytest.raises(BlockTransferError, match="NOT activated") as caught:
        run(channel, pdu_length=480)
    assert caught.value.code == 0xD209


def test_plc_error_in_the_middle_of_the_transfer() -> None:
    channel = ScriptedChannel([ack(1, 0x1A), error(0x4001, 0x8404)])
    with pytest.raises(BlockTransferError, match="0x8404") as caught:
        run(channel)
    assert caught.value.code == 0x8404


def test_plc_ending_early_is_detected() -> None:
    channel = ScriptedChannel([ack(1, 0x1A), job(0x4001, 0x1B), job(0x4002, 0x1C)])
    with pytest.raises(BlockTransferError, match="after 50 of 125 bytes"):
        run(channel, pdu_length=68)


def test_plc_asking_for_more_than_the_block_is_detected() -> None:
    channel = ScriptedChannel([ack(1, 0x1A), job(0x4001, 0x1B), job(0x4002, 0x1B)])
    with pytest.raises(BlockTransferError, match="asked for more data"):
        run(channel, pdu_length=480)


def test_unexpected_job_is_detected() -> None:
    channel = ScriptedChannel([ack(1, 0x1A), job(0x4001, 0x29)])
    with pytest.raises(BlockTransferError, match="unexpected job 0x29"):
        run(channel)


def test_wrong_acknowledgement_is_detected() -> None:
    with pytest.raises(BlockTransferError, match="did not confirm 'request download'"):
        run(ScriptedChannel([ack(1, 0x1D)]))


@pytest.mark.parametrize("garbage", [b"", b"\x32\x03", b"\x00" * 12, b"\x33" + bytes(12)])
def test_malformed_replies_are_detected(garbage: bytes) -> None:
    with pytest.raises(BlockTransferError, match="malformed"):
        run(ScriptedChannel([garbage]))
    with pytest.raises(BlockTransferError, match="malformed"):
        run(ScriptedChannel([ack(1, 0x1A), garbage]))


def test_too_small_pdu_is_rejected_before_anything_is_sent() -> None:
    channel = ScriptedChannel([])
    with pytest.raises(BlockTransferError, match="too small"):
        run(channel, pdu_length=18)
    assert channel.sent == []
