"""Generate the compact lookup table consumed by mojo-unidecode.

This is a maintainer tool. It requires the upstream Unidecode distribution
whose table data is being packed.
"""

from __future__ import annotations

import array
import importlib
import pathlib
import struct
import sys

import unidecode


MAGIC = b"MUDATA1\0"
ROOT = pathlib.Path(__file__).resolve().parents[1]
DEST = ROOT / "python" / "mojo_unidecode" / "data.bin"


def main() -> None:
    if sys.byteorder != "little":
        raise RuntimeError("the generated table format is little-endian")

    package_dir = pathlib.Path(unidecode.__file__).resolve().parent
    modules = sorted(package_dir.glob("x[0-9a-f][0-9a-f][0-9a-f].py"))
    if not modules:
        raise RuntimeError("no upstream Unidecode table modules found")

    table_size = (max(int(path.stem[1:], 16) for path in modules) + 1) * 256
    offsets = array.array("i", [-1]) * table_size
    lengths = bytearray(table_size)
    payload = bytearray()
    interned: dict[bytes, int] = {}
    max_length = 0

    for path in modules:
        section = int(path.stem[1:], 16)
        table = importlib.import_module(f"unidecode.{path.stem}").data
        for position, replacement in enumerate(table):
            if replacement is None:
                continue
            encoded = replacement.encode("ascii")
            offset = interned.get(encoded)
            if offset is None:
                offset = len(payload)
                interned[encoded] = offset
                payload.extend(encoded)
            codepoint = section * 256 + position
            offsets[codepoint] = offset
            lengths[codepoint] = len(encoded)
            max_length = max(max_length, len(encoded))

    DEST.parent.mkdir(parents=True, exist_ok=True)
    header = struct.pack("<8sIII", MAGIC, table_size, len(payload), max_length)
    with DEST.open("wb") as stream:
        stream.write(header)
        offsets.tofile(stream)
        stream.write(lengths)
        stream.write(payload)

    print(
        f"wrote {DEST}: {table_size} slots, {len(payload)} payload bytes, "
        f"maximum replacement {max_length} bytes"
    )


if __name__ == "__main__":
    main()
