# Reference block

`cm7.bin` is the sample block of [rz-libmc7](https://github.com/rizinorg/rz-libmc7), vendored verbatim.
It is a real OB1 of 142 bytes and the only block in this repository that did not come from the fake PLC.

| | |
| --- | --- |
| Upstream file | `example/cm7.bin` |
| Upstream commit | `111b189aad531468f9fb1ea07cdbe3e18b7c2d4d` (2026-07-09) |
| SHA-256 | `089f010eb69a6795690d40596eacd094c67f3f46e29b8e91f3e9532a93767c29` |
| Copyright | 2021 RizinOrg, per upstream `.reuse/dep5` |
| License | LGPL-3.0-only, see `LGPL-3.0-only.txt` in this directory |

Its layout adds up exactly: 36 header + 36 code + 28 interface + 6 segment table + 36 footer = 142 bytes, which is also its length field.
`tests/fixtures/golden/cm7.disasm.en.txt` and `cm7.disasm.de.txt` hold its expected disassembly.
