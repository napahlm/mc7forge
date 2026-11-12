# Block container

This document describes how `mc7asm build` wraps compiled MC7 code into a block image, and what each byte it writes is based on.
The field layout itself is documented in the module docstring of `src/mc7asm/image.py`.

## Design rule

`mc7asm.container` is pure.
It takes compiled code and a timestamp and returns a block image; it reads and writes no file and imports nothing from the `mc7` communication package.
The command `mc7asm build` writes exactly one file, the one it is given.
Building a block and loading it into a CPU are separate concerns: loading is `mc7 download`, which asks for confirmation and verifies the block afterwards.

## The reference block, decoded

`tests/fixtures/blocks/reference/cm7.bin` is a real OB1 of 142 bytes and the working example of a minimal organization block.

| Offset | Bytes | Meaning |
| --- | --- | --- |
| 0 | `70 70` | signature |
| 2 | `01` | block version |
| 3 | `01` | attributes: linked |
| 4 | `01` | language: STL |
| 5 | `08` | block type: OB |
| 6 | `00 01` | block number 1 |
| 8 | `00 00 00 8e` | block length 142 |
| 12 | `00 00 00 00` | password: none |
| 16 | `03 4a 12 28 37 30` | last modified: 2022-09-06 15:19:45.960 |
| 22 | `02 e1 6c 8c 2c 71` | last interface change: 2015-02-24 13:25:27.820 |
| 28 | `00 1c` | interface length 28 |
| 30 | `00 06` | segment table length 6 |
| 32 | `00 14` | local data length 20 |
| 34 | `00 24` | code length 36 |
| 36 | 36 bytes | code: 15 instructions, the last one `65 00` (`BE`) |
| 72 | 28 bytes | interface, see below |
| 100 | `01 00 22 00 00 00` | segment table, see below |
| 106 | 36 bytes | footer, see below |

The sum 36 + 36 + 28 + 6 + 36 = 142 equals the length field and the file size.

### Interface

```text
01  00 00  14 00  00 00  02 05 02 05 02 05 02 05 02 05 02 05  05 05 05 05 05 05  0e 05  20
```

| Bytes | Meaning | Source |
| --- | --- | --- |
| `01` | marks the interface of a code block | `MC7Converter.cs` comment on code blocks |
| `00 00` | block number, little-endian, zero for an OB | same comment: "Zero on OB" |
| `14 00` | length of the declarations, little-endian: 20 | `MC7Converter.cs` reads this word at interface offset 3 |
| `00 00` | length of the start values, little-endian: none | `MC7Converter.cs`, "Start Value Length" at offset 5 |
| 20 bytes | ten declarations of two bytes: data type, then declaration kind | `Parameter.cs` starts at byte 7 and reads these pairs |
| `20` | one closing byte | not explained by any source |

The ten declarations are six `02 05`, three `05 05` and one `0e 05`.
In `S7DataRowType.cs` 0x02 is BYTE, 0x05 is INT and 0x0E is DATE_AND_TIME; in `Parameter.cs` the kind 0x05 is TEMP.
These are the ten temporary variables of an OB1, its start information, and they add up to 6 + 6 + 8 = 20 bytes, which is the local data length in the header.

The closing byte is not covered by the declared length of 20 and the C# reader never looks at it.
It may be padding to an even length or a terminator.
Both readings give the same result for a block without declarations: seven header bytes plus this one byte.

### Segment table

```text
01 00  22 00  00 00
```

Read as little-endian words: 1 network, 34 bytes, 0.
34 is the code length without the closing `BE`.
`NetWork.cs` of the C# library reads the first word as a count and the following words as network lengths.
The layout for more than one network is not confirmed by a real block; [opcodes.md](opcodes.md) lists the candidate readings.

### Footer

All 36 bytes are zero except the version byte `10` at footer offset 24 and the checksum `4d e5` at offset 26.
Author, family and name are empty.

## What the builder writes

| Part | Value | Basis |
| --- | --- | --- |
| Signature, block version, attributes, language | `70 70`, `01`, `01` (linked), `01` (STL) | copied from the reference block |
| Block type and number | from the source | |
| Password | zero | the reference block |
| Timestamps | the build time, or `--timestamp`; milliseconds since midnight and days since 1984-01-01 | layout verified on the reference block |
| Code | the compiled body, plus `65 00` unless the source ends with `BE` | see "Block end" |
| Code length | length of the code including the `BE` | the reference block |
| Interface, OB | the 28 bytes of the reference block | copied |
| Interface, FC and FB | `01`, block number little-endian, no declarations, closing `20` | generalized |
| Local data length | 20 for an OB, 0 for an FC or FB without declarations | reference block; generalized for FC and FB |
| Segment table | count, one length per network without the `BE`, zero word | confirmed for one network |
| Footer | empty names, version `10`, checksum 0 | the reference block, except the checksum |
| Block length | the size of the finished image | |

### Block end

The code section of a block ends with `BE` (`65 00`), and those two bytes are part of the code length at offset 34.
The reference block ends this way, and `MC7Converter.cs` hands `CodeSize - 2` bytes to its decoder, because STEP 7 does not show that instruction.
So the closing `BE` does not belong in the source: the code generator emits exactly the source and the container appends `65 00`.
A source that ends with `BE` anyway is left as it is.
The check looks at the last instruction and not at the last two bytes, so `L W#16#6500` at the end of a block is not mistaken for it.

### Checksum

The footer checksum is written as zero.
No source documents its algorithm, so it is never computed, verified or corrected, and a parsed block keeps whatever value it had.
The Snap7 client sets the field to zero before it downloads a block, which is why zero is the value chosen here.

## What is confirmed and what is generalized

Confirmed by a real block: building `examples/reference_ob1.awl` with the timestamps of `cm7.bin` gives the same 142 bytes, except for the two checksum bytes.
That covers the header, the code with its closing `BE`, the OB interface, the single-network segment table and the footer layout.

Generalized, and reported by `mc7asm build` as a note:

- the interface and the local data length of an FC or FB,
- the declarations of an OB other than OB1, which gets the temporary variables of OB1,
- the segment table of a block with more than one network.

Not decided by any source:

- whether a CPU accepts a zero checksum on download; Snap7's behaviour suggests it does,
- whether the attribute byte should say "linked" in a block that is about to be downloaded.

No block built by `mc7asm` has been loaded into a CPU.

## Validation before writing

`mc7asm build` serializes the image, parses those bytes again and runs `validate_generated_image` on the result.
If anything is reported, nothing is written.
The checks are:

- length field at offset 8 = file size = 36 + code length + interface length + segment table length + 36, with no unaccounted bytes,
- the attribute byte has only documented bits, the language code is a known one, and the block type is OB, FC or FB,
- the code section ends with `65 00`.

The checksum is not part of the validation.
Blocks read from a PLC are not held to this profile: for them `validate_image` keeps its tolerance, so unaccounted bytes stay a note and a length mismatch stays a warning.

## Out of scope

Data blocks are not built.
Their layout is still open until a real DB fixture exists, see `TODO(real-db-fixture)` in `src/mc7asm/image.py`.
Declaration sections in source are a syntax error, so a built FC or FB has no parameters or local variables.
