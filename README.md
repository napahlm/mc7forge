# mc7

An open-source toolchain for the Siemens S7-300, in two packages.

- `mc7` is a library and CLI for talking to the PLC over ISO-on-TCP (RFC 1006, TCP port 102).
  It targets a CPU 317-2 DP reached through a CP 343-1 Ethernet module and is built on [python-snap7](https://github.com/gijzelaerr/python-snap7).
- `mc7asm` is the start of an STL to MC7 assembler.
  It compiles straight-line STL source into complete code blocks, and dumps and disassembles block files.
  It is pure software, works on files only and never talks to a PLC.
  See [mc7asm](#mc7asm-the-assembler-toolchain).

The communication layer provides:

- Connect by IP at rack 0, slot 2, with clean connect/disconnect and context-manager support.
- Read and write inputs (I), outputs (Q) and bit memory (M) by address.
- Read and write data blocks with typed helpers (BOOL, BYTE, WORD, INT, DWORD, DINT, REAL, STRING).
- Read the CPU state and identity, and start or stop the CPU where it permits that.
- Upload blocks to local files and send a block file back unchanged as a round-trip integrity check.

## Verification status

Read this before pointing the tool at a machine.

- Everything is tested against a mocked snap7 client, against python-snap7's built-in S7 server over real TCP, and against a fake PLC in `tests/support.py` that implements block upload and download.
- The reading side has been run against one physical station: a CPU 317-2 DP (6ES7 317-2AJ10-0AB0, firmware V2.6.5) behind a CP 343-1, in RUN.
  Connecting, identity and state, the block list, block upload and reads of inputs, outputs, bit memory and a data block worked, and the three read-only integration tests pass.
- Nothing that writes has been run against a physical S7-300: no write to memory, no download, no start or stop.
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

## mc7asm: the assembler toolchain

`mc7asm` turns STL source into S7-300 block images and takes block images apart again.
It works on files only.

### Scope

**This toolchain compiles and validates. It does not load anything onto a PLC.**
Loading a block is the job of the stage-1 transfer module, `mc7 download`, and it is run deliberately by the operator: it asks for confirmation, sends the file and verifies the result.
`mc7asm` never imports the communication package, and a test enforces that.

No block built by `mc7asm` has been loaded into a CPU yet.
The layout it writes reproduces one published block and was compared with three blocks uploaded from a CPU; see [Verification](#verification) for what that covers.

### Usage

Build a block image from source:

```bash
mc7asm build examples/reference_ob1.awl -o OB1.mc7
```

```text
examples/reference_ob1.awl: OB1, 142 bytes -> OB1.mc7
  code 36 bytes (BE appended), interface 28, segment table 6, local data 20
```

`build` compiles the source, appends the closing `BE`, wraps the code into a block image and validates the bytes it is about to write.
If the validation reports anything, nothing is written.
`--timestamp 2024-01-01T00:00:00` fixes the time stored in the header, which makes a build reproducible.

Look at a block image, built or uploaded:

```bash
mc7asm dump OB1.mc7
```

```bash
mc7asm disasm OB1.mc7
```

```text
OB1.mc7: OB1, 36 bytes of MC7 code

  offset  bytes        instruction
  0x0024  c1 00        A I 0.1
  0x0026  49 30 00 00  FP M 0.0
  ...
  0x0046  65 00        BE

Coverage: 36 of 36 code bytes decoded, 0 unknown

Findings
  none
```

`dump` prints every header and footer field with offset, raw bytes and meaning, and a hex dump of each section.
`disasm` lists the instructions; bytes it does not know appear as `?? unknown opcode` and again under the findings.

Inspect the earlier steps of the pipeline:

```bash
mc7asm parse examples/blink.awl
```

```bash
mc7asm parse examples/blink.awl --show-tokens
```

```bash
mc7asm compile examples/blink.awl -o blink.body
```

`parse` prints the typed intermediate representation with the source location of every node, `compile` writes the raw MC7 code without a container.

`build`, `compile`, `parse` and `disasm` take `--mnemonics de` for German spelling (`U E 0.0`, `= A 0.0`, `ZV Z 1`).

### Supported subset

A source file holds one block: `ORGANIZATION_BLOCK OB n`, `FUNCTION FC n : VOID` or `FUNCTION_BLOCK FB n`, then `BEGIN`, networks with optional titles and comments, and the matching `END_...`.

| Statements | Operands |
| --- | --- |
| `A`, `AN`, `O`, `ON`, `=`, `S`, `R`, `FP`, `FN` | a bit: `I 0.0`, `Q`, `M`, `L`, `DBX`, `DIX` |
| `L`, `T` | a byte, word or double word: `MW 10`, `QD 4`, `DBW 2`, `PIW 256` and so on |
| `L` | a constant: `100`, `L#100000`, `1.5`, `W#16#1F`, `DW#16#...`, `2#1010`, `'AB'`, `B#(1, 2)`, `C#100`, `D#2024-12-31`, `S5T#2S`, `T#1500MS`, `TOD#8:30:0.000` |
| `CU`, `CD`, `LC` | a counter: `C 1` |

[examples/](examples/README.md) has one source per feature with the image it builds to.

Limits:

- **Straight-line code only.** There are no jumps, labels, calls, timers or arithmetic yet.
- **No declarations.** Declaration sections are a syntax error, so every operand is an absolute address and a built FC or FB has no parameters.
- **Parsed but not compiled.** Parentheses (`A(` ... `)`), fully qualified data block addresses (`DB1.DBX 0.0`) and `TRUE`/`FALSE` are accepted by the parser and refused by the code generator with "not yet supported".
- **`L B#16#...` is refused.** The two sources disagree on what its text means, and refusing beats silently emitting the wrong byte.
- **Code blocks only.** Data blocks are not built; their layout is not settled.
- **Real numbers** are printed with six decimals, so disassembling and reassembling is exact only for values six decimals can represent.
- **The disassembler knows 156 instruction forms.** Everything else is reported as unknown, and after the first unknown opcode the instruction boundaries are not certain.

Syntax errors name the file, line and column, the offending text and a hint.

### Verification

Everything is checked without hardware, against two external references and three blocks that were uploaded from a CPU once.

- **The opcode corpus**: the decoder test table of rz-libmc7, 2,531 vectors of bytes, expected text and expected length.
  Every vector must decode to exactly its text or be reported as unknown; 718 decode.
  Each of those then goes through parsing and code generation, and 714 come back byte for byte.
  The other four are listed with their reasons in the [decision log](docs/decisions.md).
- **The reference block**: `cm7.bin`, a real OB1 from the same project.
  It decodes completely, and building its program from source reproduces it byte for byte except for the two checksum bytes.
- **Real blocks**: an OB1, an FC1 and a DB1 uploaded from a CPU 317-2 DP.
  They parse without a finding and add up exactly, and they settled several open layout questions; the [field map](docs/mc7-structure.md) marks each such statement.
  Both code blocks were written in FBD, and most of their code is outside the instruction table: 46% of the OB1 and 14% of the FC1 decode, see [opcodes.md](docs/opcodes.md#coverage-on-real-blocks).
- **The examples**: every example builds to its committed image, validates, disassembles without unknown opcodes and reassembles to the same code.

What this does not cover:

- No built block has been loaded into a CPU.
- The checksum is written as zero, because its algorithm is not documented; whether a CPU accepts that is open.
- An FC or FB without declarations, OBs other than OB1 and the end of the segment table of a block with several networks go beyond what any real block shows. `mc7asm build` prints a note in each of these cases.
- Data blocks are read, not built.
- If Rizin's `rz-asm` with the mc7 plugin is installed, the tests also disassemble the example code with it and compare; without it that check is skipped.

### Fixtures and how they were obtained

| Fixture | Where | How it got there |
| --- | --- | --- |
| Opcode corpus | `tests/fixtures/corpus/test_simatic.c` | copied verbatim from rz-libmc7 at a pinned commit, LGPL-3.0-only, hash checked by a test |
| Reference block | `tests/fixtures/blocks/reference/cm7.bin` | copied verbatim from rz-libmc7, same commit and licence |
| Synthetic blocks | `tests/fixtures/blocks/fake/` | uploaded from the fake PLC of the test suite with `scripts/capture_fixtures.py --fake` |
| Real blocks | `tests/fixtures/blocks/real/`, not in this repository | `OB1`, `FC1` and `DB1` of a CPU 317-2 DP, uploaded read-only with `scripts/capture_fixtures.py --host <ip>` |
| Example images | `examples/expected/` | built with `scripts/build_examples.py` at a fixed timestamp |
| Golden listings | `tests/fixtures/golden/` | output of `mc7asm` on the fixtures, reviewed and committed |

The capture script only lists and uploads blocks.

**The real fixtures exist, and they are kept out of this repository for confidentiality.**
They come from a CPU that runs a real application: they carry author marks and live operational data, so `tests/fixtures/blocks/real/` is in `.gitignore`.
The test suite is green both ways: with the blocks in place it holds them to the documented layout, and without them those tests are skipped and everything else runs.
What they showed is written down in the [field map](docs/mc7-structure.md), which quotes structural bytes only (lengths, sub-headers, segment tables) and never program content or names.
To get fixtures of your own, run the capture script against your PLC; real blocks contain the program of the machine they come from, so check what you commit.
The synthetic blocks predate the decoding of the reference block and are structural stand-ins for the parser tests, not models of a real block.

### Documentation

| Document | Content |
| --- | --- |
| [docs/mc7-structure.md](docs/mc7-structure.md) | The block container: every field with offset, meaning and provenance, and the open questions. |
| [docs/opcodes.md](docs/opcodes.md) | The instruction encodings, the cross-check of the two sources and the provenance of every opcode row. |
| [docs/assembler.md](docs/assembler.md) | The source subset, the intermediate representation, syntax errors and the code generator. |
| [docs/container.md](docs/container.md) | What `mc7asm build` writes, what is confirmed and what is generalized, and the validation before writing. |
| [docs/decisions.md](docs/decisions.md) | The decision log: why the toolchain behaves as it does. |
| [examples/README.md](examples/README.md) | One example per feature with its expected image. |

### Modules

| Module | Responsibility |
| --- | --- |
| `mc7asm.image` | Typed, lossless model of the container: header fields, raw sections, footer fields. |
| `mc7asm.validate` | Findings for real blocks, and the strict profile for built ones. |
| `mc7asm.corpus` | Typed model and strict parser of the opcode corpus. |
| `mc7asm.opcodes` | The opcode table as data, with the German spellings. |
| `mc7asm.notation` | Spelling of typed constants, shared by parser, printer and disassembler. |
| `mc7asm.disasm` | Table-driven decoder with unknown-opcode reporting. |
| `mc7asm.lexer`, `mc7asm.parser` | STL source to tokens to the typed IR, with located syntax errors. |
| `mc7asm.ir`, `mc7asm.source` | The IR: block, network, instruction and operand nodes with source locations. |
| `mc7asm.codegen` | IR to MC7 bytes through the opcode table, with length accounting. |
| `mc7asm.container` | Compiled code to a block image, closing it with `BE`. Pure, no I/O. |
| `mc7asm.printer`, `mc7asm.report`, `mc7asm.cli` | IR back to source, the reports, and the `mc7asm` command. |

## Safety

Writing outputs or bit memory, downloading blocks and stopping or starting the CPU change what the machine does.
Only use these on equipment you are responsible for, when it is in a safe state.
A block built by `mc7asm` is new program code that no CPU has run yet; download the first ones only where a wrong block does no harm.
Single-bit writes use the S7 bit transport, so the CPU changes only the addressed bit and neighbouring bits are never rewritten.

## Testing

```bash
uv run pytest
```

The default run needs no hardware.
It contains unit tests against a mocked snap7 client, end-to-end tests over TCP against python-snap7's S7 server, and end-to-end block transfer tests against the fake PLC.
For `mc7asm` it contains the byte-for-byte round trip of every block fixture and tests of the image model, the validation and the dump report.
Blocks that came from a CPU, the reference block and the real captures where present, are also held to the documented layout: exact lengths, the closing `BE` behind the last network, and the interface sub-header.
It also runs the whole opcode corpus through the disassembler: every vector must decode to exactly its expected text and length or be reported as unknown, and the count of each is pinned.
The same corpus then goes through the full loop of disassembly, parsing and code generation, and a seeded property test checks that generated code disassembles back to the IR it came from.
`tests/expected_errors` holds one malformed source per syntax error together with the exact message it must produce.
End-to-end tests take every example from source to image and back: build, validate, disassemble, reassemble, and compare with the committed image field for field.
The documentation is tested as well: its field tables are checked against the code and the reference block, its numbers against the corpus, and its links against the files.

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
