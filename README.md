# mc7

An open-source toolchain for the Siemens S7-300, in two packages.

- `mc7` is a library and CLI for talking to the PLC over ISO-on-TCP (RFC 1006, TCP port 102).
  It targets a CPU 317-2 DP reached through a CP 343-1 Ethernet module and is built on [python-snap7](https://github.com/gijzelaerr/python-snap7).
- `mc7asm` is the start of an STL to MC7 assembler.
  So far it reads, dumps and disassembles block files, and compiles straight-line STL source to MC7 code.
  It is pure software, works on block files only and never talks to a PLC.
  See [mc7asm](#mc7asm-block-images-and-the-assembler-skeleton).

The communication layer provides:

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

## mc7asm: block images and the assembler skeleton

`mc7asm` reads the block files that `mc7 upload` writes.
It models the block container at field level, prints it, and disassembles the MC7 code of OBs, FCs and FBs for the instruction forms in its opcode table.
It also parses STL source and compiles it to the raw MC7 code of a block; wrapping that code into a block container is the next stage.

```bash
mc7asm dump tests/fixtures/blocks/fake/OB1.mc7
```

The report lists every header and footer field with its offset, raw bytes and decoded value, then a hex dump of each section, then the findings:

```text
tests/fixtures/blocks/fake/OB1.mc7: OB1, 111 bytes

Header (offset 0x0000, 36 bytes)
  off  field                  raw                decoded
    0  signature              70 70              pp
    2  block version          01                 1
    3  attributes             01                 LINKED
    4  language               01                 STL
    5  block type             08                 OB
    6  block number           00 01              1
    8  block length           00 00 00 6f        111
   12  password               00 00 00 00        not set
   16  last modified          00 00 ea 60 00 01  1984-01-02 00:01:00.000
   22  last interface change  00 00 00 00 00 00  1984-01-01 00:00:00.000
   28  interface length       00 1b              27
   30  segment table length   00 06              6
   32  local data length      00 14              20
   34  MC7 code length        00 06              6

Sections
  offset  size  section
  0x0000    36  Header
  0x0024     6  MC7 code
  0x002a    27  Interface
  0x0045     6  Segment table
  0x004b     0  Trailing unknown
  0x004b    36  Footer
...
```

### Disassembling

```bash
mc7asm disasm tests/fixtures/blocks/reference/cm7.bin
```

```text
tests/fixtures/blocks/reference/cm7.bin: OB1, 36 bytes of MC7 code

  offset  bytes        instruction
  0x0024  c1 00        A I 0.1
  0x0026  49 30 00 00  FP M 0.0
  0x002a  d0 80        S Q 0.0
  ...
  0x0044  4b 80        T QB 0
  0x0046  65 00        BE

Coverage: 36 of 36 code bytes decoded, 0 unknown

Findings
  none
```

`--mnemonics de` prints German (SIMATIC) spelling, for example `U E 0.1` and `S A 0.0`.

The decoder is driven by the opcode table in `src/mc7asm/opcodes.py`, which is plain data: fixed bytes, mnemonic, operand form and length.
A row is in the table only if vectors of the opcode corpus exercise it, and every row is cross-checked against the C# decoder of DotNetSiemensPLCToolBoxLibrary.
[docs/opcodes.md](docs/opcodes.md) records the provenance of every row and the findings of the cross-check.

The table covers the minimal subset: `A AN O ON = S R` on directly addressed bits, `L T` on directly addressed bytes, words and double words, and `L` with typed constants.
It also has the few rows needed to decode the reference block completely: `FP`, `FN`, `CU`, `CD`, `LC` and `BE`.
718 of the 2,531 corpus vectors decode, each to exactly its expected text and length; the rest are reported as unknown.

Bytes the table does not know are never skipped.
They are listed as `?? unknown opcode` at their offset and again under the findings, together with a warning that instruction boundaries after the first unknown opcode are not certain.
Data blocks are rejected with a message, because their body holds values and not code.

### Parsing and compiling STL

```bash
mc7asm parse examples/blink.awl
```

```text
Block OB1 "Lamp control" at examples/blink.awl:1:1
  Network 1 "Latch the lamp" at examples/blink.awl:4:1
    // The start button sets the lamp, the stop button resets it.
    BitLogic A at examples/blink.awl:7:7  // start button
      BitAddress I 0.0 at examples/blink.awl:7:13
    BitWrite S at examples/blink.awl:8:7
      BitAddress Q 0.0 at examples/blink.awl:8:13
...
```

`mc7asm parse --show-tokens` prints the token stream of the lexer instead.

```bash
mc7asm compile examples/counter.awl -o counter.body
```

```text
examples/counter.awl: FC1, 2 networks, 36 bytes of MC7 code -> counter.body
  network 1 "Edge-triggered set and reset": 6 instructions, 16 bytes at offset 0x0000
  network 2 "Count and show the value": 9 instructions, 20 bytes at offset 0x0010
```

The output is the raw MC7 code only.
`examples/counter.awl` is the program of the reference block, and its body is byte for byte the code section of `cm7.bin`.

Both commands take `--mnemonics de` for German source (`U E 0.0`, `= A 0.0`, `ZV Z 1`).
The source subset, the IR and the rules of the code generator are described in [docs/assembler.md](docs/assembler.md).
In short:

- A file holds one block: `ORGANIZATION_BLOCK OB 1`, `FUNCTION FC 1 : VOID` or `FUNCTION_BLOCK FB 1`, then `BEGIN`, networks and the matching `END_...`.
- Statements: `A AN O ON = S R FP FN` on a bit, `L` with an address or a typed constant, `T` with an address, `CU CD LC` on a counter, `BE`, and the nesting forms `A( AN( O( ON( )`.
- Syntax errors name the file, line and column, the offending text and a hint.
- The code generator only uses rows of the opcode table.
  Valid STL without a usable row is refused with "not yet supported": nesting, fully qualified `DB1.DBX 0.0` addresses, `TRUE`/`FALSE` and the unverified `B#16#` constant.

The corpus is the arbiter of the whole chain.
Every corpus vector goes through bytes, disassembly, parsing and code generation, and 714 of the 718 vectors the table covers come back identical.
The other four are listed in the test with the reason: two are not the canonical encoding of their text, two belong to the unverified `B#16#` row.

### Opcode corpus

`tests/fixtures/corpus/test_simatic.c` is the decoder test table of rz-libmc7, vendored verbatim under LGPL-3.0-only with its licence text.
`mc7asm.corpus` parses it with a strict line parser: every line of the table must be a vector, a disabled vector, a comment or the terminator, otherwise parsing fails with the line number.
The tests pin the file hash and the vector counts, so a changed file cannot go unnoticed.
`tests/fixtures/blocks/reference/cm7.bin` is the sample block of the same project, vendored the same way.

### Block container layout

A block image is a 36-byte header, the MC7 code (or the body of a data block), the interface, the segment table and a 36-byte footer.
The field list with offsets, and which source documents each field, is in the module docstring of `src/mc7asm/image.py`.
It is derived from two public reverse-engineering projects:

- [DotNetSiemensPLCToolBoxLibrary](https://github.com/dotnetprojects/DotNetSiemensPLCToolBoxLibrary): `MC7Converter.cs`, `Helper.cs` and `S7Block.cs`.
- [rz-libmc7](https://github.com/rizinorg/rz-libmc7): `src/plugin_bin.c` and its sample block.

`mc7asm.image.parse_image` is lossless: `parse_image(data).to_bytes() == data` for every input it accepts.
Three rules keep it that way:

- The local data length at offset 32 is a size only; there is no local-data section in the image.
- Bytes between the declared sections and the footer are kept as a "trailing unknown" region and reported, never dropped.
- The length field at offset 8 is not enforced; a mismatch with the file size is reported as a finding.

One question is open and marked `TODO(real-db-fixture)` in the code.
The references do not settle the layout of data blocks, in particular whether start values are counted in the interface length.
It will be decided from a real DB fixture, not guessed.

### Modules

| Module | State | Responsibility |
| --- | --- | --- |
| `mc7asm.image` | implemented | Typed model of the container: header fields, raw sections, footer fields. |
| `mc7asm.validate` | implemented | Field-level findings: length field, sections that do not fit, unaccounted bytes, unknown codes. |
| `mc7asm.report`, `mc7asm.cli` | implemented | The `mc7asm dump` and `mc7asm disasm` reports. |
| `mc7asm.opcodes` | implemented for decoding | The opcode table as data, with the German spellings. |
| `mc7asm.disasm` | implemented | Table-driven decoder with unknown-opcode reporting. |
| `mc7asm.corpus` | implemented | Typed model and strict parser of the opcode corpus. |
| `mc7asm.lexer`, `mc7asm.parser` | implemented | STL source to tokens to the typed IR, with located syntax errors. |
| `mc7asm.ir`, `mc7asm.source` | implemented | Typed IR: block, network, instruction and operand nodes with source locations. |
| `mc7asm.notation` | implemented | Spelling of typed constants, shared by parser, printer and disassembler. |
| `mc7asm.printer` | implemented | IR back to STL text and the tree of `mc7asm parse`. |
| `mc7asm.codegen` | implemented for straight-line code | IR to MC7 bytes through the opcode table, with length accounting. |
| `mc7asm.container` | interface only | Wrap assembled code into a new block image. |

The interface-only functions raise `NotYetImplementedError`.
A test checks that importing `mc7asm` never loads `mc7`, `snap7` or `socket`.

### Reference corpus

Block fixtures live in `tests/fixtures/blocks`, and every one of them must re-serialize byte for byte.

```bash
uv run python scripts/capture_fixtures.py --fake
```

This writes the synthetic stand-ins `OB1`, `FC1` and `DB1` to `tests/fixtures/blocks/fake`.
They are uploaded from the fake PLC of the test suite, are committed, and a test fails if they differ from what the script produces.

```bash
uv run python scripts/capture_fixtures.py --host 192.168.0.10
```

This uploads OB1, the lowest-numbered FC and the lowest-numbered DB from a real PLC into `tests/fixtures/blocks/real`.
Name the blocks to choose others, for example `OB1 FC5 DB10`.
The capture is read-only: it lists and uploads blocks and does nothing else, which a test enforces.
For each block it prints the section sizes and any finding, which is the information needed to settle the open DB question.
Real blocks contain the program of the machine they come from, so check what you commit.

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
For `mc7asm` it contains the byte-for-byte round trip of every committed block fixture and tests of the image model, the validation and the dump report.
It also runs the whole opcode corpus through the disassembler: every vector must decode to exactly its expected text and length or be reported as unknown, and the count of each is pinned.
The same corpus then goes through the full loop of disassembly, parsing and code generation, and a seeded property test checks that generated code disassembles back to the IR it came from.
`tests/expected_errors` holds one malformed source per syntax error together with the exact message it must produce.

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
