# Opcode corpus

`test_simatic.c` is the decoder test table of [rz-libmc7](https://github.com/rizinorg/rz-libmc7), vendored verbatim.
It is the opcode ground truth of `mc7asm`: 2,531 active vectors, each giving the bytes of one MC7 instruction, the STL text a decoder must produce and the number of bytes it must consume.

| | |
| --- | --- |
| Upstream file | `unit/test_simatic.c` |
| Upstream commit | `111b189aad531468f9fb1ea07cdbe3e18b7c2d4d` (2026-07-09) |
| Size | 160,984 bytes |
| SHA-256 | `8a93f7ada52c6636f0eef58b9f8fb03b838bad8a766624d6273d9e264ef0d886` |
| Copyright | 2019-2022 deroad, as stated in the file |
| License | LGPL-3.0-only, see `LGPL-3.0-only.txt` in this directory |

Do not edit the file.
`mc7asm.corpus` parses it directly, so there is no second copy of the data, and `tests/test_corpus.py` fails if its hash or its vector counts change.

The table also contains 9 entries that upstream commented out with `// FIXME` and one `NULL` terminator.
The disabled entries are parsed separately and are never used as ground truth.

To move to a newer upstream version, replace the file, then update the commit, size and hash here and the pinned numbers in `tests/test_corpus.py` and `tests/test_disasm.py`.
