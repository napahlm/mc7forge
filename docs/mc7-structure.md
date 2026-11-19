# MC7 block container: field map

This is the reference for the layout of an S7-300/400 block image as this project understands it.
A block image is what a CPU hands out on a full upload and expects back on a download: a header, the code or data, an interface description, a segment table and a footer.

Every statement below names where it comes from.
Nothing here was taken from Siemens documentation; the format is known from public reverse-engineering projects, from one published block and from three blocks uploaded from a CPU.

## Sources

| Key | Source | Pinned version |
| --- | --- | --- |
| TB | [DotNetSiemensPLCToolBoxLibrary](https://github.com/dotnetprojects/DotNetSiemensPLCToolBoxLibrary): `MC7Converter.cs`, `Helper.cs`, `Parameter.cs`, `NetWork.cs`, `S7Block.cs`, `S7DataRowType.cs`, `PLCLanguage.cs` | commit `734b1413` |
| RZ | [rz-libmc7](https://github.com/rizinorg/rz-libmc7): `src/plugin_bin.c` | commit `111b189a` |
| S7 | [Snap7](https://github.com/davenardella/snap7) 1.4.3: `s7_types.h`, `s7_micro_client.cpp` | read during stage 1 |
| REF | the reference block `tests/fixtures/blocks/reference/cm7.bin`, a real OB1 from rz-libmc7, written in STL | SHA-256 `089f010e...767c29` |
| REAL | `OB1`, `FC1` and `DB1`, uploaded on 2026-11-19 from a CPU 317-2 DP (6ES7 317-2AJ10-0AB0, firmware V2.6.5) with `scripts/capture_fixtures.py`; both code blocks are written in FBD | SHA-256 `d8d1a126...710072`, `021a235d...fbf6f9`, `86e212fb...f4be7f` |
| CPU | what the same CPU answered when asked about these blocks: block information, and the contents of DB1 read as data | read the same day with the `mc7` package |

"Verified" in this document means: checked on the bytes of REF by a test in this repository.
"Seen on REAL" means: observed on the three uploaded blocks, and checked by `tests/test_image_fixtures.py` in every checkout that has them.
The real blocks are part of the program of a running machine and are kept out of the repository for confidentiality; the tests that need them are skipped without them.
This document quotes structural bytes of them only, lengths, sub-headers and segment tables, and never program content or names.
Four blocks are still a thin basis, and each section says how far it reaches.

## Overall layout

```text
+--------+----------------------+-----------+---------------+--------+
| header | code or data         | interface | segment table | footer |
| 36     | u16 at offset 34     | u16 at 28 | u16 at 30     | 36     |
+--------+----------------------+-----------+---------------+--------+
```

- All header fields are big-endian. The interface and the segment table use little-endian words.
- Order of the sections: TB, remarks at the top of `MC7Converter.cs`.
  RZ lists a different order in its section table, but its own sample only adds up in the TB order.
- Verified on REF: 36 + 36 + 28 + 6 + 36 = 142 = length field = file size.
- Seen on REAL: OB1 is 36 + 200 + 28 + 16 + 36 = 316, FC1 is 36 + 724 + 10 + 62 + 36 = 868 and DB1 is 36 + 2220 + 106 + 0 + 36 = 2398.
  Each sum is the length field and the file size, and no byte is left over.
- CPU: the block information reports the same four numbers per block, as load size (offset 8), MC7 size (34), SBB length (28) and local data (32).
- The footer is the last 36 bytes of the image (TB: "always located 36 bytes at the end").
- The local data length at offset 32 is a size only. There are no local data bytes in the image.

## Header

36 bytes, big-endian.
TB and RZ agree on every offset; the S7 column gives the field name in Snap7's `TS7CompactBlockInfo`, which has the same layout.

| Offset | Size | Field | Meaning | S7 name | Value in REF |
| --- | --- | --- | --- | --- | --- |
| 0 | 2 | signature | always `70 70`, the letters "pp" | `Cst_pp` | `70 70` |
| 2 | 1 | block version | meaning unclear according to TB | `Uk_01` | `01` |
| 3 | 1 | attributes | bit flags, see below | `BlkFlags` | `01` |
| 4 | 1 | language | see below | `BlkLang` | `01` |
| 5 | 1 | block type | see below | `SubBlkType` | `08` |
| 6 | 2 | block number | | `BlkNum` | `00 01` |
| 8 | 4 | block length | size of the whole image, "load memory length" in S7 | `LenLoadMem` | `00 00 00 8e` |
| 12 | 4 | password | non-zero means know-how protected (TB) | `BlkSec` | `00 00 00 00` |
| 16 | 6 | last modified | timestamp, see below | `CodeTime_ms`, `CodeTime_dy` | `03 4a 12 28 37 30` |
| 22 | 6 | last interface change | timestamp, see below | `IntfTime_ms`, `IntfTime_dy` | `02 e1 6c 8c 2c 71` |
| 28 | 2 | interface length | length of the interface section | `SbbLen` | `00 1c` |
| 30 | 2 | segment table length | length of the segment table | `AddLen` | `00 06` |
| 32 | 2 | local data length | bytes of local data the block needs | `LocDataLen` | `00 14` |
| 34 | 2 | MC7 length | length of the code, or of the body of a data block | `MC7Len` | `00 24` |

Implemented in `src/mc7asm/image.py` (`BlockHeader`).
The stage-1 communication layer reads the same header in `src/mc7/blocks.py`.

Seen on REAL:

| Field | OB1 | FC1 | DB1 |
| --- | --- | --- | --- |
| block version | `01` | `01` | `01` |
| attributes | `01` | `01` | `01` |
| language | `03` (FBD) | `03` (FBD) | `05` (DB) |
| block length | 316 | 868 | 2398 |
| password | zeros | zeros | zeros |
| interface length | 28 | 10 | 106 |
| segment table length | 16 | 62 | 0 |
| local data length | 28 | 8 | 0 |
| MC7 length | 200 | 724 | 2220 |

### Attributes (offset 3)

Bit values from the `S7BlockAtributes` enum in TB `S7Block.cs`.
RZ reads the byte without naming its bits.

| Bit | Value | Name | Meaning |
| --- | --- | --- | --- |
| 0 | `01` | linked | the block is linked into execution |
| 1 | `02` | standard block | a block of the standard library |
| 3 | `08` | know-how protected | |
| 5 | `20` | non-retain | |
| 6 | `40` | F block | a safety block of a safety PLC |

TB notes that "linked" is clear while a code block has been downloaded but is not yet linked, and for a data block marked "unlinked".
That matches what stage 1 found: a download is only activated by a final insert request.
REF has `01`.
Seen on REAL: all three blocks have `01` and no other bit; they were uploaded from a CPU in RUN.

### Language (offset 4)

| Code | TB `Helper.GetLang` | RZ `mc7_lang` |
| --- | --- | --- |
| 1 | AWL (STL) | STL |
| 2 | KOP (LAD) | LAD |
| 3 | FUP (FBD) | FBD |
| 4 | SCL | SCL |
| 5 | DB | DB |
| 6 | GRAPH | GRAPH |
| 7 | CFC (`PLCLanguage.cs`) | SDB |

The sources agree on 1 to 6 and disagree on 7.
TB `PLCLanguage.cs` also lists 8 (SFC) and 31 to 35 (FAWL, FKOP, FFUP, FDB, FCALL).
`mc7asm` names 1 to 6 and prints every other code as a number.
Seen on REAL: `03` on both code blocks, whose code has the `BLD` and `NOP 0` instructions a graphical editor generates, and `05` on the data block.

### Block type (offset 5)

| Code | Type | Code used in block names on the wire |
| --- | --- | --- |
| `08` | OB | `38` ("8") |
| `0A` | DB | `41` ("A") |
| `0B` | SDB | `42` ("B") |
| `0C` | FC | `43` ("C") |
| `0D` | SFC | `44` ("D") |
| `0E` | FB | `45` ("E") |
| `0F` | SFB | `46` ("F") |

The header codes are the same in TB `Helper.GetPLCBlockType`, RZ `mc7_type` and S7 `SubBlk_*`.
The wire codes are S7 `Block_*`; the upload and download requests of the communication layer use them (`src/mc7/blocks.py`, `src/mc7/transfer.py`).
A test checks that both packages hold the same header codes.

### Timestamps (offsets 16 and 22)

Six bytes: a big-endian u32 of milliseconds since midnight, then a big-endian u16 of days since 1984-01-01.
Sources: RZ `mc7_parse_s7_date`, TB `Helper.GetDT`, and the split into `_ms` and `_dy` fields in S7.
Verified on REF: the two fields decode to 2022-09-06 15:19:45.960 and 2015-02-24 13:25:27.820.
The range is 1984-01-01 to 2163-06-06.
Seen on REAL: all six timestamps decode to valid dates between 1996 and 2011, and no interface change is later than the code change of the same block.
The interface of OB1 is dated 1996-02-15 16:51:12.780, years before the block was last modified; that looks like the date of the template the OB was created from, which is an interpretation.

## Code section

The code starts at offset 36 and its length is the u16 at offset 34.
The instruction encoding is documented in [opcodes.md](opcodes.md).

**The code ends with `BE` (`65 00`), and those two bytes are part of the MC7 length.**
REF ends this way, and TB `MC7Converter.cs` passes `CodeSize - 2` to its decoder, because STEP 7 does not show that instruction.
The source of a block therefore does not contain it; `mc7asm.container` appends it.
Seen on REAL: OB1 and FC1 both end with `65 00`, and in both the network lengths of the segment table add up to the code length minus these two bytes.
So the closing `BE` lies behind the last network, which is where the builder puts it.

For a data block the same position holds the current values of the block instead of code, see [Data blocks](#data-blocks).

## Interface

The interface follows the code.
The 28 bytes of REF:

```text
01  00 00  14 00  00 00  02 05 02 05 02 05 02 05 02 05 02 05  05 05 05 05 05 05  0e 05  20
```

| Offset in section | Size | Field | Value in REF | Source |
| --- | --- | --- | --- | --- |
| 0 | 1 | kind of block | `01`: code block | TB `MC7Converter.cs` comment; `05` for a DB, `0a` for an instance DB according to its code |
| 1 | 2 | a word TB calls the block number, little-endian | `00 00` | TB comment: "Zero on OB"; the FB number for an instance DB |
| 3 | 2 | length of the declarations, little-endian | `14 00` = 20 | TB reads this word at section offset 3 |
| 5 | 2 | length of the start values, little-endian | `00 00` | TB: "Start Value Length"; only FBs and DBs have start values |
| 7 | 20 | declarations, two bytes each | see below | TB `Parameter.cs` starts parsing at byte 7 |
| 27 | 1 | closing byte | `20` | not explained by any source |

Seen on REAL, the interface of OB1, of FC1, and the start of the interface of DB1:

```text
01 00 00 14 00 00 00 02 05 02 05 02 05 02 05 02 05 02 05 05 05 05 05 05 05 0e 05 3a
```

```text
01 00 00 02 00 00 00 05 05 50
```

```text
05 01 00 62 00 00 00 11 04 08 11 04 07 01 04
```

| Block | Kind | Word at 1 | Declarations | Start values | Bytes after them |
| --- | --- | --- | --- | --- | --- |
| REF, OB1 | `01` | 0 | 20 | 0 | 1: `20` |
| REAL OB1 | `01` | 0 | 20 | 0 | 1: `3a` |
| REAL FC1 | `01` | 0 | 2 | 0 | 1: `50` |
| REAL DB1 | `05` | 1 | 98 | 0 | 1: `49` |

- The kind byte is `05` for the data block, as TB says.
- The word at offset 1 is zero in FC1 as well, so for a code block it is not the block number.
  It is 1 in DB1; one data block cannot tell whether that is its own number.
- The declarations length is exact in all four blocks, see below.
- No block has start values.

Each declaration is a data type followed by a declaration kind.

| Data type | Code | | Declaration kind | Code |
| --- | --- | --- | --- | --- |
| BOOL | `01` | | IN | `01` |
| BYTE | `02` | | OUT | `02` |
| CHAR | `03` | | IN_OUT | `03` |
| WORD | `04` | | STATIC | `04` |
| INT | `05` | | TEMP | `05` |
| DWORD | `06` | | RET | `06` |
| DINT | `07` | | | |
| REAL | `08` | | | |
| DATE | `09` | | | |
| TIME_OF_DAY | `0A` | | | |
| TIME | `0B` | | | |
| S5TIME | `0C` | | | |
| DATE_AND_TIME | `0E` | | | |

Data types from TB `S7DataRowType.cs`, kinds from the `ParameterType` enum in TB `Parameter.cs`.
`Parameter.cs` also defines variants of each kind with `08` added (with a start value) and `10` added.
Structured types take more than two bytes; they are not covered here.

Verified on REF: the ten declarations are six BYTE, three INT and one DATE_AND_TIME, all TEMP.
These are the start information of an OB1, 6 + 6 + 8 = 20 bytes, which is exactly the local data length in the header.

Seen on REAL:

- OB1 has the same ten declarations and a local data length of 28.
  Its code uses the local bytes 20 to 27 for the parameters of block calls, so the header field is the declared variables plus what the compiler added.
- FC1 declares one INT as TEMP, 2 bytes, and has a local data length of 8; its code uses local bytes up to 6.
- DB1 uses structured types.
  A structure is `11`, the kind, the number of members and then the members.
  An array is `10`, the kind, the number of dimensions, a low and a high bound per dimension as little-endian words, and then the element type.
  Read this way the 98 declaration bytes are used up exactly, and they describe 2220 bytes of data, which is the length of the body of DB1.
  All its declarations have the kind STATIC.

The closing byte lies outside the declared length and TB never reads it.
In all four blocks exactly one byte follows the declarations.
The two OB1 have the same sub-header and the same declarations and different closing bytes, so the byte is not computed from the interface.
All four declaration lengths are even, so these blocks cannot tell padding to an even section length from a terminator.

`mc7asm` reads the sub-header of a parsed block (`InterfaceHeader`, `split_interface` in `src/mc7asm/image.py`) and keeps the declarations as raw bytes.
The builder writes this structure, see [container.md](container.md).

## Segment table

The segment table follows the interface.
TB calls it the table of network lengths and reads it at 36 + code length + interface length.
The 6 bytes of REF:

```text
01 00  22 00  00 00
```

Read as little-endian words: 1, 34, 0.
REF has one network, and 34 is its code length without the closing `BE`.

Seen on REAL, the 16 bytes of OB1, which has five networks and 200 bytes of code:

```text
05 00 28 00 28 00 58 00 10 00 0e 00 00 00 55 00
```

Words: 5, then 40, 40, 88, 16 and 14, which add up to 198, then 0 and 85.

FC1 has 19 networks and 724 bytes of code.
Its table starts with 19 and 19 lengths that add up to 722, and ends with these 22 bytes:

```text
09 00 01 00 0d 00 3a 01 50 00 bf 00 d4 00 e9 00 fe 00 25 01 3c 01
```

Words: 9, then 1, 13, 314, 80, 191, 212, 233, 254 and 293, then 316.
The nine words after the 9 are the positions of the nine `JNB` instructions of FC1 (`ff 98`), counted in words from the start of the code.
Its three `JU` (`70 0b`), which belong to block calls, are not in the list.

So the table reads:

1. the number of networks,
2. one length per network, in bytes, the closing `BE` not included,
3. a count of jump positions and that many positions, zero in REF and in OB1,
4. one more word in the two FBD blocks (85 and 316), which REF does not have.

Parts 1 and 2 settle what one single-network block could not.
The reading of TB `NetWork.GetNetworks`, a count N followed by N-1 lengths, does not fit: it would lose a network.

Not known: what the last word means, why the `JU` of a call are not listed while the `JNB` are (a `JNB` has a label in the source, which is an interpretation), and whether a block written in STL carries the same parts.
REF is the only STL block, and it has one network and no jump.

`mc7asm` keeps the table of a parsed block raw and derives no network boundaries from it.
The builder writes parts 1 to 3 with a zero count, which is exactly REF.
It cannot generate jumps yet; when it can, their positions belong here.

## Footer

The last 36 bytes of the image.
Only TB parses it (`ParseBlockHeaderAndFooterFromMC7`); RZ stops after the header.

| Offset in footer | Size | Field | Meaning | Value in REF | Seen on REAL |
| --- | --- | --- | --- | --- | --- |
| 0 | 8 | author | text | zeros | text in FC1 and DB1, padded with zero bytes; zeros in OB1 |
| 8 | 8 | family | text | zeros | text in FC1, zeros in the others |
| 16 | 8 | name | text, called "Header" in S7 | zeros | text in FC1, zeros in the others |
| 24 | 1 | version | high nibble major, low nibble minor (TB `Helper.GetVersion`) | `10` | `01` in all three, version 0.1 |
| 25 | 1 | unknown | not parsed by any source | `00` | `00` |
| 26 | 2 | checksum | algorithm not documented by any source | `4d e5` | non-zero in OB1 and FC1, `00 00` in DB1 |
| 28 | 8 | unknown | not parsed by any source | zeros | zeros |

S7 describes a 56-byte `TS7BlockFooter`.
Its last 36 bytes are exactly this footer, and its first 20 bytes overlap whatever precedes it, in REF the end of the interface and the segment table.
The stage-1 test blocks originally used the 56-byte form and were corrected in stage 2.0.

**Checksum.**
No source says how it is computed.
`mc7asm` never computes, verifies or corrects it: a parsed block keeps its value, a built block gets zero.
Snap7 sets the field to zero before it downloads a block (`opDownload` in `s7_micro_client.cpp`).

Seen on REAL and CPU: for OB1 and FC1 the footer checksum is the checksum the CPU reports in its block information.
For DB1 the CPU reports a non-zero checksum, and the uploaded image has zero.
The body of an uploaded DB is its current values, so the checksum of the loaded block would not describe it.

## Data blocks

Settled by the real DB1, except for start values.

**The body at offset 36 holds the current values, and the field at offset 34 is its length.**
Three observations, independent of each other:

- The declarations in the interface describe 2220 bytes, and the field is 2220.
- The CPU lets one read DB1 as data up to byte 2219 and refuses byte 2220.
- The body holds records with a time that the running program keeps rewriting.
  Two uploads a few minutes apart are identical in header, interface and footer and differ in those time bytes only, by the time that had passed on the clock of the CPU.
  The block was last modified years before the times in its body, so these are not the values it was loaded with.

**The field at offset 28 is the length of the interface section**, as for a code block.
In DB1 that is 106 bytes: the 7-byte sub-header with the kind `05`, 98 bytes of declarations and one closing byte.

A data block has no segment table and no local data; both fields are zero in DB1, and no byte is left over.
Its footer checksum is zero, see above.

This is what the code of TB does.
The comment in TB's header description gives the two fields a second meaning for data blocks, "DB body (actual values part) length" at offset 28 and "definitions/initial values" at offset 34, and that is not what a block from a CPU shows.

**Still open: start values.**
The sub-header word at offset 5 is zero in DB1 and in the three other blocks, and none of them has bytes that could be start values.
TB reads them behind the declarations, inside the interface section; `split_interface` follows that, but no block has shown it.
A block whose sub-header declares start values would settle where they are and whether the field at offset 28 counts them.
`validate_image` reports such a block with the code `start-values`, so a capture that contains one says so.
This is what is left of `TODO(real-db-fixture)` in `src/mc7asm/image.py`.

`mc7asm`:

- parses a DB like any block and keeps bytes it cannot place as "trailing unknown",
- does not build data blocks,
- refuses to disassemble them, because their body is values.

An uploaded DB is a snapshot: DB1 changed between two uploads, so the same capture cannot be reproduced.

## Reading real blocks

A block read from a PLC may not follow this map exactly, so the reader is tolerant and loses nothing.

- `parse_image(data).to_bytes() == data` holds for every image that has the signature and at least 72 bytes.
- Bytes between the declared sections and the footer are kept as a "trailing unknown" region.
- A length field that differs from the file size is reported, not rejected: as an error for an OB, FC or FB, as a warning for other blocks.
  It is the file size in REF and in all three real blocks, and the CPU reports the same number as the load size.
- Sections whose declared lengths do not fit are left raw.
- An interface that is shorter than its sub-header says is reported and left raw.

`validate_image` reports these as findings.
For images that `mc7asm` builds itself, `validate_generated_image` turns every one of them into an error, see [container.md](container.md).

## What is verified, and by what

| Fact | Evidence |
| --- | --- |
| Header offsets and sizes | TB and RZ agree; all 14 fields of REF decode to plausible values (`tests/test_image_fixtures.py`) |
| Section order and the length equation | REF adds up exactly; a rebuilt REF has identical bytes (`tests/test_end_to_end.py`); REAL adds up exactly for an OB, an FC and a DB |
| Length field = file size | REF and REAL; the CPU reports the same number as load size |
| Timestamp encoding | both timestamps of REF decode to valid dates |
| Code ends with `BE`, counted in the code length | REF; TB decodes `CodeSize - 2`; REAL OB1 and FC1 |
| Interface sub-header and declaration pairs | TB code; REF decodes to the ten temporary variables of OB1, matching its local data length; the declarations length is exact in REAL OB1, FC1 and DB1 |
| Segment table for one network | REF; rebuilt identically |
| Network count and one length per network | REAL OB1 with 5 and FC1 with 19 networks; the lengths add up to the code without `BE` |
| A DB body is the current values, in the declared size | REAL DB1 and what the CPU answers, see [Data blocks](#data-blocks) |
| Footer position and fields | TB; REF rebuilt identically except the checksum; the checksum of REAL OB1 and FC1 is the one the CPU reports |
| The image survives a round trip through this code | every fixture re-serializes byte for byte |

## Open questions

- Start values of a data block: where they are, and whether the interface length counts them.
- The byte after the declarations in the interface: `20`, `3a`, `50` and `49` so far.
- The word at interface offset 1: zero in the code blocks, 1 in DB1.
- The segment table behind the network lengths: the last word of the FBD blocks, and what an STL block with jumps or with several networks has there.
- The block version byte at offset 2 and the footer bytes at 25 and 28.
- The checksum algorithm, and whether a CPU accepts a zero checksum on download.
- Whether "linked" should be set in a block that is about to be downloaded.
- The interface of an FB, of an instance DB and of OBs other than OB1.

Answered by the real blocks since the first version of this document: the meaning of the fields 28 and 34 for a DB, the segment table for more than one network, and the interface of an FC.

Each open item needs a real block, or a real CPU, to answer.
`scripts/capture_fixtures.py` exists to bring such blocks into `tests/fixtures/blocks/real`.
