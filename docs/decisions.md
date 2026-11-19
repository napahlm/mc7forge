# Decision log

Decisions taken while building `mc7asm`, with the reason for each and where it is enforced.
A decision stays here even when later work changes it, with a note saying so.

## D1. The corpus is the arbiter

**Decision.** The decoder test table of rz-libmc7, 2,531 vectors, is the ground truth for opcodes.
A row enters the opcode table only if corpus vectors exercise it, and every vector must either decode to exactly its text or be reported as unknown.

**Why.** The vectors are facts that can be checked mechanically: bytes, text and length.
Everything else, including this project's own reading of the format, is interpretation.

**Outcome of the full loop.** Every vector goes through bytes, disassembly, parsing and code generation.

| Outcome | Vectors |
| --- | --- |
| Covered by the table, bytes identical after the loop | 714 |
| Covered by the table, not the canonical encoding of its text | 2 |
| Covered by the table, refused as unverified | 2 |
| Outside the table, rejected by the parser | 1,807 |
| Outside the table, parsed but refused by the code generator | 6 |
| Total | 2,531 |

The first three rows are the 718 vectors the disassembler decodes; 9 of the parser-rejected vectors are negative vectors that no decoder may accept.

**Enforced by.** `tests/test_disasm.py` pins the decoded and undecoded counts per mnemonic.
`tests/test_roundtrip.py` pins this table and lists the four exceptions by source line.

## D2. Corpus parsing is strict, and the file is the only copy

**Decision.** `mc7asm.corpus` parses the vendored C file directly with a line parser that rejects any line it does not understand.
There is no converted copy of the data.

**Why.** A loose pattern silently skips what it does not match.
The first prototype matched 1,146 of 2,531 vectors because it only accepted lower-case hex; the strict mode reported the other lines instead of returning a wrong count.
A second copy of the data could drift from the file.

**Consequence.** The counts are the strict ones: 2,531 active vectors, 9 that upstream disabled with `// FIXME`, one terminator.
A looser count gives slightly higher numbers for five mnemonics, because it includes the disabled vectors and counts `A(` as `A`; `tests/test_corpus.py` shows the reconciliation.

## D3. `L B#16#...` is not assembled

**Decision.** The code generator refuses the byte constant `L B#16#...`.

**Why.** For the bytes `28 12` the corpus expects the text `L B#16#18`, the value 0x12 printed in decimal behind a hexadecimal prefix.
The C# decoder prints `B#16#12`.
The two sources disagree on what the text means, so the row is marked unverified.
Assembling it either way risks writing a byte the author did not mean, with nothing to show for it.
Refusing beats silently emitting the wrong byte.

**Details.** The parser reads `B#16#` as hexadecimal, as the prefix says.
The disassembler prints what the corpus expects.
These are the two "refused as unverified" vectors of D1, source lines 443 and 2435.

**Enforced by.** `compile_instruction` rejects every row with the status "unverified"; `tests/test_codegen.py`.

## D4. The shortest encoding wins

**Decision.** When several opcode rows can encode an instruction, the code generator uses the shortest.
`A M 255.7` becomes the 2-byte `87 ff`, `A M 256.7` the 4-byte `00 37 01 00`.

**Why.** The reference block shows it for real code: its `A I 0.1` is `c1 00`, its `T QW 2` is `53 82`, although 4-byte forms exist for both.
With this rule every corpus vector whose address fits a short form round-trips.

**Enforced by.** `tests/test_codegen.py` checks the boundary on both sides for each form.

## D5. Two corpus vectors are not canonical

**Decision.** For two vectors the assembler produces different bytes than the vector has, and that is accepted and listed.

| Vector | Text | Assembler output | Reason |
| --- | --- | --- | --- |
| `30 0c 38 ff` | `L S5T#2H40M50S` | `30 0c 39 65` | the digits 8, F, F are not decimal; 9,650 s is written as 965 with a time base of 10 s |
| `38 02 00 00 00 00` | `L 2#0` | `30 02 00 00` | the text does not show the width; a binary constant of up to 16 digits is encoded in 16 bits |

**Why.** One text can only assemble to one byte sequence.
Both outputs decode back to the same text, and both are shorter or equally long.
The rule for S5TIME is the smallest time base that represents the duration exactly, which reproduces every other S5TIME vector.

**Enforced by.** `tests/test_roundtrip.py`, `NOT_CANONICAL`.

## D6. Real numbers are printed with six decimals

**Decision.** The disassembler prints a real constant in fixed notation with six decimals, `L 12.345000`, as the corpus does.

**Limit.** Six decimals do not identify every 32-bit real.
Disassembling and reassembling is exact only for values those six decimals represent exactly, which includes both corpus vectors.
The C# decoder uses scientific notation instead; the row is marked "notation differs".

**Not done.** Printing more digits would make the loop exact for every value but would no longer match the corpus text.
The trade-off is left as it is until real code needs it.

## D7. `BE` belongs to the container, not to the source

**Decision.** The code generator emits exactly the instructions of the source.
The container builder appends `BE` (`65 00`) unless the source already ends with it, and counts it in the code length.

**Why.** The reference block ends with `65 00`, counted in its code length, and the C# decoder skips the last two code bytes because STEP 7 does not show them.
Closing a block is a property of the block, not of a network.
In stage 2.3 the body had no implicit `BE` and the decision was deferred; stage 2.4 placed it here.

**Details.** The builder looks at the last instruction, not at the last two bytes, so `L W#16#6500` at the end of a block is not mistaken for `BE`.
The network lengths in the segment table never include the closing `BE`.

**Enforced by.** `tests/test_container.py`, `tests/test_end_to_end.py`.

## D8. Valid STL without a table row is refused, not approximated

