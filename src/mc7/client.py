"""High-level client for an S7-300 CPU reached over ISO-on-TCP.

:class:`PlcClient` wraps a python-snap7 client, validates arguments before
anything is sent, and translates every low-level failure into the typed
exceptions of :mod:`mc7.errors`.
"""

from __future__ import annotations

import itertools
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from types import TracebackType
from typing import Self

import snap7
from snap7.error import S7ConnectionError, S7Error, S7TimeoutError
from snap7.type import Area as S7Area
from snap7.type import Block as S7Block
from snap7.type import WordLen

from mc7 import transfer
from mc7.addressing import (
    Address,
    Area,
    DataType,
    parse_address,
    resolve_dtype,
    validate_bit,
    validate_byte_offset,
    validate_db_number,
)
from mc7.blocks import BlockHeader, BlockType, parse_block, validate_block_number
from mc7.encoding import (
    STRING_HEADER_SIZE,
    Scalar,
    Value,
    decode,
    encode,
    encode_string,
    parse_string_header,
    size_of,
)
from mc7.errors import (
    AddressError,
    BlockVerifyError,
    EncodingError,
    Mc7Error,
    NotConnectedError,
    PlcConnectionError,
    PlcRequestError,
    PlcTimeoutError,
)

DEFAULT_RACK = 0
DEFAULT_SLOT = 2
DEFAULT_PORT = 102
MAX_LISTED_BLOCKS = 65536

_S7_AREAS: dict[Area, S7Area] = {
    Area.INPUT: S7Area.PE,
    Area.OUTPUT: S7Area.PA,
    Area.MARKER: S7Area.MK,
    Area.DB: S7Area.DB,
}

_CPU_STATES: dict[str, str] = {
    "S7CpuStatusRun": "RUN",
    "S7CpuStatusStop": "STOP",
}


class CpuState(Enum):
    """Operating state of the CPU as reported by the PLC.

    Start-up, HOLD and DEFECT are reported as :attr:`STOP`, like Snap7 does.
    """

    RUN = "RUN"
    STOP = "STOP"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class CpuInfo:
    """Identity of the CPU.

    Attributes:
        module_type: Module type name, for example ``CPU 317-2 DP``.
        order_number: Order number (MLFB), for example ``6ES7 317-2AK14-0AB0``.
        firmware: Firmware version, for example ``3.3.12``.
        serial_number: Serial number of the module.
        station_name: Name of the automation system (station).
        module_name: Name given to the module in the hardware configuration.
    """

    module_type: str
    order_number: str
    firmware: str
    serial_number: str
    station_name: str
    module_name: str


class _Snap7Channel:
    """Adapts the ISO connection of a snap7 client to :class:`mc7.transfer.PduChannel`."""

    def __init__(self, connection: snap7.connection.ISOTCPConnection) -> None:
        self._connection = connection

    def send(self, pdu: bytes) -> None:
        self._connection.send_data(pdu)

    def receive(self) -> bytes:
        return bytes(self._connection.receive_data())


