"""Shared test helpers: synthetic block images and a fake PLC for block transfers."""

from __future__ import annotations

import socket
import struct
import threading
from dataclasses import dataclass, field

from snap7.server import ServerISOConnection

from mc7.blocks import HEADER_SIZE, BlockType

FOOTER_SIZE = 56


def make_block(
    block_type: BlockType = BlockType.FC,
    number: int = 1,
    *,
    mc7: bytes = b"\x65\x00",
    language: int = 1,
) -> bytes:
    """Build a structurally valid block image: header, MC7 payload and footer."""
    load_size = HEADER_SIZE + len(mc7) + FOOTER_SIZE
    header = struct.pack(
        ">2sBBBBHII6s6sHHHH",
        b"pp",
        0x01,
        0x01,
        language,
        block_type.subblock_code,
        number,
        load_size,
        0,
        bytes(range(6)),
        bytes(range(6, 12)),
        0,
        0,
        0,
        len(mc7),
    )
    footer = bytes(20) + b"AUTHOR  FAMILY  NAME    " + bytes((0x11, 0x00, 0xAB, 0xCD)) + bytes(8)
    return header + mc7 + footer


def free_port() -> int:
    """Return a TCP port that is currently unused on localhost."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


def _ack(reference: int, params: bytes, data: bytes = b"") -> bytes:
    return struct.pack(">BBHHHHH", 0x32, 0x03, 0, reference, len(params), len(data), 0) + (
        params + data
    )


def _error(reference: int, code: int) -> bytes:
    return struct.pack(">BBHHHHH", 0x32, 0x02, 0, reference, 0, 0, code)


@dataclass
class FakePlc:
    """A minimal S7 peer on a real TCP socket that implements block upload and download.

    It serves the PLC side of the sequences documented in :mod:`mc7.transfer`:
    start/continue/end upload, and request download, slice pulls, download
    ended and the ``_INSE`` insert. A downloaded block only becomes visible to
    uploads once it has been inserted, like on a real CPU. Variable writes are
    acknowledged and recorded in :attr:`writes` (parameters plus data).
    """

    blocks: dict[tuple[int, int], bytes] = field(default_factory=dict)
    pdu_length: int = 240
    download_error: int | None = None
    insert_error: int | None = None
    port: int = 0
    inserted: list[tuple[int, int]] = field(default_factory=list)
    writes: list[bytes] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._passive: dict[tuple[int, int], bytes] = {}
        self._listener = socket.socket()
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", self.port))
        self._listener.listen()
        self._listener.settimeout(0.2)
        self.port = self._listener.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def add(self, block_type: BlockType, number: int, image: bytes) -> None:
        self.blocks[(block_type.type_code, number)] = image

    def get(self, block_type: BlockType, number: int) -> bytes | None:
        return self.blocks.get((block_type.type_code, number))

    def __enter__(self) -> FakePlc:
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
        self._listener.close()

    # ---------------------------------------------------------------- serving

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                client, _address = self._listener.accept()
            except TimeoutError:
                continue
            with client:
                self._session(client)

    def _session(self, client: socket.socket) -> None:
        iso = ServerISOConnection(client)
        if not iso.accept_connection():
            self.failures.append("ISO handshake failed")
            return
        uploads: dict[int, tuple[bytes, int]] = {}
        try:
            while not self._stop.is_set():
                self._dispatch(iso, iso.receive_data(), uploads)
        except (ConnectionError, TimeoutError, OSError):
            return
        except Exception as exc:
            self.failures.append(f"{type(exc).__name__}: {exc}")

    def _dispatch(
        self, iso: ServerISOConnection, pdu: bytes, uploads: dict[int, tuple[bytes, int]]
    ) -> None:
        reference = struct.unpack_from(">H", pdu, 4)[0]
        params = pdu[10:]
        function = params[0]
        if function == 0xF0:
            iso.send_data(
                _ack(reference, bytes((0xF0, 0)) + struct.pack(">HHH", 1, 1, self.pdu_length))
            )
        elif function == 0x1D:
            self._start_upload(iso, reference, params, uploads)
        elif function == 0x1E:
            self._upload(iso, reference, params, uploads)
        elif function == 0x1F:
            uploads.pop(params[7], None)
            iso.send_data(_ack(reference, bytes((0x1F,))))
        elif function == 0x1A:
            self._download(iso, reference, params)
        elif function == 0x28:
            self._insert(iso, reference, params)
        elif function == 0x05:
            self.writes.append(pdu[10:])
            iso.send_data(_ack(reference, bytes((0x05, 0x01)), b"\xff"))
        else:
            iso.send_data(_error(reference, 0x8104))

    def _start_upload(
        self,
        iso: ServerISOConnection,
        reference: int,
        params: bytes,
        uploads: dict[int, tuple[bytes, int]],
    ) -> None:
        key = (params[11], int(params[12:17]))
        image = self.blocks.get(key)
        if image is None:
            iso.send_data(_error(reference, 0xD209))
            return
        upload_id = 7
        uploads[upload_id] = (image, 0)
        reply = bytes((0x1D, 0x00, 0x01, 0x00)) + struct.pack(">I", upload_id)
        iso.send_data(_ack(reference, reply + b"\x07" + f"{len(image):07d}".encode()))

    def _upload(
        self,
        iso: ServerISOConnection,
        reference: int,
        params: bytes,
        uploads: dict[int, tuple[bytes, int]],
    ) -> None:
        image, offset = uploads[params[7]]
        chunk = image[offset : offset + self.pdu_length - 18]
        offset += len(chunk)
        uploads[params[7]] = (image, offset)
        more = offset < len(image)
        data = struct.pack(">HH", len(chunk), 0x00FB) + chunk
        iso.send_data(_ack(reference, bytes((0x1E, 1 if more else 0)), data))

    def _download(self, iso: ServerISOConnection, reference: int, params: bytes) -> None:
        if self.download_error is not None:
            iso.send_data(_error(reference, self.download_error))
            return
        if len(params) != 32 or params[8:11] != b"\x09_0" or params[17:20] != b"P\x0d1":
            self.failures.append(f"malformed request download: {params.hex(' ')}")
            iso.send_data(_error(reference, 0x8104))
            return
        key = (params[11], int(params[12:17]))
        load_size, mc7_size = int(params[20:26]), int(params[26:32])
        file_name = params[9:18]
        iso.send_data(_ack(reference, bytes((0x1A,))))

        received = bytearray()
        job_reference = 0x4000
        more = True
        while more:
            job_reference += 1
            iso.send_data(self._job(job_reference, 0x1B, file_name))
            answer = iso.receive_data()
            kind, ref, param_len, data_len, error = struct.unpack_from(">xBxxHHHH", answer)
            body = answer[12:]
            length, marker = struct.unpack_from(">HH", body, 2)
            chunk = body[6:]
            if (
                (kind, ref, param_len, error, body[0]) != (0x03, job_reference, 2, 0, 0x1B)
                or data_len != 4 + len(chunk)
                or (length, marker) != (len(chunk), 0x00FB)
                or len(answer) > self.pdu_length
            ):
                self.failures.append(f"malformed slice answer: {answer[:20].hex(' ')}")
                return
            received += chunk
            more = body[1] == 0x01

        job_reference += 1
        iso.send_data(self._job(job_reference, 0x1C, file_name))
        ended = iso.receive_data()
        if ended != _ack(job_reference, bytes((0x1C,))):
            self.failures.append(f"malformed download-ended answer: {ended.hex(' ')}")
            return
        header_mc7 = struct.unpack_from(">H", received, 34)[0]
        if (load_size, mc7_size) != (len(received), header_mc7):
            self.failures.append(f"announced sizes {load_size}/{mc7_size} do not match the data")
            return
        self._passive[key] = bytes(received)

    def _insert(self, iso: ServerISOConnection, reference: int, params: bytes) -> None:
        expected_prefix = bytes((0x28, 0, 0, 0, 0, 0, 0, 0xFD, 0x00, 0x0A, 0x01, 0x00))
        if len(params) != 26 or params[:12] != expected_prefix or params[20:] != b"\x05_INSE":
            iso.send_data(_error(reference, 0x8104))
            return
        key = (params[13], int(params[14:19]))
        if params[12:13] != b"0" or params[19:20] != b"P" or key not in self._passive:
            self.failures.append(f"insert for a block that was not downloaded: {params.hex(' ')}")
            iso.send_data(_error(reference, 0xD209))
            return
        if self.insert_error is not None:
            iso.send_data(_error(reference, self.insert_error))
            return
        self.blocks[key] = self._passive.pop(key)
        self.inserted.append(key)
        iso.send_data(_ack(reference, bytes((0x28,))))

    @staticmethod
    def _job(reference: int, function: int, file_name: bytes) -> bytes:
        params = bytes((function,)) + bytes(7) + b"\x09" + file_name
        return struct.pack(">BBHHHH", 0x32, 0x01, 0, reference, len(params), 0) + params
