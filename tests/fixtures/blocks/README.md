# Block fixtures

Reference block images for the `mc7asm` tests.
Every `*.mc7` file below this directory must re-serialize byte for byte through `mc7asm.image`.

| Directory | Content | How it is produced |
| --- | --- | --- |
| `fake/` | Synthetic stand-ins: `OB1`, `FC1`, `DB1`. | `uv run python scripts/capture_fixtures.py --fake` |
| `real/` | Blocks uploaded from a real S7-300. | `uv run python scripts/capture_fixtures.py --host <ip> [OB1 FC5 DB10]` |

The fake blocks have the documented layout (36-byte header, payload, interface, segment table, 36-byte footer), but their section contents are made up.
They are uploaded from the fake PLC of the test suite, so they travel the same path as a real capture.
A test fails if the committed files differ from what the script produces.

The real capture is read-only: it lists blocks and uploads them, nothing else.
Real blocks contain the program of the machine they come from, so check what you commit.

## Open question the real fixtures must answer

`TODO(real-db-fixture)` in `src/mc7asm/image.py`: the data block layout is not settled by the public references.
When a real DB is captured, look at the line the capture script prints for it and at `mc7asm dump`:

- a non-zero "trailing unknown" size means the DB carries bytes that no header length field accounts for, most likely start values,
- a `length-field` finding means the length field at offset 8 is not the file size.
