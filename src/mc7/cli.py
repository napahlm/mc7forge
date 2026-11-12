"""Command line interface: a thin layer over :class:`mc7.client.PlcClient`.

Exit codes: 0 success, 1 the operation failed, 2 invalid command line.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from mc7 import __version__
from mc7.addressing import DataType, parse_address, resolve_dtype
from mc7.blocks import BlockType, block_filename, load_block, parse_block_spec, save_block
from mc7.client import DEFAULT_PORT, DEFAULT_RACK, DEFAULT_SLOT, CpuState, PlcClient
from mc7.encoding import Value
from mc7.errors import EncodingError, Mc7Error

HOST_ENV = "MC7_HOST"
EXIT_OK = 0
EXIT_FAILURE = 1

_UPLOAD_ALL_TYPES = (BlockType.OB, BlockType.FB, BlockType.FC, BlockType.DB)
_TRUE_WORDS = frozenset({"1", "true", "on", "yes"})
_FALSE_WORDS = frozenset({"0", "false", "off", "no"})

Handler = Callable[[argparse.Namespace], int]


class CliError(Mc7Error):
    """The command cannot proceed for a reason that is not a PLC failure."""


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return the process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(name)s: %(message)s")
    handler: Handler = args.handler
    try:
        return handler(args)
    except (Mc7Error, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_FAILURE
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with all sub-commands."""
    parser = argparse.ArgumentParser(
        prog="mc7",
        description="Talk to a Siemens S7-300 PLC over ISO-on-TCP (RFC 1006).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(
        title="commands", dest="command", required=True, metavar="COMMAND"
    )
    common = _connection_options()

    def add(name: str, handler: Handler, summary: str) -> argparse.ArgumentParser:
        sub = commands.add_parser(name, parents=[common], help=summary, description=summary)
        sub.set_defaults(handler=handler)
        return sub

    add("connect", _cmd_connect, "Check that the PLC answers and show the negotiated session.")
    add("info", _cmd_info, "Show the CPU identity and operating state.")

    read = add("read", _cmd_read, "Read one value by address and print it.")
    read.add_argument("address", help="for example I0.0, QB4, MW10, DB1.DBD4")
    _add_type_option(read)

    write = add("write", _cmd_write, "Write one value by address.")
    write.add_argument("address", help="for example Q0.0, MW10, DB1.DBW2")
    write.add_argument("value", help="true/false for bits, numbers (0x.. allowed), or text")
    _add_type_option(write)

    blocks = add("blocks", _cmd_blocks, "List the blocks present in the CPU.")
    blocks.add_argument(
        "--type",
        dest="block_types",
        action="append",
        choices=[t.value for t in BlockType],
        type=str.upper,
        metavar="TYPE",
        help=f"block type to list, repeatable: {_choices(BlockType)} (default: OB, FB, FC, DB)",
    )

    upload = add("upload", _cmd_upload, "Upload blocks from the PLC into local files.")
    upload.add_argument("blocks", nargs="*", metavar="BLOCK", help="for example OB1 FC105 DB10")
    upload.add_argument("--all", action="store_true", help="upload every OB, FB, FC and DB")
    upload.add_argument(
        "-o", "--output", type=Path, default=Path("blocks"), help="target directory (%(default)s)"
    )
    upload.add_argument("--force", action="store_true", help="overwrite existing files")

    download = add(
        "download",
        _cmd_download,
        "Send a block file back to the PLC unchanged and verify it by uploading it again.",
    )
    download.add_argument("file", type=Path, help="block file created by 'mc7 upload'")
    download.add_argument("--no-verify", action="store_true", help="skip the read-back comparison")
    _add_yes_option(download)

    start = add("start", _cmd_start, "Start the CPU (warm restart).")
    start.add_argument("--cold", action="store_true", help="cold restart instead of warm restart")
    _add_yes_option(start)

    stop = add("stop", _cmd_stop, "Put the CPU into STOP.")
    _add_yes_option(stop)
    return parser


def _connection_options() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    group = common.add_argument_group("connection")
    group.add_argument(
        "-H",
        "--host",
        default=os.environ.get(HOST_ENV),
        help=f"IP address of the PLC (default: ${HOST_ENV})",
    )
    group.add_argument("--rack", type=int, default=DEFAULT_RACK, help="CPU rack (%(default)s)")
    group.add_argument("--slot", type=int, default=DEFAULT_SLOT, help="CPU slot (%(default)s)")
    group.add_argument("--port", type=int, default=DEFAULT_PORT, help="TCP port (%(default)s)")
    group.add_argument("-v", "--verbose", action="store_true", help="log protocol details")
    return common


def _add_type_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-t",
        "--type",
        dest="dtype",
        choices=[t.value for t in DataType],
        type=str.lower,
        metavar="TYPE",
        help=(
            f"data type: {_choices(DataType)} "
            "(default: bool, byte, word or dword depending on the address width)"
        ),
    )


def _choices(enum: type[DataType] | type[BlockType]) -> str:
    return ", ".join(member.value for member in enum)


def _add_yes_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-y", "--yes", action="store_true", help="do not ask for confirmation")


# ---------------------------------------------------------------------- helpers


def open_client(args: argparse.Namespace) -> PlcClient:
    """Create the client for the connection options given on the command line."""
    if not args.host:
        raise CliError(f"no PLC address: pass --host or set the {HOST_ENV} environment variable")
    return PlcClient(args.host, rack=args.rack, slot=args.slot, port=args.port)


