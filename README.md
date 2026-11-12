# mc7

A small Python library and CLI for talking to a Siemens S7-300 PLC over ISO-on-TCP (RFC 1006, TCP port 102).
It targets a CPU 317-2 DP reached through a CP 343-1 Ethernet module and is built on [python-snap7](https://github.com/gijzelaerr/python-snap7).

This is stage one: the communication layer only.

- Connect by IP at rack 0, slot 2, with clean connect/disconnect and context-manager support.
- Read and write inputs (I), outputs (Q) and bit memory (M) by address.
- Read and write data blocks with typed helpers (BOOL, BYTE, WORD, INT, DWORD, DINT, REAL, STRING).
- Read the CPU state and identity, and start or stop the CPU where it permits that.
- Upload blocks to local files and send a block file back unchanged as a round-trip integrity check.

## Verification status

Read this before pointing the tool at a machine.

- Everything is tested against a mocked snap7 client, against python-snap7's built-in S7 server over real TCP, and against a fake PLC in `tests/support.py` that implements block upload and download.
- Nothing has been run against a physical S7-300 yet.
  The optional integration tests exist for exactly that, see [Testing](#testing).
- Block download is implemented in this package, not by python-snap7.
  python-snap7 3.x only downloads data blocks and never sends the final insert command, so a block would be stored but not activated.
  `mc7/transfer.py` implements the full sequence for every block type, following the wire format of the original Snap7 C++ client.
  Try it first on a block that does not matter, for example a scratch DB.

## Install

Python 3.11 or newer is required.
python-snap7 is the only runtime dependency and it is pure Python, so no native library is needed.

With [uv](https://docs.astral.sh/uv/):

```bash
uv sync
```

```bash
uv run mc7 --help
```

With pip:

```bash
python -m venv .venv && . .venv/bin/activate && pip install -e .
```

## Network and wiring setup

1. Give the CP 343-1 an IP address in the STEP 7 hardware configuration and download the configuration to the station.
2. Connect the PC to the CP with an Ethernet cable, directly or through a switch.
3. Put the PC network interface in the same subnet as the CP, for example CP `192.168.0.10/24` and PC `192.168.0.100/24`.
4. Check that the CP answers: `ping 192.168.0.10`.
5. Make sure nothing between the PC and the CP blocks TCP port 102.

The connection is addressed to the CPU, not to the CP.
On an S7-300 the CPU always sits in rack 0, slot 2, which are the defaults here, no matter which slot the CP occupies.

Things that commonly get in the way:

- The CPU has a limited number of connection resources.
  If STEP 7, an HMI and other clients hold all of them, the connection is refused.
- A protection level set in the hardware configuration can make the CPU read-only or fully locked.
  Write, download and run-state requests are then refused and reported as errors.
  Supplying the CPU password is not part of this stage.
- Starting the CPU from the network only works when its mode selector is in RUN.

## CLI

Every command takes the connection options `-H/--host`, `--rack` (default 0), `--slot` (default 2), `--port` (default 102) and `-v/--verbose`.
The host can also come from the `MC7_HOST` environment variable.

```bash
export MC7_HOST=192.168.0.10
```

Check the connection and identify the CPU:

```bash
mc7 connect
```

```bash
mc7 info
```

Example output:

```text
State:         RUN
Module type:   CPU 317-2 DP
Order number:  6ES7 317-2AK14-0AB0
Firmware:      V3.3.12
Serial number: S C-X4U421302009
Station name:  SIMATIC 300 Station
Module name:   CPU 317-2 DP
```

Read values.
The output is the bare value, so it can be used in scripts.

```bash
mc7 read I0.0
```

```bash
mc7 read MW10 --type int
```

```bash
mc7 read DB1.DBD4 --type real
```

```bash
mc7 read DB1.DBB20 --type string
```

Write values:

```bash
mc7 write Q0.0 true
```

```bash
mc7 write MW10 -1234 --type int
```

```bash
mc7 write DB1.DBD4 3.5 --type real
```

List and upload blocks.
Files are written to `./blocks` as `OB1.mc7`, `FC105.mc7` and so on, and existing files are kept unless `--force` is given.

```bash
mc7 blocks
```

```bash
mc7 upload OB1 FC105 DB10
```

```bash
mc7 upload --all -o backup/
```

Send a block back unchanged and verify it:

```bash
mc7 download blocks/DB10.mc7
```

Example session:

```text
About to download DB10 (150 bytes) to 192.168.0.10, replacing the block there. Continue? [y/N] y
DB10 downloaded (150 bytes)
DB10 verified: the block in the PLC is identical to blocks/DB10.mc7
```

Change the operating state:

```bash
mc7 stop
```

```bash
mc7 start
```

`download`, `start` and `stop` ask for confirmation.
Pass `-y/--yes` to skip the question, which is required when the input is not a terminal.

Exit codes: `0` success, `1` the operation failed (the reason is printed to stderr as `error: ...`), `2` invalid command line.

### Addresses and types

| Address | Meaning | Default type | Other types |
| --- | --- | --- | --- |
| `I0.0`, `Q1.7`, `M10.3`, `DB1.DBX0.0` | single bit | `bool` | |
| `IB0`, `QB4`, `MB10`, `DB1.DBB2` | byte | `byte` | `string` |
| `IW0`, `QW4`, `MW10`, `DB1.DBW2` | word, 2 bytes | `word` | `int` |
| `ID0`, `QD4`, `MD20`, `DB1.DBD4` | double word, 4 bytes | `dword` | `dint`, `real` |

Addresses are case-insensitive and the German mnemonics `E` (input) and `A` (output) are accepted.
For `string`, the address points at the first header byte of an S7 `STRING`.
The declared maximum length is read from the PLC, enforced on write and never modified.

## Library

```python
from mc7 import BlockType, DataType, PlcClient

with PlcClient("192.168.0.10") as plc:  # rack 0, slot 2
    print(plc.cpu_info().order_number, plc.cpu_state())

    start_button = plc.read("I0.0")
    plc.write("Q0.0", True)
    plc.write("MW10", -1234, DataType.INT)

    speed = plc.db_read_real(1, 4)
    plc.db_write_int(1, 2, 42)
    plc.db_write_string(1, 20, "hello")

    image = plc.upload_block(BlockType.FC, 105)  # complete block as bytes
    plc.download_block(image)  # send it back unchanged
    plc.verify_block(image)  # raises BlockVerifyError on a difference
```

The public API is exported from the `mc7` package:

| Name | Purpose |
| --- | --- |
| `PlcClient` | Connection, I/Q/M/DB access, CPU state and identity, block upload and download. |
| `parse_address`, `Address`, `Area`, `Width`, `DataType` | Address parsing and the supported data types. |
| `BlockType`, `BlockHeader`, `parse_block`, `parse_block_spec`, `save_block`, `load_block`, `block_filename` | Block images and block files. |
| `CpuState`, `CpuInfo` | Results of `cpu_state()` and `cpu_info()`. |
| `Mc7Error` and subclasses | All errors, see below. |

### Errors

Every error derives from `Mc7Error`, and the message says what was attempted, where, and why it failed.

| Exception | Raised when |
| --- | --- |
| `AddressError` | An address or offset is malformed or out of range. Nothing is sent. |
| `EncodingError` | A value does not fit its S7 type. Nothing is sent. |
| `BlockFormatError` | Bytes or a file are not a complete block image. Nothing is sent. |
| `PlcConnectionError` | The PLC cannot be reached or the connection dropped. |
| `NotConnectedError` | An operation was called before `connect()`. Subclass of `PlcConnectionError`. |
| `PlcTimeoutError` | The PLC did not answer in time. |
| `PlcRequestError` | The PLC refused a request. `code` holds the S7 error word when there is one. |
| `BlockTransferError` | A block download failed part-way. Subclass of `PlcRequestError`. |
| `BlockVerifyError` | The block read back differs from the reference. |

### Module layout

| Module | Responsibility |
| --- | --- |
| `mc7.addressing` | Address grammar and validation. Pure. |
| `mc7.encoding` | Python values to and from big-endian S7 bytes. Pure. |
| `mc7.blocks` | Block header parsing, validation and block files. Pure apart from file access. |
| `mc7.transfer` | The block download sequence on top of a two-method PDU channel. |
| `mc7.client` | `PlcClient`: wraps python-snap7, validates first, translates errors. |
| `mc7.cli` | The `mc7` command, a thin layer over `PlcClient`. |
| `mc7.errors` | The exception hierarchy. |

## Blocks and the round-trip check

`upload` reads the complete block image: the 36-byte header, the MC7 payload, the interface description and the footer.
The image is validated before it is saved or sent: it must start with `pp`, carry a known block type, and its length field must match its size.

`download` sends the file byte for byte, has the CPU insert it in place of the existing block, then uploads the block again and compares it with the file.
A successful run therefore proves that the uploaded file is a complete block the CPU accepts, and that the CPU holds exactly those bytes afterwards.
If the insert is refused, the error says that the block was transferred but not activated.

Known differences and limits:

- The original Snap7 client zeroes the checksum field in the block footer before a download.
  mc7 does not modify the image at all.
- Deleting blocks, password sessions, timers and counters are out of scope for this stage.
- `cpu_state()` reports start-up, HOLD and DEFECT as `STOP`, as python-snap7 does.

## Safety

Writing outputs or bit memory, downloading blocks and stopping or starting the CPU change what the machine does.
Only use these on equipment you are responsible for, when it is in a safe state.
Single-bit writes use the S7 bit transport, so the CPU changes only the addressed bit and neighbouring bits are never rewritten.

## Testing

```bash
uv run pytest
```

The default run needs no hardware.
It contains unit tests against a mocked snap7 client, end-to-end tests over TCP against python-snap7's S7 server, and end-to-end block transfer tests against the fake PLC.

The integration tests talk to a real S7-300 and are skipped unless a host is given:

```bash
uv run pytest tests/test_integration.py --plc-host 192.168.0.10
```

That runs read-only tests: identity, state, reads and an upload of OB1.
Tests that write need an explicit opt-in and the name of what they may touch:

```bash
uv run pytest tests/test_integration.py --plc-host 192.168.0.10 --plc-allow-writes --plc-marker-byte 200 --plc-block DB100
```

- `--plc-marker-byte N` names four bit-memory bytes `MBn` to `MBn+3` that no program uses.
  They are written and then restored.
- `--plc-block DB100` names a block that is uploaded, downloaded unchanged and verified.
- `--plc-rack`, `--plc-slot` and `--plc-port` override the defaults, and `MC7_TEST_PLC_HOST` can replace `--plc-host`.

No integration test changes the operating state of the CPU.

## Development

```bash
uv run ruff format . && uv run ruff check . && uv run mypy && uv run pytest
```
