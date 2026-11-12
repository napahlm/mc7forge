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
