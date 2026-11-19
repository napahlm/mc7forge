# Block container

This document describes how `mc7asm build` wraps compiled MC7 code into a block image, and what each byte it writes is based on.
The layout itself is documented in [mc7-structure.md](mc7-structure.md); the decisions behind the builder are in [decisions.md](decisions.md).

## Design rule

`mc7asm.container` is pure.
It takes compiled code and a timestamp and returns a block image; it reads and writes no file and imports nothing from the `mc7` communication package.
The command `mc7asm build` writes exactly one file, the one it is given.
Building a block and loading it into a CPU are separate concerns: loading is `mc7 download`, which asks for confirmation and verifies the block afterwards.

## Layout

The field map, the decoded reference block and the provenance of every field are in [mc7-structure.md](mc7-structure.md).
This document only covers what the builder does with it.

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
| Interface, FC and FB | `01`, a zero word, no declarations, padding byte `20` | the sub-header of a real FC1; the empty declarations are generalized |
| Local data length | 20 for an OB, 0 for an FC or FB without declarations | reference block; generalized for FC and FB |
| Segment table | count, one length per network without the `BE`, zero word | the reference block; count and lengths also seen on real blocks with 5 and 19 networks |
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

Compared afterwards with an OB1 and an FC1 uploaded from a CPU 317-2 DP, both written in FBD; the evidence is in [mc7-structure.md](mc7-structure.md).

- Confirmed: the length equation, the closing `BE` behind the last network, the network count and one length per network for 5 and 19 networks, and the form of the interface sub-header for an FC.
- Corrected: the word after the kind byte of the interface is zero in the real FC1.
  The builder used to write the block number there for an FC or FB, following a comment in `MC7Converter.cs`; it now writes zero.
- Not imitated: the FBD blocks list the positions of their jumps in the segment table and end it with one more word.
  The builder writes STL blocks without jumps, and the only STL block, `cm7.bin`, has a zero word there.

Generalized, and reported by `mc7asm build` as a note:

- an FC without declarations, and everything about the interface of an FB, of which no real one has been examined,
- the declarations of an OB other than OB1, which gets the temporary variables of OB1,
- what follows the network lengths in the segment table of an STL block with more than one network.

Not decided by any source, and since tried on one CPU:

- a zero checksum on download: a CPU 317-2 DP accepted it and reports zero for the block,
- the "linked" bit in a block that is about to be downloaded: the same CPU accepted the block with the bit set.

One block built by `mc7asm` has been loaded into a CPU and came back byte for byte: `examples/expected/orphan.mc7`, an FC that nothing calls.
No built block has been executed by a CPU.
The record is D16 in the [decision log](decisions.md).

## Validation before writing

`mc7asm build` serializes the image, parses those bytes again and runs `validate_generated_image` on the result.
If anything is reported, nothing is written.
The checks are:

- length field at offset 8 = file size = 36 + code length + interface length + segment table length + 36, with no unaccounted bytes,
- the interface is as long as its sub-header says,
- the attribute byte has only documented bits, the language code is a known one, and the block type is OB, FC or FB,
- the code section ends with `65 00`.

The checksum is not part of the validation.
Blocks read from a PLC are not held to this profile: for them `validate_image` keeps its tolerance, so unaccounted bytes stay a note.
A length field that is not the file size is an error for a code block since the real blocks confirmed it, and a warning for other blocks; either way it is a finding, and the block is still parsed and dumped.

## Out of scope

Data blocks are not built.
Real blocks settled where their values, their declarations and their start values are, see [mc7-structure.md](mc7-structure.md#data-blocks); how start values are encoded is not known well enough to write them.
Declaration sections in source are a syntax error, so a built FC or FB has no parameters or local variables.
