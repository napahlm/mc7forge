# STL front end and code generator

This document describes what `mc7asm parse` and `mc7asm compile` accept and produce.
The opcode knowledge itself is in [opcodes.md](opcodes.md).

## Source subset

A source file holds exactly one block.

```text
ORGANIZATION_BLOCK OB 1
TITLE = Lamp control
BEGIN
NETWORK
TITLE = Latch the lamp
// The start button sets the lamp, the stop button resets it.
      A     I 0.0;        // start button
      S     Q 0.0;
END_ORGANIZATION_BLOCK
```

- Block headers: `ORGANIZATION_BLOCK OB n`, `FUNCTION FC n : VOID` (the `: VOID` is optional) and `FUNCTION_BLOCK FB n`, closed by the matching `END_...` keyword.
- `TITLE = text` is optional after the header and after `NETWORK`.
- Comment lines directly after a network title belong to the network; a `//` comment after a statement belongs to that statement; other comment lines are ignored.
- Keywords, operations and areas are case-insensitive.
- Addresses may be written `I0.0` or `I 0.0`, and the `;` after a statement is optional.
- Declaration sections, block attributes, symbols and labels are not supported and are reported as syntax errors.

| Statement | Operand |
| --- | --- |
| `A`, `AN`, `O`, `ON` | bit address |
| `=`, `S`, `R` | bit address |
| `FP`, `FN` | bit address |
| `A(`, `AN(`, `O(`, `ON(`, `)` | none; must balance inside a network |
| `L` | byte, word or double word address, or a constant |
| `T` | byte, word or double word address |
| `CU`, `CD`, `LC` | counter, `C n` |
| `BE` | none |

Bit addresses: `I`, `Q`, `M`, `L`, `DBX`, `DIX` with `byte.bit`, and the qualified form `DB1.DBX 0.0`.
Data addresses: `IB/IW/ID`, `QB/QW/QD`, `MB/MW/MD`, `LB/LW/LD`, `DBB/DBW/DBD`, `DIB/DIW/DID`, `PIB/PIW/PID`, `PQB/PQW/PQD`, and the qualified form `DB1.DBD 4`.

Constants: `TRUE`, `FALSE`, integers (`100`, `-5`), 32-bit integers (`L#100000`), reals (`1.5`, `2.5e3`), and the prefixed notations `B#16#`, `W#16#`, `DW#16#`, `2#`, `C#`, `D#`, `S5T#`, `T#nMS`, `TOD#h:m:s.mmm`, `B#(a, b)`, `B#(a, b, c, d)` and `'text'` with up to four characters.

With `--mnemonics de` the German spelling is expected instead: `U`, `UN`, `ZV`, `ZR`, areas `E`, `A`, `Z`, `PE`, `PA`.
The switch is explicit because the letter `A` is the AND operation in one spelling and the output area in the other.
International spelling in German mode, and the reverse, is a syntax error with a hint.

## Intermediate representation

The IR in `src/mc7asm/ir.py` is a tree of `Block`, `Network`, instruction and operand.
It is always in international spelling.

- Instructions: `BitLogic`, `NestOpen`, `NestClose`, `BitWrite`, `EdgeDetect`, `Load`, `Transfer`, `CounterControl`, `BlockEnd`.
- Operands: `BitAddress`, `DataAddress`, `CounterAddress`, `BoolConstant`, `IntConstant`, `RealConstant`, `TypedConstant`.
- Every node carries a `file:line:column` location.
  Locations and comments do not take part in equality.
- The instruction list of a network is flat; `A(` and `)` are instructions, as in MC7.

Compared with the hierarchy proposed for stage 2.2, three instruction classes and two operand classes were added, because the opcode table and the reference block need them: `EdgeDetect`, `CounterControl`, `BlockEnd`, `CounterAddress` and `TypedConstant`.
Jumps will add one instruction class, a label operand and a label field on the base class.

`mc7asm.notation` is the only place that knows how typed constants are spelled.
The parser, the IR printer and the disassembler all use it.

## Syntax errors

`Mc7SyntaxError` derives from `Mc7AsmError` and carries `location`, `message`, the offending `text` and a `hint`.
Its string form is `file:line:column: message; hint`.
`tests/expected_errors` holds one malformed source per error with the exact expected message.

## Code generation

`mc7asm.codegen` selects a row of the opcode table by mnemonic and operand and fills the operand into the bits the row leaves open.

- **Shortest encoding.** When several rows fit, the shortest wins: `A M 255.7` is the 2-byte `87 ff`, `A M 256.7` the 4-byte `00 37 01 00`.
  The reference block confirms this for real code: its `A I 0.1` is `c1 00`.
- **Unverified rows are not used.** `L B#16#...` is refused, because the corpus and the C# decoder disagree on what its text means and a wrong guess would produce wrong code silently.
- **Not yet supported.** Nesting operations, fully qualified data block addresses (they need `OPN DB`), `TRUE`/`FALSE`, and `L`/`T` on the peripheral area of the other direction have no row and raise `NotYetSupportedError` with the source location.
- **No `BE` in the body.** The body is exactly the instructions of the source.
  The closing `BE` is appended by the container builder, see [container.md](container.md).
- **Accounting.** `compile_block` returns the bytes and offset of every instruction and the offset and size of every network.

## The correctness loop

`tests/test_roundtrip.py` runs all 2,531 corpus vectors through bytes, disassembly, parsing and code generation.

| Outcome | Vectors |
| --- | --- |
| Covered by the table, bytes identical | 714 |
| Covered by the table, not the canonical encoding | 2 |
| Covered by the table, refused as unverified (`B#16#`) | 2 |
| Outside the table, rejected by the parser | 1,807 |
| Outside the table, parsed but refused by the code generator (nesting) | 6 |

The two non-canonical vectors are:

- `30 0c 38 ff`, `L S5T#2H40M50S`: its digits 8, F, F are not decimal. The assembler writes the same duration as `30 0c 39 65`.
- `38 02 00 00 00 00`, `L 2#0` as a 32-bit constant. The text does not show the width, and the assembler uses 16 bits when the digits fit, giving `30 02 00 00`.

Further checks:

- Assembling the golden disassembly of `cm7.bin`, in international and in German spelling, reproduces its 36 code bytes.
- A seeded property test builds random operands for every usable row and checks that disassembling the generated bytes gives back the same IR.

## Limits to keep in mind

- Real numbers are printed with six decimals, as in the corpus.
  Parsing that text back does not always give the same 32-bit value, so the disassemble-then-assemble loop is exact only for reals that six decimals represent exactly.
- `T#` constants are plain millisecond counts and `TOD#` hours are not limited to 23, both as in the corpus.
- The German spelling is not covered by corpus vectors; it is tested through the loop against the international form.
- Nothing produced by `mc7asm compile` has been loaded into a PLC.