def _confirm(args: argparse.Namespace, action: str) -> None:
    """Ask before an action that changes the behaviour of the plant.

    Args:
        args: Parsed command line, ``args.yes`` skips the question.
        action: What is about to happen, phrased to follow "About to" and "refusing to".
    """
    if args.yes:
        return
    if not sys.stdin.isatty():
        raise CliError(f"refusing to {action} without --yes (input is not a terminal)")
    answer = input(f"About to {action}. Continue? [y/N] ").strip().lower()
    if answer not in ("y", "yes"):
        raise CliError("aborted, nothing was sent")


def parse_value(text: str, dtype: DataType) -> Value:
    """Convert a command line word into the Python value for ``dtype``."""
    if dtype is DataType.STRING:
        return text
    word = text.strip().lower()
    if dtype is DataType.BOOL:
        if word in _TRUE_WORDS:
            return True
        if word in _FALSE_WORDS:
            return False
        raise EncodingError(f"{text!r} is not a bit value; use true/false, on/off or 1/0")
    try:
        return float(word) if dtype is DataType.REAL else int(word, 0)
    except ValueError as exc:
        raise EncodingError(f"{text!r} is not a valid {dtype.value} value") from exc


def format_value(value: Value) -> str:
    """Render a value read from the PLC for printing."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _dtype_option(args: argparse.Namespace) -> DataType | None:
    return DataType(args.dtype) if args.dtype else None


# ---------------------------------------------------------------------- commands


def _cmd_connect(args: argparse.Namespace) -> int:
    with open_client(args) as plc:
        print(f"Connected to {plc.host}:{plc.port} (rack {plc.rack}, slot {plc.slot})")
        print(f"PDU length: {plc.pdu_length}")
        print(f"CPU state:  {plc.cpu_state().value}")
    return EXIT_OK


def _cmd_info(args: argparse.Namespace) -> int:
    with open_client(args) as plc:
        info = plc.cpu_info()
        state = plc.cpu_state()
    rows = (
        ("State", state.value),
        ("Module type", info.module_type),
        ("Order number", info.order_number),
        ("Firmware", f"V{info.firmware}"),
        ("Serial number", info.serial_number),
        ("Station name", info.station_name),
        ("Module name", info.module_name),
    )
    for label, value in rows:
        print(f"{label + ':':<15}{value or '-'}")
    return EXIT_OK


def _cmd_read(args: argparse.Namespace) -> int:
    address = parse_address(args.address)
    dtype = resolve_dtype(address, _dtype_option(args))
    with open_client(args) as plc:
        value = plc.read(address, dtype)
    print(format_value(value))
    return EXIT_OK


def _cmd_write(args: argparse.Namespace) -> int:
    address = parse_address(args.address)
    dtype = resolve_dtype(address, _dtype_option(args))
    value = parse_value(args.value, dtype)
    with open_client(args) as plc:
        plc.write(address, value, dtype)
    print(f"{address} = {format_value(value)}")
    return EXIT_OK


def _cmd_blocks(args: argparse.Namespace) -> int:
    types = [BlockType(name) for name in args.block_types] if args.block_types else None
    with open_client(args) as plc:
        for block_type in types or _UPLOAD_ALL_TYPES:
            numbers = plc.list_blocks(block_type)
            listing = " ".join(str(number) for number in numbers) or "-"
            print(f"{block_type.value + ':':<5}{listing}")
    return EXIT_OK


def _cmd_upload(args: argparse.Namespace) -> int:
    if args.all == bool(args.blocks):
        raise CliError("name the blocks to upload (for example OB1 FC105) or pass --all, not both")
    specs = [parse_block_spec(text) for text in args.blocks]
    with open_client(args) as plc:
        if args.all:
            specs = [(bt, number) for bt in _UPLOAD_ALL_TYPES for number in plc.list_blocks(bt)]
        for block_type, number in specs:
            path = args.output / block_filename(block_type, number)
            if path.exists() and not args.force:
                raise CliError(f"{path} already exists; pass --force to overwrite it")
            data = plc.upload_block(block_type, number)
            save_block(path, data, overwrite=args.force)
            print(f"{block_type.value}{number} -> {path} ({len(data)} bytes)")
    if not specs:
        print("no blocks found")
    return EXIT_OK


def _cmd_download(args: argparse.Namespace) -> int:
    data, header = load_block(args.file)
    plc = open_client(args)
    _confirm(
        args,
        f"download {header.name} ({len(data)} bytes) to {plc.host}, replacing the block there",
    )
    with plc:
        plc.download_block(data)
        print(f"{header.name} downloaded ({len(data)} bytes)")
        if not args.no_verify:
            plc.verify_block(data)
            print(f"{header.name} verified: the block in the PLC is identical to {args.file}")
    return EXIT_OK


def _cmd_start(args: argparse.Namespace) -> int:
    kind = "cold restart" if args.cold else "warm restart"
    plc = open_client(args)
    _confirm(args, f"start the CPU at {plc.host} ({kind})")
    with plc:
        return _report_state_change(plc, plc.start(cold=args.cold), CpuState.RUN)


def _cmd_stop(args: argparse.Namespace) -> int:
    plc = open_client(args)
    _confirm(args, f"put the CPU at {plc.host} into STOP")
    with plc:
        return _report_state_change(plc, plc.stop(), CpuState.STOP)


def _report_state_change(plc: PlcClient, requested: bool, target: CpuState) -> int:
    if not requested:
        print(f"CPU is already in {target.value}")
        return EXIT_OK
    state = plc.wait_for_state(target)
    if state is not target:
        raise CliError(
            f"the CPU accepted the request but reports {state.value} instead of {target.value}"
        )
    print(f"CPU state: {state.value}")
    return EXIT_OK
