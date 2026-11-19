# Examples

One STL source per feature, each with the block image it must build to.
The images in `expected/` are committed, and a test fails if a build no longer produces them.

| Source | Shows | Block | Image |
| --- | --- | --- | --- |
| `bit_logic.awl` | `A`, `AN`, `O`, `ON`, with 2-byte and 4-byte encodings | FC 10 | `expected/bit_logic.mc7` |
| `set_reset.awl` | `=`, `S`, `R` | FC 11 | `expected/set_reset.mc7` |
| `edges.awl` | `FP`, `FN` | FC 12 | `expected/edges.mc7` |
| `load_transfer.awl` | `L`, `T` on bytes, words and double words in every area | FC 13 | `expected/load_transfer.mc7` |
| `constants.awl` | every constant notation the code generator accepts | FC 14 | `expected/constants.mc7` |
| `counters.awl` | `CU`, `CD`, `LC` | FC 15 | `expected/counters.mc7` |
| `networks.awl` | several networks, titles, comments, an empty network | FC 16 | `expected/networks.mc7` |
| `function_block.awl` | a function block | FB 1 | `expected/function_block.mc7` |
| `cyclic_interrupt.awl` | an organization block other than OB1 | OB 35 | `expected/cyclic_interrupt.mc7` |
| `blink.awl` | a small program using most features | OB 1 | `expected/blink.mc7` |
| `blink_de.awl` | the same program in German mnemonics | OB 1 | `expected/blink_de.mc7` |
| `counter.awl` | the program of the reference block as an FC with two networks | FC 1 | `expected/counter.mc7` |
| `reference_ob1.awl` | the program of the reference block as it is, one network in OB 1 | OB 1 | `expected/reference_ob1.mc7` |
| `orphan.awl` | a block nothing calls, whose transfers write each value back where it came from; meant for a first download to a CPU | FC 270 | `expected/orphan.mc7` |
| `nesting.awl` | statements that parse but are refused by the code generator | FB 7 | none |

## Building them

```bash
mc7asm build examples/bit_logic.awl -o bit_logic.mc7 --timestamp 2024-01-01T00:00:00
```

All images use the timestamp 2024-01-01 00:00:00, so a build is reproducible.
Sources whose name ends in `_de` are built with `--mnemonics de`.
`blink.mc7` and `blink_de.mc7` are identical.

To rebuild every image, or to check them:

```bash
uv run python scripts/build_examples.py
```

```bash
uv run python scripts/build_examples.py --check
```

## Looking at an image

```bash
mc7asm dump examples/expected/bit_logic.mc7
```

```bash
mc7asm disasm examples/expected/bit_logic.mc7
```

## What these images are

They are what this toolchain builds, checked against its own rules and against the reference block.
`reference_ob1.mc7` has the same bytes as that real block except for the timestamps and the checksum.
None of the images has been loaded into a CPU.

`nesting.awl` has no image on purpose: it uses parentheses, a fully qualified data block address and `TRUE`, which the code generator does not support yet.
