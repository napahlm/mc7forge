# MC7 opcodes

This document records what `mc7asm` knows about the MC7 instruction encoding of the S7-300, and where each fact comes from.
The table at the end is generated from `src/mc7asm/opcodes.py` and the corpus by `scripts/gen_opcode_docs.py`, and a test fails when it is stale.

## Sources

| Source | What it is | Pinned version |
| --- | --- | --- |
| Corpus | `unit/test_simatic.c` of [rz-libmc7](https://github.com/rizinorg/rz-libmc7), vendored in `tests/fixtures/corpus` | commit `111b189a`, SHA-256 `8a93f7ad...f0d886` |
| Reference block | `example/cm7.bin` of rz-libmc7, vendored in `tests/fixtures/blocks/reference` | commit `111b189a`, SHA-256 `089f010e...767c29` |
| C# decoder | `MC7toAWL.cs`, `Mnemonic.cs` and `MC7Converter.cs` of [DotNetSiemensPLCToolBoxLibrary](https://github.com/dotnetprojects/DotNetSiemensPLCToolBoxLibrary) | commit `734b1413` (2026-10-28) |

The corpus is the ground truth.
It holds 2,531 active vectors: instruction bytes, the expected STL text and the expected read length.
The C# decoder is the cross-check.
The decoder source of rz-libmc7 (`src/simatic.c`) was not read; the table was derived from the vectors alone.

## Rules for a row

- A row exists only if corpus vectors exercise it.
  A test asserts that every row decodes at least one vector.
- A row is `verified` when the C# decoder agrees on the fixed bytes, the length and the meaning.
- A row is `verified, notation differs` when both agree on bytes, length and value but spell the operand differently, for example hex digits in lower or upper case.
- A row is `unverified` when the two sources disagree on what the bytes mean.
- The disassembler prints the corpus text character for character, also where that text is not what STEP 7 would print.
  The encoder of a later stage must not rely on those spellings before they are settled.

## Layout facts the disassembler relies on

- The code starts at offset 36 and its length is the 16-bit value at offset 34.
- Precondition: 36 + code length + interface length (offset 28) + segment table length (offset 30) + 36 = length field (offset 8) = file size.
  This holds on `cm7.bin`: 36 + 36 + 28 + 6 + 36 = 142.
- When a block violates the precondition, the violation is reported as a finding and the code section is decoded all the same.
- Only OB, FC and FB are disassembled.
  A DB is rejected because its body holds values, not code; SDB, SFC and SFB are rejected as out of scope.

## Findings of the cross-check

### 0xC0 to 0xC7 is `A`, not a compare-with-zero form

The stage brief assumed that `c1 00`, the first instruction of `cm7.bin`, is `AN <=0` and that 0xC0 to 0xC7 are compare-with-zero forms.
Both sources say otherwise.

- Corpus: 16 vectors, for example `c0 55` gives `A I 85.0` (line 1625) and `c0 d5` gives `A Q 85.0` (line 1626).
- C# decoder: `case 0xC0` to `case 0xC7` (lines 2221-2248) emit `U`/`A` with `E`/`I` or `A`/`Q` chosen by bit 7 of the second byte.

So `c1 00` is `A I 0.1`, and the whole family 0xC0 to 0xF7 is the 2-byte form of the bit operations on inputs and outputs.
It belongs to the minimal subset and is in the table.
No compare-with-zero family was needed.

### What `cm7.bin` needs beyond the minimal subset

The block decodes completely with four additions, each exercised by the corpus and confirmed by the C# decoder:

| Bytes | Instruction | Corpus vectors | C# decoder |
| --- | --- | --- | --- |
| `49 1x` to `49 6x`, `49 9x` to `49 Ex` | `FP`, `FN` on a directly addressed bit | 48 each | lines 107-178 |
| `54 nn` | `CD C n` | 4 | case 0x54 |
| `6c nn` | `CU C n` | 1 | case 0x6C |
| `4c nn` | `LC C n` | 1 | case 0x4C |
| `65 00` | `BE` | 2 | case 0x65 |

These rows carry the scope "needed for cm7.bin".
The expected listing is the golden file `tests/fixtures/golden/cm7.disasm.en.txt`.

### The last two bytes of the code section

`MC7Converter.cs` passes `CodeSize - 2` to the C# decoder, so it never decodes the last two code bytes.
On `cm7.bin` those bytes are `65 00`, which the corpus decodes as `BE` (lines 970 and 2458).
Conclusion: the code section ends with a `BE` instruction that is part of the code length, and the C# decoder leaves it out because STEP 7 does not show it in the source.
The disassembler decodes and prints it.
This is established on one block; the fake fixtures were built to end the same way.

Consequence for the assembler: the source of a block does not contain the closing `BE`.
The code generator emits exactly the source, and `mc7asm.container` appends `65 00` and counts it in the code length.
Building the reference program this way reproduces the 36 code bytes of `cm7.bin`.

### `L B#16#` is unverified

For `28 12` the corpus expects `L B#16#18` (line 443): the byte 0x12 printed in decimal behind the radix prefix.
The C# decoder prints `B#16#12`, which is what the prefix means.
The opcode and length agree; the operand text does not, and the corpus text does not denote the encoded value.
The row is marked `unverified` and the disassembler follows the corpus.

### Smaller differences

- `CD C n`: the C# decoder only handles counter numbers below 128; the corpus also has `54 ff` as `CD C 255` (line 2407).
- `L C#`: the corpus rejects values above 999 (`30 08 10 00` is invalid, line 457); the C# decoder prints any value.
- `L S5T#`: the corpus accepts non-decimal digits as long as the value stays below 1000 (`30 0c 38 ff` is `S5T#2H40M50S`, line 463) and rejects the rest.
- Constants: several operand spellings differ between the two sources (hex digit case, real numbers, time values); these rows are `verified, notation differs`.
- `L P#...` (`38 04`) is not in the table.
  The corpus has two active pointer vectors and three more that upstream disabled with `// FIXME`, and the active text `P#DI27187.4` does not follow the pointer layout the disabled ones imply.

## Segment table

The segment table follows the interface; on `cm7.bin` it is the 6 bytes `01 00 22 00 00 00` at file offset 0x64.
The six bytes `01 00 00 14 00 00` quoted in the stage brief are not the segment table: they are the first six bytes of the interface at offset 0x48, directly after the code.

`MC7Converter.cs` calls it the table of network lengths and reads it at 36 + code length + interface length.
Candidate readings of `01 00 22 00 00 00`, all as little-endian 16-bit words:

1. Count, then one length per network, then a zero word: 1 network of 0x22 = 34 bytes.
   34 is the code length minus the closing `BE`, which fits the conclusion above.
2. The reading of `NetWork.GetNetworks` in the C# library: the first word is the number of entries N and the words 1 to N-1 are lengths.
   With N = 1 it reads no length at all and would ignore the 0x22.
3. A length list terminated by zero, with the first word meaning something else.

Two real blocks with 5 and 19 networks decided it: reading 1 is right about the count and the lengths.
What it calls the zero word is a count of jump positions, and the blocks written in FBD carry one more word after those.
The bytes and the evidence are in [mc7-structure.md](mc7-structure.md#segment-table).

The container builder writes the network count, one length per network without the closing `BE`, and a zero word.
For one network this reproduces the bytes of `cm7.bin`.
For several networks the count and the lengths are what the real blocks show; whether an STL block has more behind them is not known, and `mc7asm build` says so in a note.
The reader still keeps the table raw.

## Unknown opcodes

Bytes no row matches become an unknown-opcode entry with their offset and a finding; nothing is skipped silently.
All instructions in the corpus are 2, 4 or 6 bytes long, so the decoder steps over one 2-byte word and continues.
An unknown instruction may be longer than that, so a second finding states that instruction boundaries after the first unknown opcode are not certain.

The real blocks show what that warning is worth.
The operand of an unknown 4-byte or 6-byte instruction, and the parameter list behind a block call, are read as if they were instructions, and some of them match a row.
In the real OB1 the listing shows `AN Q 34560.0` where the code has the parameters of a call.
The coverage line of `mc7asm disasm` counts such bytes as decoded, so on code with unknown opcodes it is an upper bound, not a measurement.

## Not in the table yet

718 of the 2,531 corpus vectors decode; 9 are negative vectors that must not decode; the other 1,804 are reported as unknown opcodes.
`tests/test_disasm.py` pins the exact count per mnemonic, so the number can only change deliberately.
The families still missing, in corpus terms:

- memory-indirect and register-indirect addressing (`A I [MD 4]`, `A [P#2330.0]`, the 0x51, 0x58, 0x59, 0x79, 0xBA to 0xBF and 0xFB groups),
- timers and counters as operands (`L T 5`, `A C 5`, `SP T 5`, `FR C 5`), except the three counter rows above,
- `X`, `XN` and the nesting forms `A(`, `O(`, `)`,
- jumps, `LOOP` and block calls (`JU`, `JC`, `UC`, `CC`, `OPN`),
- word logic, arithmetic, comparisons, conversions, shifts and rotates,
- status word and address register operations.

Jump targets need a decision first: the corpus prints them as absolute addresses from a base of 0x80000000.

## Coverage on real blocks

The two real code blocks, an OB1 and an FC1 uploaded from a CPU 317-2 DP, were written in FBD.
Counted on true instruction boundaries, with the instruction lengths of the corpus for everything the table does not have:

| Block | Code bytes | In the table | Outside the table | Call parameters | `mc7asm disasm` says |
| --- | --- | --- | --- | --- | --- |
| OB1 | 200 | 92 (46%) | 68 | 40 | 132 decoded, 68 unknown |
| FC1 | 724 | 98 (14%) | 626 | 0 | 164 decoded, 560 unknown |

Every byte of both blocks is accounted for by this count.
The last column is the coverage line of the tool, which is too high for the reason given under [Unknown opcodes](#unknown-opcodes).
What the table decodes is `A` and `=` on bit memory and local data, `L` of a constant, `T` to local data and `BE`.

What is outside the table, most frequent first, with the text the corpus gives for these bytes:

| Bytes | Corpus text | Length | OB1 | FC1 |
| --- | --- | --- | --- | --- |
| `10 nn` | `BLD nn` | 2 | 15 | 40 |
| `fb 7c` | `CDB` | 2 | | 34 |
| `00 00` | `NOP 0` | 2 | 4 | 19 |
| `fb 79 nn nn` | `OPN DI nnnn` | 4 | | 17 |
| `fe 6f nn nn` | `TAR2 LD nnnn` | 4 | | 17 |
| `fe 0b` and a pointer | `LAR2 P#...` | 6 | | 17 |
| `fb 72 nn nn` | `UC FC nnnn`, see below | 4 | | 17 |
| `fe 6b nn nn` | `LAR2 LD nnnn` | 4 | | 17 |
| `ff 98 nn nn` | `JNB` | 4 | | 9 |
| `70 0b nn nn` | `JU` | 4 | 5 | 3 |
| `3d nn` | `UC FC nn` | 2 | 5 | |
| `fb 70 nn nn` | `UC FC nnnn` | 4 | | 3 |
| `ba 00`, `bf 00` | `A(`, `)` | 2 | | 1 each |
| `ff e0` | `A BR` | 2 | | 1 |

This is the order in which rows pay off for code that a graphical editor produced.
Three things in it need more than a table row:

- **Block calls.**
  A call is `UC`, then a `JU` over the parameter list, then four bytes per parameter that are data, not instructions.
  The operand of that `JU` is the distance in words from the `JU` to the instruction behind the list; in OB1 it is 6 for two parameters, 14 for six and 2 for none.
  A decoder has to follow it, and an assembler has to produce it.
- **`fb 72` is a call of an FB.**
  The corpus prints `UC FC 4660` for `fb 72 12 34`, the same text as for `fb 70 12 34`.
  In the real FC1 each of the 17 `fb 72` instructions stands in the same sequence, `CDB`, `OPN DI n`, `TAR2`, `LAR2`, `fb 72 n`, `LAR2`, `CDB`, with the same number n in both places.
  The CPU has an FB and a DB with each of those 17 numbers and no FC with any of them.
  The three `fb 70` instructions name blocks that exist as FCs.
  So a row for `fb 72` must not take its text from the corpus.
- **Jumps.**
  The positions of the `JNB` instructions are listed in the segment table, see [mc7-structure.md](mc7-structure.md#segment-table).

## Encoding reference

This section states the encodings of the table in prose, family by family.
Every statement is backed by rows of the generated table at the end and therefore by corpus vectors.
`n` stands for a byte address, `b` for a bit number from 0 to 7.

### Bit operations, 4 bytes

```text
byte 0      byte 1               bytes 2-3
operation   v aaa 0 bbb          byte address, big-endian
```

| Byte 0 | `v` = 0 | `v` = 1 |
| --- | --- | --- |
| `00` | `A` | `AN` |
| `01` | `O` | `ON` |
| `09` | `S` | `R` |
| `41` | `=` | not exercised |
| `49` | `FP` | `FN` |

`aaa` is the area: 1 `I`, 2 `Q`, 3 `M`, 4 `DBX`, 5 `DIX`, 6 `L`.
`bbb` is the bit number; bit 3 of the byte is zero in every vector.
Example: `00 b7 12 34` is `AN M 4660.7`.

### Bit operations, 2 bytes

```text
byte 0              byte 1
ooooo bbb           byte address
```

| Byte 0, bit number 0 | Bit memory `M` | Inputs and outputs |
| --- | --- | --- |
| `A` | `80` | `c0` |
| `O` | `88` | `c8` |
| `S` | `90` | `d0` |
| `=` | `98` | `d8` |
| `AN` | `a0` | `e0` |
| `ON` | `a8` | `e8` |
| `R` | `b0` | `f0` |

For bit memory, byte 1 is the address, 0 to 255.
For inputs and outputs, bit 7 of byte 1 selects the area, 0 for `I` and 1 for `Q`, and bits 0 to 6 are the address, 0 to 127.
Examples: `87 ff` is `A M 255.7`, `c1 00` is `A I 0.1`, `d0 80` is `S Q 0.0`.
There is no 2-byte form for `L`, `DBX`, `DIX`, `FP` or `FN`.

### Load and transfer, 2 bytes

| | Byte | Word | Double word |
| --- | --- | --- | --- |
| `L M..` | `0a` | `12` | `1a` |
| `T M..` | `0b` | `13` | `1b` |
| `L I..` / `L Q..` | `4a` | `52` | `5a` |
| `T I..` / `T Q..` | `4b` | `53` | `5b` |

Byte 1 is the address, with the same input/output flag in bit 7 as above.
Examples: `12 0a` is `L MW 10`, `53 82` is `T QW 2`.

### Load and transfer, 4 bytes

```text
byte 0   byte 1          bytes 2-3
7e       aaaa 0 t ww     byte address, big-endian
```

`aaaa` is the area: 0 peripheral, 1 `I`, 2 `Q`, 3 `M`, 4 `DB`, 5 `DI`, 6 `L`.
`ww` is the width: 1 byte, 2 word, 3 double word.
`t` is 0 for `L` and 1 for `T`.
The peripheral area is `PIB`/`PIW`/`PID` for `L` and `PQB`/`PQW`/`PQD` for `T`; the other direction has no row.
Examples: `7e 46 00 02` is `T DBW 2`, `7e 01 01 00` is `L PIB 256`.

### Constants

`28 nn` loads a byte constant; its row is unverified, see below.
`30 kk` is followed by a 16-bit value and `38 kk` by a 32-bit value, both big-endian.

| `kk` | With `30` (16 bits) | With `38` (32 bits) |
| --- | --- | --- |
| `01` | | real number, IEEE 754 single precision |
| `02` | binary, `2#...` | binary, `2#...` |
| `03` | signed integer | signed integer, `L#...` |
| `05` | one or two characters | three or four characters |
| `06` | two bytes, `B#(a, b)` | four bytes, `B#(a, b, c, d)` |
| `07` | hexadecimal word, `W#16#...` | hexadecimal double word, `DW#16#...` |
| `08` | counter value, `C#...` | |
| `09` | | time in milliseconds, `T#...MS` |
| `0a` | date, `D#...` | |
| `0b` | | time of day, `TOD#...` |
| `0c` | S5 time, `S5T#...` | |

How the values are stored:

- **Characters** are right-aligned and padded with zero bytes on the left: `30 05 00 41` is `'A'`.
- **Counter value**: three BCD digits, 0 to 999: `30 08 01 00` is `C#100`.
- **Date**: days since 1990-01-01: `30 0a 00 01` is `D#1990-1-2`.
- **S5 time**: bits 12 and 13 hold the time base (0: 10 ms, 1: 100 ms, 2: 1 s, 3: 10 s), the low 12 bits three BCD digits.
  `30 0c 02 00` is `S5T#2S`, 200 times 10 ms.
  The assembler uses the smallest base that represents the duration exactly.
- **Time of day**: milliseconds since midnight.
- **Time**: a 32-bit millisecond count; the corpus prints it unsigned, and whether it is signed is not established.

`38 04`, a pointer constant, is in the corpus but not in the table, because its active and its disabled vectors contradict each other.

### Counters and block end

| Bytes | Instruction |
| --- | --- |
| `4c nn` | `LC C n` |
| `54 nn` | `CD C n` |
| `6c nn` | `CU C n` |
| `65 00` | `BE` |

### Seen in a real block

The reference block `cm7.bin` uses these encodings, which is the only evidence from real code:

```text
c1 00         A I 0.1         2-byte bit operation on an input
49 30 00 00   FP M 0.0        4-byte edge detection
d0 80         S Q 0.0         2-byte bit operation on an output
49 b1 00 00   FN M 0.1
f0 80         R Q 0.0
c2 00         A I 0.2
54 00         CD C 0
c3 00         A I 0.3
6c 00         CU C 0
4c 00         LC C 0
53 82         T QW 2          2-byte transfer to an output word
30 03 00 0d   L 13            16-bit integer constant
4b 80         T QB 0
65 00         BE
```

It shows that real code uses the 2-byte forms where they fit, which is why the assembler prefers the shortest encoding.

## Assembling with the table

The code generator uses the same rows in the other direction.
The rules it follows, and the corpus vectors that do not survive a round trip, are recorded in [decisions.md](decisions.md): shortest encoding (D4), the two non-canonical vectors (D5), the refusal of `L B#16#` (D3) and of statements without a row (D8).

## German mnemonics

`mc7asm disasm --mnemonics de` prints German (SIMATIC) spelling.
The pairs come from `Mnemonic.cs` of the C# library: `A`/`U`, `AN`/`UN`, `CD`/`ZR`, `CU`/`ZV`, areas `I`/`E`, `Q`/`A`, `C`/`Z`, and the peripheral areas `PI`/`PE`, `PQ`/`PA`.
The corpus is in international spelling only, so the German output is not covered by corpus vectors.

## The table

"Bytes" are the fixed bits of the first two bytes and "Mask" says which bits those are.
"Corpus vectors" is the number of active vectors the row decodes and the source line of the first one.

<!-- BEGIN GENERATED OPCODE TABLE -->

| Bytes | Mask | Mnemonic | Area | Operand | Length | Scope | Corpus vectors | C# decoder | Status | Note |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `00 10` | `ff f8` | `A` | `I` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | minimal subset | 8, first at line 20 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `00 20` | `ff f8` | `A` | `Q` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | minimal subset | 8, first at line 28 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `00 30` | `ff f8` | `A` | `M` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | minimal subset | 8, first at line 36 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `00 40` | `ff f8` | `A` | `DBX` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | minimal subset | 8, first at line 44 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `00 50` | `ff f8` | `A` | `DIX` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | minimal subset | 8, first at line 52 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `00 60` | `ff f8` | `A` | `L` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | minimal subset | 8, first at line 60 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `00 90` | `ff f8` | `AN` | `I` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | minimal subset | 8, first at line 69 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `00 a0` | `ff f8` | `AN` | `Q` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | minimal subset | 8, first at line 77 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `00 b0` | `ff f8` | `AN` | `M` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | minimal subset | 8, first at line 85 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `00 c0` | `ff f8` | `AN` | `DBX` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | minimal subset | 8, first at line 93 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `00 d0` | `ff f8` | `AN` | `DIX` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | minimal subset | 8, first at line 101 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `00 e0` | `ff f8` | `AN` | `L` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | minimal subset | 8, first at line 109 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `01 10` | `ff f8` | `O` | `I` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | minimal subset | 8, first at line 120 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `01 20` | `ff f8` | `O` | `Q` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | minimal subset | 8, first at line 128 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `01 30` | `ff f8` | `O` | `M` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | minimal subset | 8, first at line 136 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `01 40` | `ff f8` | `O` | `DBX` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | minimal subset | 8, first at line 144 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `01 50` | `ff f8` | `O` | `DIX` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | minimal subset | 8, first at line 152 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `01 60` | `ff f8` | `O` | `L` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | minimal subset | 8, first at line 160 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `01 90` | `ff f8` | `ON` | `I` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | minimal subset | 8, first at line 169 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `01 a0` | `ff f8` | `ON` | `Q` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | minimal subset | 8, first at line 177 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `01 b0` | `ff f8` | `ON` | `M` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | minimal subset | 8, first at line 185 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `01 c0` | `ff f8` | `ON` | `DBX` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | minimal subset | 8, first at line 193 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `01 d0` | `ff f8` | `ON` | `DIX` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | minimal subset | 8, first at line 201 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `01 e0` | `ff f8` | `ON` | `L` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | minimal subset | 8, first at line 209 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `09 10` | `ff f8` | `S` | `I` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | minimal subset | 8, first at line 322 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `09 20` | `ff f8` | `S` | `Q` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | minimal subset | 8, first at line 330 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `09 30` | `ff f8` | `S` | `M` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | minimal subset | 8, first at line 338 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `09 40` | `ff f8` | `S` | `DBX` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | minimal subset | 8, first at line 346 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `09 50` | `ff f8` | `S` | `DIX` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | minimal subset | 8, first at line 354 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `09 60` | `ff f8` | `S` | `L` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | minimal subset | 8, first at line 362 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `09 90` | `ff f8` | `R` | `I` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | minimal subset | 8, first at line 371 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `09 a0` | `ff f8` | `R` | `Q` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | minimal subset | 8, first at line 379 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `09 b0` | `ff f8` | `R` | `M` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | minimal subset | 8, first at line 387 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `09 c0` | `ff f8` | `R` | `DBX` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | minimal subset | 8, first at line 395 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `09 d0` | `ff f8` | `R` | `DIX` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | minimal subset | 8, first at line 403 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `09 e0` | `ff f8` | `R` | `L` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | minimal subset | 8, first at line 411 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `49 10` | `ff f8` | `FP` | `I` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | needed for cm7.bin | 8, first at line 554 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `49 20` | `ff f8` | `FP` | `Q` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | needed for cm7.bin | 8, first at line 562 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `49 30` | `ff f8` | `FP` | `M` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | needed for cm7.bin | 8, first at line 570 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `49 40` | `ff f8` | `FP` | `DBX` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | needed for cm7.bin | 8, first at line 578 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `49 50` | `ff f8` | `FP` | `DIX` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | needed for cm7.bin | 8, first at line 586 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `49 60` | `ff f8` | `FP` | `L` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | needed for cm7.bin | 8, first at line 594 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `49 90` | `ff f8` | `FN` | `I` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | needed for cm7.bin | 8, first at line 603 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `49 a0` | `ff f8` | `FN` | `Q` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | needed for cm7.bin | 8, first at line 611 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `49 b0` | `ff f8` | `FN` | `M` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | needed for cm7.bin | 8, first at line 619 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `49 c0` | `ff f8` | `FN` | `DBX` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | needed for cm7.bin | 8, first at line 627 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `49 d0` | `ff f8` | `FN` | `DIX` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | needed for cm7.bin | 8, first at line 635 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `49 e0` | `ff f8` | `FN` | `L` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | needed for cm7.bin | 8, first at line 643 | lines 107-178 | verified | bit numbers 8-15 are not exercised by the corpus and stay unknown |
| `41 10` | `ff f8` | `=` | `I` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | minimal subset | 8, first at line 501 | lines 545-678 | verified |  |
| `41 20` | `ff f8` | `=` | `Q` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | minimal subset | 8, first at line 509 | lines 545-678 | verified |  |
| `41 30` | `ff f8` | `=` | `M` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | minimal subset | 8, first at line 517 | lines 545-678 | verified |  |
| `41 40` | `ff f8` | `=` | `DBX` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | minimal subset | 8, first at line 525 | lines 545-678 | verified |  |
| `41 50` | `ff f8` | `=` | `DIX` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | minimal subset | 8, first at line 533 | lines 545-678 | verified |  |
| `41 60` | `ff f8` | `=` | `L` | area byte.bit: bit in byte 1 bits 0-2, byte address in bytes 2-3 | 4 | minimal subset | 9, first at line 541 | lines 545-678 | verified |  |
| `80 00` | `f8 00` | `A` | `M` | area byte.bit: bit in byte 0 bits 0-2, byte address in byte 1 | 2 | minimal subset | 8, first at line 1203 | case 0x80-0x87 | verified |  |
| `88 00` | `f8 00` | `O` | `M` | area byte.bit: bit in byte 0 bits 0-2, byte address in byte 1 | 2 | minimal subset | 8, first at line 1211 | case 0x88-0x8F | verified |  |
| `90 00` | `f8 00` | `S` | `M` | area byte.bit: bit in byte 0 bits 0-2, byte address in byte 1 | 2 | minimal subset | 8, first at line 1219 | case 0x90-0x97 | verified |  |
| `98 00` | `f8 00` | `=` | `M` | area byte.bit: bit in byte 0 bits 0-2, byte address in byte 1 | 2 | minimal subset | 8, first at line 1227 | case 0x98-0x9F | verified |  |
| `a0 00` | `f8 00` | `AN` | `M` | area byte.bit: bit in byte 0 bits 0-2, byte address in byte 1 | 2 | minimal subset | 8, first at line 1235 | case 0xA0-0xA7 | verified |  |
| `a8 00` | `f8 00` | `ON` | `M` | area byte.bit: bit in byte 0 bits 0-2, byte address in byte 1 | 2 | minimal subset | 8, first at line 1243 | case 0xA8-0xAF | verified |  |
| `b0 00` | `f8 00` | `R` | `M` | area byte.bit: bit in byte 0 bits 0-2, byte address in byte 1 | 2 | minimal subset | 8, first at line 1251 | case 0xB0-0xB7 | verified |  |
| `c0 00` | `f8 80` | `A` | `I` | area byte.bit: bit in byte 0 bits 0-2, byte address in byte 1 bits 0-6 | 2 | minimal subset | 8, first at line 1625 | case 0xC0-0xC7 | verified |  |
| `c0 80` | `f8 80` | `A` | `Q` | area byte.bit: bit in byte 0 bits 0-2, byte address in byte 1 bits 0-6 | 2 | minimal subset | 8, first at line 1626 | case 0xC0-0xC7 | verified |  |
| `c8 00` | `f8 80` | `O` | `I` | area byte.bit: bit in byte 0 bits 0-2, byte address in byte 1 bits 0-6 | 2 | minimal subset | 8, first at line 1641 | case 0xC8-0xCF | verified |  |
| `c8 80` | `f8 80` | `O` | `Q` | area byte.bit: bit in byte 0 bits 0-2, byte address in byte 1 bits 0-6 | 2 | minimal subset | 8, first at line 1642 | case 0xC8-0xCF | verified |  |
| `d0 00` | `f8 80` | `S` | `I` | area byte.bit: bit in byte 0 bits 0-2, byte address in byte 1 bits 0-6 | 2 | minimal subset | 8, first at line 1657 | case 0xD0-0xD7 | verified |  |
| `d0 80` | `f8 80` | `S` | `Q` | area byte.bit: bit in byte 0 bits 0-2, byte address in byte 1 bits 0-6 | 2 | minimal subset | 8, first at line 1658 | case 0xD0-0xD7 | verified |  |
| `d8 00` | `f8 80` | `=` | `I` | area byte.bit: bit in byte 0 bits 0-2, byte address in byte 1 bits 0-6 | 2 | minimal subset | 8, first at line 1673 | case 0xD8-0xDF | verified |  |
| `d8 80` | `f8 80` | `=` | `Q` | area byte.bit: bit in byte 0 bits 0-2, byte address in byte 1 bits 0-6 | 2 | minimal subset | 8, first at line 1674 | case 0xD8-0xDF | verified |  |
| `e0 00` | `f8 80` | `AN` | `I` | area byte.bit: bit in byte 0 bits 0-2, byte address in byte 1 bits 0-6 | 2 | minimal subset | 8, first at line 1689 | case 0xE0-0xE7 | verified |  |
| `e0 80` | `f8 80` | `AN` | `Q` | area byte.bit: bit in byte 0 bits 0-2, byte address in byte 1 bits 0-6 | 2 | minimal subset | 8, first at line 1690 | case 0xE0-0xE7 | verified |  |
| `e8 00` | `f8 80` | `ON` | `I` | area byte.bit: bit in byte 0 bits 0-2, byte address in byte 1 bits 0-6 | 2 | minimal subset | 8, first at line 1705 | case 0xE8-0xEF | verified |  |
| `e8 80` | `f8 80` | `ON` | `Q` | area byte.bit: bit in byte 0 bits 0-2, byte address in byte 1 bits 0-6 | 2 | minimal subset | 8, first at line 1706 | case 0xE8-0xEF | verified |  |
| `f0 00` | `f8 80` | `R` | `I` | area byte.bit: bit in byte 0 bits 0-2, byte address in byte 1 bits 0-6 | 2 | minimal subset | 8, first at line 1721 | case 0xF0-0xF7 | verified |  |
| `f0 80` | `f8 80` | `R` | `Q` | area byte.bit: bit in byte 0 bits 0-2, byte address in byte 1 bits 0-6 | 2 | minimal subset | 8, first at line 1722 | case 0xF0-0xF7 | verified |  |
| `0a 00` | `ff 00` | `L` | `MB` | area address: address in byte 1 | 2 | minimal subset | 1, first at line 420 | case 0x0A | verified |  |
| `0b 00` | `ff 00` | `T` | `MB` | area address: address in byte 1 | 2 | minimal subset | 1, first at line 421 | case 0x0B | verified |  |
| `12 00` | `ff 00` | `L` | `MW` | area address: address in byte 1 | 2 | minimal subset | 1, first at line 425 | case 0x12 | verified |  |
| `13 00` | `ff 00` | `T` | `MW` | area address: address in byte 1 | 2 | minimal subset | 1, first at line 426 | case 0x13 | verified |  |
| `1a 00` | `ff 00` | `L` | `MD` | area address: address in byte 1 | 2 | minimal subset | 1, first at line 429 | case 0x1A | verified |  |
| `1b 00` | `ff 00` | `T` | `MD` | area address: address in byte 1 | 2 | minimal subset | 1, first at line 430 | case 0x1B | verified |  |
| `4a 00` | `ff 80` | `L` | `IB` | area address: address in byte 1 bits 0-6 | 2 | minimal subset | 1, first at line 652 | case 0x4A | verified |  |
| `4a 80` | `ff 80` | `L` | `QB` | area address: address in byte 1 bits 0-6 | 2 | minimal subset | 1, first at line 654 | case 0x4A | verified |  |
| `4b 00` | `ff 80` | `T` | `IB` | area address: address in byte 1 bits 0-6 | 2 | minimal subset | 1, first at line 653 | case 0x4B | verified |  |
| `4b 80` | `ff 80` | `T` | `QB` | area address: address in byte 1 bits 0-6 | 2 | minimal subset | 1, first at line 655 | case 0x4B | verified |  |
| `52 00` | `ff 80` | `L` | `IW` | area address: address in byte 1 bits 0-6 | 2 | minimal subset | 1, first at line 756 | case 0x52 | verified |  |
| `52 80` | `ff 80` | `L` | `QW` | area address: address in byte 1 bits 0-6 | 2 | minimal subset | 1, first at line 758 | case 0x52 | verified |  |
| `53 00` | `ff 80` | `T` | `IW` | area address: address in byte 1 bits 0-6 | 2 | minimal subset | 1, first at line 757 | case 0x53 | verified |  |
| `53 80` | `ff 80` | `T` | `QW` | area address: address in byte 1 bits 0-6 | 2 | minimal subset | 1, first at line 759 | case 0x53 | verified |  |
| `5a 00` | `ff 80` | `L` | `ID` | area address: address in byte 1 bits 0-6 | 2 | minimal subset | 1, first at line 937 | case 0x5A | verified |  |
| `5a 80` | `ff 80` | `L` | `QD` | area address: address in byte 1 bits 0-6 | 2 | minimal subset | 1, first at line 939 | case 0x5A | verified |  |
| `5b 00` | `ff 80` | `T` | `ID` | area address: address in byte 1 bits 0-6 | 2 | minimal subset | 1, first at line 938 | case 0x5B | verified |  |
| `5b 80` | `ff 80` | `T` | `QD` | area address: address in byte 1 bits 0-6 | 2 | minimal subset | 1, first at line 940 | case 0x5B | verified |  |
| `7e 01` | `ff ff` | `L` | `PIB` | area address: address in bytes 2-3 | 4 | minimal subset | 1, first at line 1160 | case 0x7E, lines 1559-1773 | verified |  |
| `7e 05` | `ff ff` | `T` | `PQB` | area address: address in bytes 2-3 | 4 | minimal subset | 1, first at line 1163 | case 0x7E, lines 1559-1773 | verified |  |
| `7e 11` | `ff ff` | `L` | `IB` | area address: address in bytes 2-3 | 4 | minimal subset | 1, first at line 1166 | case 0x7E, lines 1559-1773 | verified |  |
| `7e 15` | `ff ff` | `T` | `IB` | area address: address in bytes 2-3 | 4 | minimal subset | 1, first at line 1169 | case 0x7E, lines 1559-1773 | verified |  |
| `7e 21` | `ff ff` | `L` | `QB` | area address: address in bytes 2-3 | 4 | minimal subset | 1, first at line 1172 | case 0x7E, lines 1559-1773 | verified |  |
| `7e 25` | `ff ff` | `T` | `QB` | area address: address in bytes 2-3 | 4 | minimal subset | 1, first at line 1175 | case 0x7E, lines 1559-1773 | verified |  |
| `7e 31` | `ff ff` | `L` | `MB` | area address: address in bytes 2-3 | 4 | minimal subset | 1, first at line 1178 | case 0x7E, lines 1559-1773 | verified |  |
| `7e 35` | `ff ff` | `T` | `MB` | area address: address in bytes 2-3 | 4 | minimal subset | 1, first at line 1181 | case 0x7E, lines 1559-1773 | verified |  |
| `7e 41` | `ff ff` | `L` | `DBB` | area address: address in bytes 2-3 | 4 | minimal subset | 1, first at line 1184 | case 0x7E, lines 1559-1773 | verified |  |
| `7e 45` | `ff ff` | `T` | `DBB` | area address: address in bytes 2-3 | 4 | minimal subset | 1, first at line 1187 | case 0x7E, lines 1559-1773 | verified |  |
| `7e 51` | `ff ff` | `L` | `DIB` | area address: address in bytes 2-3 | 4 | minimal subset | 1, first at line 1190 | case 0x7E, lines 1559-1773 | verified |  |
| `7e 55` | `ff ff` | `T` | `DIB` | area address: address in bytes 2-3 | 4 | minimal subset | 1, first at line 1193 | case 0x7E, lines 1559-1773 | verified |  |
| `7e 61` | `ff ff` | `L` | `LB` | area address: address in bytes 2-3 | 4 | minimal subset | 1, first at line 1196 | case 0x7E, lines 1559-1773 | verified |  |
| `7e 65` | `ff ff` | `T` | `LB` | area address: address in bytes 2-3 | 4 | minimal subset | 1, first at line 1199 | case 0x7E, lines 1559-1773 | verified |  |
| `7e 02` | `ff ff` | `L` | `PIW` | area address: address in bytes 2-3 | 4 | minimal subset | 1, first at line 1161 | case 0x7E, lines 1559-1773 | verified |  |
| `7e 06` | `ff ff` | `T` | `PQW` | area address: address in bytes 2-3 | 4 | minimal subset | 1, first at line 1164 | case 0x7E, lines 1559-1773 | verified |  |
| `7e 12` | `ff ff` | `L` | `IW` | area address: address in bytes 2-3 | 4 | minimal subset | 1, first at line 1167 | case 0x7E, lines 1559-1773 | verified |  |
| `7e 16` | `ff ff` | `T` | `IW` | area address: address in bytes 2-3 | 4 | minimal subset | 1, first at line 1170 | case 0x7E, lines 1559-1773 | verified |  |
| `7e 22` | `ff ff` | `L` | `QW` | area address: address in bytes 2-3 | 4 | minimal subset | 1, first at line 1173 | case 0x7E, lines 1559-1773 | verified |  |
| `7e 26` | `ff ff` | `T` | `QW` | area address: address in bytes 2-3 | 4 | minimal subset | 1, first at line 1176 | case 0x7E, lines 1559-1773 | verified |  |
| `7e 32` | `ff ff` | `L` | `MW` | area address: address in bytes 2-3 | 4 | minimal subset | 1, first at line 1179 | case 0x7E, lines 1559-1773 | verified |  |
| `7e 36` | `ff ff` | `T` | `MW` | area address: address in bytes 2-3 | 4 | minimal subset | 1, first at line 1182 | case 0x7E, lines 1559-1773 | verified |  |
| `7e 42` | `ff ff` | `L` | `DBW` | area address: address in bytes 2-3 | 4 | minimal subset | 1, first at line 1185 | case 0x7E, lines 1559-1773 | verified |  |
| `7e 46` | `ff ff` | `T` | `DBW` | area address: address in bytes 2-3 | 4 | minimal subset | 1, first at line 1188 | case 0x7E, lines 1559-1773 | verified |  |
| `7e 52` | `ff ff` | `L` | `DIW` | area address: address in bytes 2-3 | 4 | minimal subset | 1, first at line 1191 | case 0x7E, lines 1559-1773 | verified |  |
| `7e 56` | `ff ff` | `T` | `DIW` | area address: address in bytes 2-3 | 4 | minimal subset | 1, first at line 1194 | case 0x7E, lines 1559-1773 | verified |  |
| `7e 62` | `ff ff` | `L` | `LW` | area address: address in bytes 2-3 | 4 | minimal subset | 1, first at line 1197 | case 0x7E, lines 1559-1773 | verified |  |
| `7e 66` | `ff ff` | `T` | `LW` | area address: address in bytes 2-3 | 4 | minimal subset | 1, first at line 1200 | case 0x7E, lines 1559-1773 | verified |  |
| `7e 03` | `ff ff` | `L` | `PID` | area address: address in bytes 2-3 | 4 | minimal subset | 1, first at line 1162 | case 0x7E, lines 1559-1773 | verified |  |
| `7e 07` | `ff ff` | `T` | `PQD` | area address: address in bytes 2-3 | 4 | minimal subset | 1, first at line 1165 | case 0x7E, lines 1559-1773 | verified |  |
| `7e 13` | `ff ff` | `L` | `ID` | area address: address in bytes 2-3 | 4 | minimal subset | 1, first at line 1168 | case 0x7E, lines 1559-1773 | verified |  |
| `7e 17` | `ff ff` | `T` | `ID` | area address: address in bytes 2-3 | 4 | minimal subset | 1, first at line 1171 | case 0x7E, lines 1559-1773 | verified |  |
| `7e 23` | `ff ff` | `L` | `QD` | area address: address in bytes 2-3 | 4 | minimal subset | 1, first at line 1174 | case 0x7E, lines 1559-1773 | verified |  |
| `7e 27` | `ff ff` | `T` | `QD` | area address: address in bytes 2-3 | 4 | minimal subset | 1, first at line 1177 | case 0x7E, lines 1559-1773 | verified |  |
| `7e 33` | `ff ff` | `L` | `MD` | area address: address in bytes 2-3 | 4 | minimal subset | 1, first at line 1180 | case 0x7E, lines 1559-1773 | verified |  |
| `7e 37` | `ff ff` | `T` | `MD` | area address: address in bytes 2-3 | 4 | minimal subset | 1, first at line 1183 | case 0x7E, lines 1559-1773 | verified |  |
| `7e 43` | `ff ff` | `L` | `DBD` | area address: address in bytes 2-3 | 4 | minimal subset | 1, first at line 1186 | case 0x7E, lines 1559-1773 | verified |  |
| `7e 47` | `ff ff` | `T` | `DBD` | area address: address in bytes 2-3 | 4 | minimal subset | 1, first at line 1189 | case 0x7E, lines 1559-1773 | verified |  |
| `7e 53` | `ff ff` | `L` | `DID` | area address: address in bytes 2-3 | 4 | minimal subset | 1, first at line 1192 | case 0x7E, lines 1559-1773 | verified |  |
| `7e 57` | `ff ff` | `T` | `DID` | area address: address in bytes 2-3 | 4 | minimal subset | 1, first at line 1195 | case 0x7E, lines 1559-1773 | verified |  |
| `7e 63` | `ff ff` | `L` | `LD` | area address: address in bytes 2-3 | 4 | minimal subset | 2, first at line 1198 | case 0x7E, lines 1559-1773 | verified |  |
| `7e 67` | `ff ff` | `T` | `LD` | area address: address in bytes 2-3 | 4 | minimal subset | 1, first at line 1201 | case 0x7E, lines 1559-1773 | verified |  |
| `28 00` | `ff 00` | `L` |  | B#16#n: byte 1 | 2 | minimal subset | 2, first at line 443 | case 0x28 | unverified | the corpus prints the byte in decimal after B#16# (0x12 gives B#16#18), the C# decoder prints it in hexadecimal (B#16#12) |
| `30 02` | `ff ff` | `L` |  | 2#bits: bytes 2-3 | 4 | minimal subset | 4, first at line 448 | case 0x30, sub-case 0x02 | verified, notation differs | the C# text comes from a Helper function that was not compared |
| `30 03` | `ff ff` | `L` |  | signed integer: bytes 2-3 | 4 | minimal subset | 3, first at line 451 | case 0x30, sub-case 0x03 | verified |  |
| `30 05` | `ff ff` | `L` |  | 'characters': bytes 2-3 | 4 | minimal subset | 3, first at line 453 | case 0x30, sub-case 0x05 | verified, notation differs | the C# text comes from a Helper function that was not compared |
| `30 06` | `ff ff` | `L` |  | B#(a, b): bytes 2-3 | 4 | minimal subset | 2, first at line 454 | case 0x30, sub-case 0x06 | verified | values below 10 are not exercised |
| `30 07` | `ff ff` | `L` |  | W#16#hex: bytes 2-3 | 4 | minimal subset | 2, first at line 455 | case 0x30, sub-case 0x07 | verified, notation differs | C# prints upper-case hex digits |
| `30 08` | `ff ff` | `L` |  | C#count: three BCD digits in bytes 2-3 | 4 | minimal subset | 2, first at line 456 | case 0x30, sub-case 0x08 | verified | the corpus rejects values above 999, C# does not |
| `30 0a` | `ff ff` | `L` |  | D#year-month-day: days since 1990-01-01 in bytes 2-3 | 4 | minimal subset | 2, first at line 459 | case 0x30, sub-case 0x0A | verified, notation differs | the C# text comes from a Helper function that was not compared |
| `30 0c` | `ff ff` | `L` |  | S5T#duration: time base and three BCD digits in bytes 2-3 | 4 | minimal subset | 8, first at line 462 | case 0x30, sub-case 0x0C | verified, notation differs | the C# text comes from a Helper function that was not compared |
| `38 01` | `ff ff` | `L` |  | floating point number: IEEE 754 single in bytes 2-5 | 6 | minimal subset | 2, first at line 479 | case 0x38, sub-case 0x01 | verified, notation differs | corpus fixed notation, C# scientific |
| `38 02` | `ff ff` | `L` |  | 2#bits: bytes 2-5 | 6 | minimal subset | 4, first at line 480 | case 0x38, sub-case 0x02 | verified, notation differs | the C# text comes from a Helper function that was not compared |
| `38 03` | `ff ff` | `L` |  | L#signed integer: bytes 2-5 | 6 | minimal subset | 3, first at line 483 | case 0x38, sub-case 0x03 | verified |  |
| `38 05` | `ff ff` | `L` |  | 'characters': bytes 2-5 | 6 | minimal subset | 2, first at line 2604 | case 0x38, sub-case 0x05 | verified, notation differs | the C# text comes from a Helper function that was not compared |
| `38 06` | `ff ff` | `L` |  | B#(a, b, c, d): bytes 2-5 | 6 | minimal subset | 2, first at line 485 | case 0x38, sub-case 0x06 | verified, notation differs | the corpus pads each byte to 2 digits (0 gives 00), C# does not pad |
| `38 07` | `ff ff` | `L` |  | DW#16#hex: bytes 2-5 | 6 | minimal subset | 3, first at line 486 | case 0x38, sub-case 0x07 | verified, notation differs | C# prints upper-case hex digits |
| `38 09` | `ff ff` | `L` |  | T#milliseconds MS: bytes 2-5 | 6 | minimal subset | 2, first at line 487 | case 0x38, sub-case 0x09 | verified, notation differs | the corpus prints unsigned milliseconds; the C# text comes from a Helper function that was not compared |
| `38 0b` | `ff ff` | `L` |  | TOD#h:m:s.ms: milliseconds since midnight in bytes 2-5 | 6 | minimal subset | 2, first at line 488 | case 0x38, sub-case 0x0B | verified, notation differs | the C# text comes from a Helper function that was not compared |
| `4c 00` | `ff 00` | `LC` | `C` | area address: address in byte 1 | 2 | needed for cm7.bin | 1, first at line 656 | case 0x4C | verified |  |
| `54 00` | `ff 00` | `CD` | `C` | area address: address in byte 1 | 2 | needed for cm7.bin | 4, first at line 760 | case 0x54 | verified | C# decodes counter numbers below 128 only; the corpus also has C 255 |
| `6c 00` | `ff 00` | `CU` | `C` | area address: address in byte 1 | 2 | needed for cm7.bin | 1, first at line 1012 | case 0x6C | verified |  |
| `65 00` | `ff ff` | `BE` |  | none | 2 | needed for cm7.bin | 2, first at line 970 | case 0x65, sub-case 0x00 | verified |  |

<!-- END GENERATED OPCODE TABLE -->