class PlcClient:
    """Connection to one S7-300 CPU.

    The defaults match a CPU 317-2 DP sitting in rack 0, slot 2 and reached
    through a CP 343-1 Ethernet module.

    Example:
        >>> with PlcClient("192.168.0.10") as plc:
        ...     plc.read("MW10", DataType.INT)
        ...     plc.write("Q0.0", True)
    """

    def __init__(
        self,
        host: str,
        rack: int = DEFAULT_RACK,
        slot: int = DEFAULT_SLOT,
        port: int = DEFAULT_PORT,
        *,
        snap7_client: snap7.Client | None = None,
    ) -> None:
        """Create a client without connecting.

        Args:
            host: IP address or host name of the CP/CPU.
            rack: Rack of the CPU (0 for an S7-300).
            slot: Slot of the CPU (2 for an S7-300).
            port: TCP port of the ISO-on-TCP service.
            snap7_client: Low-level client to use instead of a new ``snap7.Client``,
                mainly for tests.
        """
        if not host.strip():
            raise PlcConnectionError("no PLC host given")
        self.host = host
        self.rack = rack
        self.slot = slot
        self.port = port
        self._client = snap7_client if snap7_client is not None else snap7.Client()
        self._connected = False
        self._references = itertools.count(1)

    # ------------------------------------------------------------------ connection

    @property
    def connected(self) -> bool:
        """Whether :meth:`connect` succeeded and :meth:`disconnect` was not called since."""
        return self._connected

    @property
    def pdu_length(self) -> int:
        """PDU length negotiated with the PLC."""
        self._require_connection()
        return int(self._client.get_pdu_length())

    def connect(self) -> None:
        """Open the connection and negotiate the PDU length.

        Raises:
            PlcConnectionError: If the PLC cannot be reached or refuses the connection.
            PlcTimeoutError: If the PLC does not answer in time.
        """
        if self._connected:
            return
        try:
            self._client.connect(self.host, self.rack, self.slot, self.port)
        except (S7Error, OSError, RuntimeError) as exc:
            error = PlcTimeoutError if _is_timeout(exc) else PlcConnectionError
            raise error(
                f"cannot connect to {self._target()}: {exc}. Check the IP address, that TCP port "
                f"{self.port} is reachable, and that rack/slot match the CPU position"
            ) from exc
        self._connected = True

    def disconnect(self) -> None:
        """Close the connection. Safe to call when not connected."""
        was_connected = self._connected
        self._connected = False
        try:
            self._client.disconnect()
        except (S7Error, OSError, RuntimeError) as exc:
            if was_connected:
                raise PlcConnectionError(
                    f"error while disconnecting from {self._target()}: {exc}"
                ) from exc

    def __enter__(self) -> Self:
        """Connect and return the client."""
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Disconnect, without masking an exception raised inside the ``with`` body."""
        try:
            self.disconnect()
        except PlcConnectionError:
            if exc_type is None:
                raise

    # ------------------------------------------------------------------ raw access

    def read_bytes(self, area: Area, start: int, size: int, *, db_number: int = 0) -> bytes:
        """Read ``size`` bytes starting at byte offset ``start`` of an area."""
        self._validate_range(area, start, size, db_number)
        with self._plc_errors(f"read {size} byte(s) at {_where(area, start, db_number)}"):
            data = self._client.read_area(_S7_AREAS[area], db_number, start, size)
        if len(data) != size:
            raise PlcRequestError(
                f"PLC returned {len(data)} byte(s) instead of {size} "
                f"at {_where(area, start, db_number)}"
            )
        return bytes(data)

    def write_bytes(self, area: Area, start: int, data: bytes, *, db_number: int = 0) -> None:
        """Write ``data`` starting at byte offset ``start`` of an area."""
        self._validate_range(area, start, len(data), db_number)
        with self._plc_errors(f"write {len(data)} byte(s) at {_where(area, start, db_number)}"):
            self._client.write_area(_S7_AREAS[area], db_number, start, bytearray(data))

    def read_bit(self, area: Area, byte: int, bit: int, *, db_number: int = 0) -> bool:
        """Read a single bit (the containing byte is read and masked)."""
        self._validate_bit_address(area, byte, bit, db_number)
        return bool(self.read_bytes(area, byte, 1, db_number=db_number)[0] >> bit & 0x01)

    def write_bit(
        self, area: Area, byte: int, bit: int, value: bool, *, db_number: int = 0
    ) -> None:
        """Write a single bit.

        The request uses the S7 bit transport, so the PLC changes only the
        addressed bit. Neighbouring bits cannot be clobbered by a
        read-modify-write race with the user program.
        """
        self._validate_bit_address(area, byte, bit, db_number)
        payload = bytearray(encode(DataType.BOOL, value))
        with self._plc_errors(f"write bit {_where(area, byte, db_number)}.{bit}"):
            self._client.write_area(
                _S7_AREAS[area], db_number, byte * 8 + bit, payload, WordLen.Bit
            )

    # ------------------------------------------------------------------ typed access

    def read(self, address: str | Address, dtype: DataType | None = None) -> Value:
        """Read one value by absolute address.

        Args:
            address: For example ``"I0.0"``, ``"MW10"`` or ``"DB1.DBD4"``.
            dtype: Interpretation of the operand. Defaults to the unsigned type
                of the address width (BOOL, BYTE, WORD, DWORD).
        """
        target = parse_address(address) if isinstance(address, str) else address
        return self._read_value(target, resolve_dtype(target, dtype))

    def write(self, address: str | Address, value: Value, dtype: DataType | None = None) -> None:
        """Write one value by absolute address. See :meth:`read` for the arguments."""
        target = parse_address(address) if isinstance(address, str) else address
        self._write_value(target, resolve_dtype(target, dtype), value)

    def _read_value(self, address: Address, dtype: DataType) -> Value:
        db_number = address.db_number or 0
        if dtype is DataType.BOOL:
            assert address.bit is not None
            return self.read_bit(address.area, address.byte, address.bit, db_number=db_number)
        if dtype is DataType.STRING:
            return self._read_string(address.area, address.byte, db_number)
        raw = self.read_bytes(address.area, address.byte, size_of(dtype), db_number=db_number)
        return decode(dtype, raw)

    def _write_value(self, address: Address, dtype: DataType, value: Value) -> None:
        db_number = address.db_number or 0
        if dtype is DataType.STRING:
            if not isinstance(value, str):
                raise EncodingError(f"string needs text, got {value!r}")
            self._write_string(address.area, address.byte, db_number, value)
            return
        if isinstance(value, str):
            raise EncodingError(f"{dtype.value} needs a {dtype.value} value, got text {value!r}")
        if dtype is DataType.BOOL:
            assert address.bit is not None
            if not isinstance(value, bool):
                raise EncodingError(f"bool needs True or False, got {value!r}")
            self.write_bit(address.area, address.byte, address.bit, value, db_number=db_number)
            return
        self.write_bytes(address.area, address.byte, encode(dtype, value), db_number=db_number)

    def _read_string(self, area: Area, start: int, db_number: int) -> str:
        header = self.read_bytes(area, start, STRING_HEADER_SIZE, db_number=db_number)
        _, current_length = self._string_header(header, area, start, db_number)
        if current_length == 0:
            return ""
        payload = self.read_bytes(
            area, start + STRING_HEADER_SIZE, current_length, db_number=db_number
        )
        return payload.decode("latin-1")

    def _write_string(self, area: Area, start: int, db_number: int, value: str) -> None:
        header = self.read_bytes(area, start, STRING_HEADER_SIZE, db_number=db_number)
        max_length, _ = self._string_header(header, area, start, db_number)
        # Skip the max-length byte so the declared size of the STRING is never altered.
        self.write_bytes(area, start + 1, encode_string(value, max_length), db_number=db_number)

    @staticmethod
    def _string_header(header: bytes, area: Area, start: int, db_number: int) -> tuple[int, int]:
        try:
            return parse_string_header(header)
        except EncodingError as exc:
            raise EncodingError(f"{_where(area, start, db_number)}: {exc}") from exc

    # ------------------------------------------------------------------ DB helpers

    def db_read_bool(self, db_number: int, byte: int, bit: int) -> bool:
        """Read a BOOL at ``DBn.DBXbyte.bit``."""
        return self.read_bit(Area.DB, byte, bit, db_number=db_number)

    def db_write_bool(self, db_number: int, byte: int, bit: int, value: bool) -> None:
        """Write a BOOL at ``DBn.DBXbyte.bit``."""
        self.write_bit(Area.DB, byte, bit, value, db_number=db_number)

    def db_read_word(self, db_number: int, offset: int) -> int:
        """Read a WORD (unsigned 16-bit) at ``DBn.DBWoffset``."""
        return int(self._db_read(db_number, offset, DataType.WORD))

    def db_write_word(self, db_number: int, offset: int, value: int) -> None:
        """Write a WORD (unsigned 16-bit) at ``DBn.DBWoffset``."""
        self._db_write(db_number, offset, DataType.WORD, value)

    def db_read_int(self, db_number: int, offset: int) -> int:
        """Read an INT (signed 16-bit) at ``DBn.DBWoffset``."""
        return int(self._db_read(db_number, offset, DataType.INT))

    def db_write_int(self, db_number: int, offset: int, value: int) -> None:
        """Write an INT (signed 16-bit) at ``DBn.DBWoffset``."""
        self._db_write(db_number, offset, DataType.INT, value)

    def db_read_dint(self, db_number: int, offset: int) -> int:
        """Read a DINT (signed 32-bit) at ``DBn.DBDoffset``."""
        return int(self._db_read(db_number, offset, DataType.DINT))

    def db_write_dint(self, db_number: int, offset: int, value: int) -> None:
        """Write a DINT (signed 32-bit) at ``DBn.DBDoffset``."""
        self._db_write(db_number, offset, DataType.DINT, value)

    def db_read_real(self, db_number: int, offset: int) -> float:
        """Read a REAL (32-bit float) at ``DBn.DBDoffset``."""
        return float(self._db_read(db_number, offset, DataType.REAL))

    def db_write_real(self, db_number: int, offset: int, value: float) -> None:
        """Write a REAL (32-bit float) at ``DBn.DBDoffset``."""
        self._db_write(db_number, offset, DataType.REAL, value)

    def db_read_string(self, db_number: int, offset: int) -> str:
        """Read an S7 STRING whose header starts at byte ``offset`` of the DB."""
        validate_db_number(db_number)
        return self._read_string(Area.DB, offset, db_number)

    def db_write_string(self, db_number: int, offset: int, value: str) -> None:
        """Write an S7 STRING whose header starts at byte ``offset`` of the DB.

        The declared maximum length is read from the PLC and enforced.
        """
        validate_db_number(db_number)
        self._write_string(Area.DB, offset, db_number, value)

    def _db_read(self, db_number: int, offset: int, dtype: DataType) -> Scalar:
        raw = self.read_bytes(Area.DB, offset, size_of(dtype), db_number=db_number)
        return decode(dtype, raw)

    def _db_write(self, db_number: int, offset: int, dtype: DataType, value: Scalar) -> None:
        self.write_bytes(Area.DB, offset, encode(dtype, value), db_number=db_number)

    # ------------------------------------------------------------------ CPU

    def cpu_state(self) -> CpuState:
        """Return the current operating state of the CPU."""
        self._require_connection()
        with self._plc_errors("read the CPU state"):
            raw = self._client.get_cpu_state()
        return CpuState(_CPU_STATES.get(raw, "UNKNOWN"))

    def cpu_info(self) -> CpuInfo:
        """Return the identity of the CPU (type, order number, firmware, ...)."""
        self._require_connection()
        with self._plc_errors("read the CPU identification"):
            info = self._client.get_cpu_info()
            order = self._client.get_order_code()
        return CpuInfo(
            module_type=_text(info.ModuleTypeName),
            order_number=_text(order.OrderCode),
            firmware=f"{order.V1}.{order.V2}.{order.V3}",
            serial_number=_text(info.SerialNumber),
            station_name=_text(info.ASName),
            module_name=_text(info.ModuleName),
        )

    def stop(self) -> bool:
        """Put the CPU into STOP.

        Returns:
            ``False`` if the CPU was already in STOP and nothing was sent, else ``True``.

        Raises:
            PlcRequestError: If the CPU refuses, for example because of its protection level.
        """
        if self.cpu_state() is CpuState.STOP:
            return False
        with self._plc_errors("stop the CPU", hint=_RUN_STATE_HINT):
            self._client.plc_stop()
        return True

    def start(self, *, cold: bool = False) -> bool:
        """Start the CPU with a warm restart, or a cold restart when ``cold`` is true.

        Returns:
            ``False`` if the CPU was already in RUN and nothing was sent, else ``True``.

        Raises:
            PlcRequestError: If the CPU refuses, for example because the mode
                selector is in STOP or the protection level forbids it.
        """
        if self.cpu_state() is CpuState.RUN:
            return False
        with self._plc_errors("start the CPU", hint=_RUN_STATE_HINT):
            if cold:
                self._client.plc_cold_start()
            else:
                self._client.plc_hot_start()
        return True

    def wait_for_state(
        self, state: CpuState, *, timeout: float = 10.0, interval: float = 0.25
    ) -> CpuState:
        """Poll until the CPU reports ``state`` or ``timeout`` seconds passed.

        Returns:
            The last state read, which the caller should compare with ``state``.
        """
        deadline = time.monotonic() + timeout
        while True:
            current = self.cpu_state()
            if current is state or time.monotonic() >= deadline:
                return current
            time.sleep(interval)

    # ------------------------------------------------------------------ blocks

    def list_blocks(self, block_type: BlockType) -> list[int]:
        """Return the sorted numbers of all blocks of one type present in the CPU."""
        self._require_connection()
        with self._plc_errors(f"list {block_type.value} blocks"):
            numbers = self._client.list_blocks_of_type(_s7_block(block_type), MAX_LISTED_BLOCKS)
        return sorted(int(number) for number in numbers)

    def upload_block(self, block_type: BlockType, number: int) -> bytes:
        """Read a complete block image (header, payload and footer) from the CPU.

        Raises:
            PlcRequestError: If the PLC refuses, or returns something that is not
                the requested block.
        """
        validate_block_number(number)
        self._require_connection()
        name = f"{block_type.value}{number}"
        with self._plc_errors(f"upload {name}"):
            data, _size = self._client.full_upload(_s7_block(block_type), number)
        image = bytes(data)
        try:
            header = parse_block(image)
        except Mc7Error as exc:
            raise PlcRequestError(f"PLC returned an invalid image for {name}: {exc}") from exc
        if (header.block_type, header.number) != (block_type, number):
            raise PlcRequestError(f"asked the PLC for {name} but received {header.name}")
        return image

    def download_block(self, data: bytes) -> BlockHeader:
        """Send a block image to the CPU byte for byte and have it activated.

        The block type and number are taken from the image itself. An existing
        block with the same name is replaced.

        Raises:
            BlockFormatError: If ``data`` is not a valid block image (nothing is sent).
            BlockTransferError: If the PLC refuses a step of the download.
        """
        header = parse_block(data)
        self._require_connection()
        connection = self._client.connection
        if connection is None:
            raise NotConnectedError(f"connection to {self._target()} is closed; reconnect first")
        with self._plc_errors(f"download {header.name}"):
            transfer.download_block(
                _Snap7Channel(connection),
                data,
                header,
                pdu_length=int(self._client.get_pdu_length()),
                next_reference=lambda: next(self._references) & 0xFFFF,
            )
        return header

    def verify_block(self, data: bytes) -> BlockHeader:
        """Upload the block named by ``data`` and require it to be identical.

        Raises:
            BlockVerifyError: If the block in the PLC differs from ``data``.
        """
        header = parse_block(data)
        actual = self.upload_block(header.block_type, header.number)
        if actual != data:
            raise BlockVerifyError(_describe_difference(header.name, data, actual))
        return header

    # ------------------------------------------------------------------ internals

    def _target(self) -> str:
        return f"{self.host}:{self.port} (rack {self.rack}, slot {self.slot})"

    def _require_connection(self) -> None:
        if not self._connected:
            raise NotConnectedError(
                f"not connected to {self._target()}; call connect() or use the client "
                "as a context manager"
            )

    def _validate_range(self, area: Area, start: int, size: int, db_number: int) -> None:
        self._validate_area(area, db_number)
        validate_byte_offset(start)
        if size <= 0:
            raise AddressError(f"size must be at least 1 byte, got {size}")
        validate_byte_offset(start + size - 1)
        self._require_connection()

    def _validate_bit_address(self, area: Area, byte: int, bit: int, db_number: int) -> None:
        self._validate_area(area, db_number)
        validate_byte_offset(byte)
        validate_bit(bit)
        self._require_connection()

    @staticmethod
    def _validate_area(area: Area, db_number: int) -> None:
        if area is Area.DB:
            validate_db_number(db_number)
        elif db_number != 0:
            raise AddressError(f"area {area.value} does not take a DB number")

    @contextmanager
    def _plc_errors(self, action: str, *, hint: str = "") -> Iterator[None]:
        """Translate low-level failures of one PLC operation into mc7 exceptions."""
        try:
            yield
        except Mc7Error:
            raise
        except (S7Error, OSError, RuntimeError, ValueError) as exc:
            message = f"failed to {action} on {self._target()}: {exc}{hint}"
            if _is_timeout(exc):
                raise PlcTimeoutError(message) from exc
            if isinstance(exc, S7ConnectionError | OSError):
                self._connected = False
                raise PlcConnectionError(message) from exc
            raise PlcRequestError(message, code=getattr(exc, "error_code", None)) from exc


_RUN_STATE_HINT = (
    ". The CPU only accepts this when its mode selector and protection level allow "
    "operating-mode changes from the network"
)


def _is_timeout(exc: BaseException) -> bool:
    return isinstance(exc, S7TimeoutError | TimeoutError)


def _s7_block(block_type: BlockType) -> S7Block:
    return S7Block[block_type.name]


def _text(raw: bytes) -> str:
    """Decode a fixed-width identification field."""
    return raw.split(b"\x00", 1)[0].decode("latin-1").strip()


def _where(area: Area, start: int, db_number: int) -> str:
    if area is Area.DB:
        return f"DB{db_number} byte {start}"
    return f"{area.value} byte {start}"


def _describe_difference(name: str, expected: bytes, actual: bytes) -> str:
    if len(expected) != len(actual):
        return (
            f"{name} in the PLC is {len(actual)} byte(s), the reference is {len(expected)} byte(s)"
        )
    offset = next(i for i, (a, b) in enumerate(zip(expected, actual, strict=True)) if a != b)
    return (
        f"{name} in the PLC differs from the reference at byte offset {offset} "
        f"(expected 0x{expected[offset]:02X}, found 0x{actual[offset]:02X})"
    )
