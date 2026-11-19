# Block fixtures

Reference block images for the `mc7asm` tests.
Every `*.mc7` and `*.bin` file below this directory must re-serialize byte for byte through `mc7asm.image`.

| Directory | Content | How it is produced |
| --- | --- | --- |
| `fake/` | Synthetic stand-ins: `OB1`, `FC1`, `DB1`. | `uv run python scripts/capture_fixtures.py --fake` |
| `reference/` | `cm7.bin`, the sample OB1 of rz-libmc7 (LGPL-3.0-only). | vendored, see its own README |
| `real/` | `OB1`, `FC1` and `DB1`, uploaded on 2026-11-19 from a CPU 317-2 DP. Not in the repository, see below. | `uv run python scripts/capture_fixtures.py --host <ip> [OB1 FC5 DB10]` |

The fake blocks have the documented layout (36-byte header, payload, interface, segment table, 36-byte footer), but their section contents are made up.
They are uploaded from the fake PLC of the test suite, so they travel the same path as a real capture.
A test fails if the committed files differ from what the script produces.

The fake blocks say nothing about the layout of a real block.
A green test run against them only shows that the code agrees with itself; every layout question is settled by `reference/` and `real/`.

The real capture is read-only: it lists blocks and uploads them, nothing else.
Real blocks contain the program of the machine they come from, so check what you commit.
An uploaded data block holds the values of the moment, so a second capture of the same DB differs.

## The real fixtures are not in the repository

The three real blocks come from a CPU that runs a real application.
They carry author marks and live operational data, so they are confidential: `real/` is listed in `.gitignore` and exists only on the machine that captured it.

- The tests that need the blocks are skipped without them; the suite is green with and without `real/`.
- The documentation quotes structural bytes of these blocks only: lengths, sub-headers and segment tables.
  Program content, values and names are never quoted.
  Keep that rule when adding evidence.
- A capture from your own PLC lands in the same ignored directory and is picked up by the same tests.

## What the real fixtures answered

The evidence is written down in [docs/mc7-structure.md](../../../docs/mc7-structure.md).

- The length field at offset 8 is the file size, and no byte is unaccounted for, in an OB, an FC and a DB.
- The code of both code blocks ends with `BE`, behind the last network.
- The segment table is a network count and one length per network, followed by more.
- A data block is its current values (length at offset 34) followed by its declarations (length at offset 28).

## Open question a further capture must answer

`TODO(real-db-fixture)` in `src/mc7asm/image.py`: no block so far has start values.
When a block is captured that has them, the capture script prints a `start-values` note for it.
Look at `mc7asm dump` then:

- if the interface line says "0 byte(s) after them" or "1 byte(s) after them", the start values lie behind the declarations as assumed,
- an `interface-lengths` finding or a non-zero "trailing unknown" size means they lie somewhere else.
