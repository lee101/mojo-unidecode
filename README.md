# mojo-unidecode

`mojo-unidecode` is a Mojo-accelerated port of the
[Unidecode](https://pypi.org/project/Unidecode/) Unicode-to-ASCII
transliterator. It keeps Python's convenient string API while moving the
table lookup and output-copy loop into a small native Mojo shared library.

The port covers the complete Unidecode 1.4.0 transliteration table: 43,120
defined replacements through U+1F6FF, ASCII pass-through, unmapped characters,
surrogate warnings, and the `ignore`, `strict`, `replace`, and `preserve` error
modes. The callable names and signatures are:

```python
unidecode(string, errors="ignore", replace_str="?")
unidecode_expect_ascii(string, errors="ignore", replace_str="?")
unidecode_expect_nonascii(string, errors="ignore", replace_str="?")
```

`UnidecodeError`, including its `index` attribute, is also provided.

This is not a replacement for upstream's command-line program or its private
lazy-loaded `xNNN` Python table modules. Import it as `mojo_unidecode`, or alias
that module where a covered caller expects `unidecode`.

## Install

Install the pinned Mojo nightly and Python dependencies, then build the shared
library:

```bash
pixi install
pixi run build
```

The build produces `dist/libmojo-unidecode.so`.

## Usage

Run this example from the repository:

```bash
pixi run python -c \
  'from mojo_unidecode import unidecode; print(unidecode("Café, Москва, 北京"))'
```

It prints:

```text
Cafe, Moskva, Bei Jing 
```

The error behavior matches upstream:

```python
from mojo_unidecode import unidecode

unidecode("text \U0001f9cc", errors="replace", replace_str="[unknown]")
unidecode("text \U0001f9cc", errors="preserve")
```

## Benchmarks

Measured with `pixi run bench` on this x86_64 host running Linux 6.8.0, using
Unidecode 1.4.0. Times are the best of five runs. The benchmark asserts equal
output before timing.

| Input | mojo-unidecode | Unidecode 1.4.0 | Speedup |
|---|---:|---:|---:|
| ASCII, 1.20M chars | 0.08 ms | 0.08 ms | 0.98x |
| Latin, 1.20M chars | 9.80 ms | 445.48 ms | 45.45x |
| Cyrillic, 1.08M chars | 10.08 ms | 610.13 ms | 60.55x |
| CJK, 1.00M chars | 18.61 ms | 617.76 ms | 33.20x |
| Mixed, 1.04M chars | 10.47 ms | 404.53 ms | 38.65x |

ASCII takes the same fast path as upstream and does not enter Mojo. For the
non-ASCII workloads above, Mojo is 33.20x to 60.55x faster.

There is no GPU path. The work consists primarily of table lookups and short
byte copies, for which host/device transfer and launch overhead are a poor
fit.

## How it works

Python first attempts ASCII encoding, preserving upstream's near-zero-cost
ASCII path. Non-ASCII strings are represented as a contiguous little-endian
UTF-32 buffer. The transliteration data is a 693 KiB direct-indexed layout:
one signed 32-bit payload offset and one 8-bit length per code point, followed
by deduplicated ASCII replacement bytes. The native measure pass also detects
surrogates; only the rare positive result triggers Python's warning scan.

All arrays remain owned by Python. Their addresses cross the C ABI as 64-bit
integers and Mojo reconstructs fixed-origin pointers inside the exported
functions. SIMD handles contiguous input, ASCII runs, and replacement-byte
copies, with scalar remainder loops. A first Mojo pass measures the exact
result and reports strict-mode errors; a second pass fills one output buffer.
Python then decodes those bytes and constructs the final string. Nothing is
allocated or retained by Mojo.

## Verification and licensing

`pixi run test` compares representative text, every supported error mode,
public signatures, warning behavior, and every code point in the complete
upstream table range against the real Unidecode package.

The new Mojo and Python source is MIT licensed. The packed transliteration
table is mechanically generated from Unidecode 1.4.0 and retains its
GPL-2.0-or-later licensing, so the combined distribution is
GPL-2.0-or-later. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and
`third_party/UNIDECODE_LICENSE`.