**Decision.** The parser accepts a wider language than the code generator can encode, and the code generator raises "not yet supported" with the source location for the rest.

Roadmap items that parse today and are refused:

| Feature | Example | What it needs |
| --- | --- | --- |
| Parenthesized logic | `A(` ... `)` | rows for the nesting operations; the corpus has them, 6 vectors |
| Fully qualified data block access | `A DB1.DBX 0.0`, `L DB1.DBD 4` | a row for `OPN DB`, emitted before the access |
| Boolean constants | `L TRUE`, `L FALSE` | an encoding; the corpus has none |

**Why.** A program that assembles but means something else is worse than one that does not assemble.
Keeping the parser ahead of the code generator lets the error name the exact statement.

**Enforced by.** `tests/test_codegen.py`; `examples/nesting.awl` is the example that is expected to be refused.

## D9. Unknown opcodes are reported, and decoding continues

**Decision.** The disassembler lists bytes without a table row as unknown, with their offset, steps over one 2-byte word and warns that later instruction boundaries are not certain.

**Why.** All corpus instructions are 2, 4 or 6 bytes long, so a word is the smallest step.
An unknown instruction may be longer, so the listing after it cannot be trusted blindly, and the report says so instead of hiding it.

## D10. Reading is tolerant, building is strict

**Decision.** A block read from a PLC is parsed losslessly whatever it contains; deviations are findings.
A block built by `mc7asm` must satisfy the layout exactly, and `mc7asm build` writes nothing otherwise.

**Why.** Real blocks are evidence, and rejecting them would discard evidence.
Generated blocks are claims, and a claim that does not hold must not leave the tool.

**Details.** The checksum is outside both: it is never computed or verified, a parsed block keeps its value and a built block gets zero.

## D11. The table is the minimal subset plus what the reference block needs

**Decision.** The opcode table holds bit logic and load/transfer on directly addressed operands, typed constants, and the rows needed to decode `cm7.bin` completely: `FP`, `FN`, `CU`, `CD`, `LC`, `BE`.

**Why.** The stage brief expected a compare-with-zero family at 0xC0 to 0xC7.
The corpus and the C# decoder both show that those bytes are `A` on inputs and outputs, so no such family was needed; what the reference block does need is edge detection and counters.
Each added row has corpus vectors and a C# cross-check.

## D12. The assembler does not talk to a PLC

**Decision.** `mc7asm` never imports the `mc7` communication package, `snap7` or `socket`.

**Why.** Compiling and loading are separate acts.
Loading changes a machine and is done deliberately by the operator with `mc7 download`, which asks for confirmation and verifies the result.

**Enforced by.** `tests/test_mc7asm_skeleton.py` imports every module of `mc7asm` in a fresh interpreter and checks that none of the three was loaded.
The only script that reads from a PLC, `scripts/capture_fixtures.py`, is limited to listing and uploading, which `tests/test_capture_fixtures.py` checks.

## D13. The length field is binding for code blocks

**Decision.** `validate_image` reports a length field at offset 8 that is not the file size as an error for an OB, FC or FB.
For every other block type it stays a warning.
Bytes that no length field accounts for stay a note, exactly as before.

**Why.** The field is the file size in the reference block and in the OB1 and the FC1 uploaded from a CPU 317-2 DP, and the CPU reports the same number as the load size of the block.
The real DB1 agrees as well, but one data block was the only evidence for its type, so the severity for it was left alone.
The later scan found the same for all 86 data blocks of that CPU; raising the severity for data blocks is a decision that has not been taken.

**Details.** An error is still a finding and not a refusal: the image is parsed, dumped and written back unchanged.
For built blocks nothing changes, because `validate_generated_image` already treats every finding as an error.

**Enforced by.** `tests/test_image.py` for each block type, `tests/test_image_fixtures.py` for the blocks that came from a CPU.

## D14. A data block is its current values, then its declarations

**Decision.** For a DB the bytes at offset 36 are the current values, with the length at offset 34, and the section behind them is the interface, with the length at offset 28.
This is the split the image model already made; the real DB1 confirmed it, and the model now also reads the 7-byte sub-header of the interface.
Data blocks are still not built.

**Why.** The real DB1 adds up exactly this way, its declarations describe as many bytes as the body has, the CPU lets one read exactly that many bytes, and the body follows the running program.
The second meaning that the header comment of `MC7Converter.cs` gives the two fields does not fit any of that.
The evidence is in [mc7-structure.md](mc7-structure.md#data-blocks).

**Start values.** DB1 has none, so the question where they are stayed open at first.
A scan of all 86 data blocks of the same CPU, which kept lengths only, settled it: they lie behind the declarations inside the interface section, and the field at offset 28 counts them.
`TODO(real-db-fixture)` is closed, and the finding `start-values` that announced such a block is gone again.
The same scan showed that an interface section is padded to an even length, which is what the byte after the declarations is.

**Enforced by.** `tests/test_image_fixtures.py`.

## D15. Real blocks correct the builder; the reference block still defines what it writes

**Decision.** The word after the kind byte of the interface is written as zero for every code block.
Nothing else in the builder changed after the comparison with the real OB1 and FC1.

**Why.** The builder wrote the block number there for an FC or FB, following a comment in `MC7Converter.cs`, and the real FC1 has zero.
A real block outranks a comment.
The real blocks were written in FBD, and what they have beyond the reference block belongs to that: `BLD` and `NOP 0` in the code, jump positions and one more word in the segment table.
The builder writes STL blocks, and `cm7.bin` is the only STL block there is, so its form stays the model.

**Consequence.** The images in `examples/expected` of every FC and FB changed in those two bytes.
The notes of `mc7asm build` now say what is confirmed by a real block and what is not.

**Enforced by.** `tests/test_container.py`, `tests/test_end_to_end.py`.
