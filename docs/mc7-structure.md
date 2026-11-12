# MC7 block container: field map

This is the reference for the layout of an S7-300/400 block image as this project understands it.
A block image is what a CPU hands out on a full upload and expects back on a download: a header, the code or data, an interface description, a segment table and a footer.

Every statement below names where it comes from.
Nothing here was taken from Siemens documentation; the format is known from public reverse-engineering projects and from one real block.

## Sources

| Key | Source | Pinned version |
| --- | --- | --- |
| TB | [DotNetSiemensPLCToolBoxLibrary](https://github.com/dotnetprojects/DotNetSiemensPLCToolBoxLibrary): `MC7Converter.cs`, `Helper.cs`, `Parameter.cs`, `NetWork.cs`, `S7Block.cs`, `S7DataRowType.cs`, `PLCLanguage.cs` | commit `734b1413` |
| RZ | [rz-libmc7](https://github.com/rizinorg/rz-libmc7): `src/plugin_bin.c` | commit `111b189a` |
| S7 | [Snap7](https://github.com/davenardella/snap7) 1.4.3: `s7_types.h`, `s7_micro_client.cpp` | read during stage 1 |
| REF | the reference block `tests/fixtures/blocks/reference/cm7.bin`, a real OB1 from rz-libmc7 | SHA-256 `089f010e...767c29` |

"Verified" in this document means: checked on the bytes of REF by a test in this repository.
One real block is a thin basis, and each section says how far it reaches.

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

## Code section

The code starts at offset 36 and its length is the u16 at offset 34.
The instruction encoding is documented in [opcodes.md](opcodes.md).

**The code ends with `BE` (`65 00`), and those two bytes are part of the MC7 length.**
REF ends this way, and TB `MC7Converter.cs` passes `CodeSize - 2` to its decoder, because STEP 7 does not show that instruction.
The source of a block therefore does not contain it; `mc7asm.container` appends it.

For a data block the same position holds the current values of the block instead of code (TB).

## Interface

The interface follows the code.
The 28 bytes of REF:

```text
01  00 00  14 00  00 00  02 05 02 05 02 05 02 05 02 05 02 05  05 05 05 05 05 05  0e 05  20
```

| Offset in section | Size | Field | Value in REF | Source |
| --- | --- | --- | --- | --- |
| 0 | 1 | kind of block | `01`: code block | TB `MC7Converter.cs` comment; `05` for a DB, `0a` for an instance DB according to its code |
| 1 | 2 | block number, little-endian | `00 00` | TB comment: "Zero on OB"; the FB number for an instance DB |
| 3 | 2 | length of the declarations, little-endian | `14 00` = 20 | TB reads this word at section offset 3 |
| 5 | 2 | length of the start values, little-endian | `00 00` | TB: "Start Value Length"; only FBs and DBs have start values |
| 7 | 20 | declarations, two bytes each | see below | TB `Parameter.cs` starts parsing at byte 7 |
| 27 | 1 | closing byte | `20` | not explained by any source |

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

The closing byte lies outside the declared length and TB never reads it.
It may be padding to an even length or a terminator; one block cannot tell.

`mc7asm` keeps the interface of a parsed block as raw bytes.
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

Candidate readings:

1. The number of networks, one length per network, and a zero word.
2. The reading of TB `NetWork.GetNetworks`: the first word is a count N and the words 1 to N-1 are lengths, so for N = 1 no length is read at all.
3. A zero-terminated list of lengths behind a first word that means something else.

One single-network block cannot decide between them.
`mc7asm` keeps the table of a parsed block raw and derives no network boundaries from it.
The builder writes reading 1, which reproduces REF for one network and is a generalization beyond that.

## Footer

The last 36 bytes of the image.
Only TB parses it (`ParseBlockHeaderAndFooterFromMC7`); RZ stops after the header.

| Offset in footer | Size | Field | Meaning | Value in REF |
| --- | --- | --- | --- | --- |
| 0 | 8 | author | text | zeros |
| 8 | 8 | family | text | zeros |
| 16 | 8 | name | text, called "Header" in S7 | zeros |
| 24 | 1 | version | high nibble major, low nibble minor (TB `Helper.GetVersion`) | `10` |
| 25 | 1 | unknown | not parsed by any source | `00` |
| 26 | 2 | checksum | algorithm not documented by any source | `4d e5` |
| 28 | 8 | unknown | not parsed by any source | zeros |

S7 describes a 56-byte `TS7BlockFooter`.
Its last 36 bytes are exactly this footer, and its first 20 bytes overlap whatever precedes it, in REF the end of the interface and the segment table.
The stage-1 test blocks originally used the 56-byte form and were corrected in stage 2.0.

**Checksum.**
No source says how it is computed.
`mc7asm` never computes, verifies or corrects it: a parsed block keeps its value, a built block gets zero.
Snap7 sets the field to zero before it downloads a block (`opDownload` in `s7_micro_client.cpp`).

## Data blocks

Not settled.
TB places the current values at offset 36 (length at offset 34), then an interface that starts with `05`, or `0a` for an instance DB, and then start values whose length is the word at interface offset 5.
The comment in TB's header description gives the fields 28 and 34 a second meaning for data blocks that its code does not follow, and it is unclear whether the start values are counted in the interface length.

Until a real DB is captured, `mc7asm`:

- parses a DB like any block and keeps bytes it cannot place as "trailing unknown",
- does not build data blocks,
- refuses to disassemble them, because their body is values.

This is the item `TODO(real-db-fixture)` in `src/mc7asm/image.py`.

## Reading real blocks

A block read from a PLC may not follow this map exactly, so the reader is tolerant and loses nothing.

- `parse_image(data).to_bytes() == data` holds for every image that has the signature and at least 72 bytes.
- Bytes between the declared sections and the footer are kept as a "trailing unknown" region.
- A length field that differs from the file size is reported, not rejected.
- Sections whose declared lengths do not fit are left raw.

`validate_image` reports these as findings.
For images that `mc7asm` builds itself, `validate_generated_image` turns every one of them into an error, see [container.md](container.md).

## What is verified, and by what

| Fact | Evidence |
| --- | --- |
| Header offsets and sizes | TB and RZ agree; all 14 fields of REF decode to plausible values (`tests/test_image_fixtures.py`) |
| Section order and the length equation | REF adds up exactly; a rebuilt REF has identical bytes (`tests/test_end_to_end.py`) |
| Timestamp encoding | both timestamps of REF decode to valid dates |
| Code ends with `BE`, counted in the code length | REF; TB decodes `CodeSize - 2` |
| Interface sub-header and declaration pairs | TB code; REF decodes to the ten temporary variables of OB1, matching its local data length |
| Segment table for one network | REF; rebuilt identically |
| Footer position and fields | TB; REF rebuilt identically except the checksum |
| The image survives a round trip through this code | every committed fixture re-serializes byte for byte |

## Open questions

- The layout of data blocks, in particular start values and the meaning of field 28 for a DB.
- The segment table for more than one network.
- The closing byte `20` of the interface.
- The block version byte at offset 2 and the footer bytes at 25 and 28.
- The checksum algorithm, and whether a CPU accepts a zero checksum on download.
- Whether "linked" should be set in a block that is about to be downloaded.
- The interface of an FC or FB, and of OBs other than OB1; REF only shows OB1.

Each of these needs a real block, or a real CPU, to answer.
`scripts/capture_fixtures.py` exists to bring such blocks into `tests/fixtures/blocks/real`.
