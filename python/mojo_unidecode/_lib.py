"""Shared-library and transliteration-table loading."""

from __future__ import annotations

import ctypes
import os
import pathlib
import shutil
import subprocess
import sys
import threading

import numpy as np


ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "unidecode.mojo"
LIB = pathlib.Path(
    os.environ.get("MOJO_UNIDECODE_LIB", ROOT / "dist" / "libmojo-unidecode.so")
)
DATA = pathlib.Path(__file__).with_name("data.bin")
HEADER_SIZE = 20

I = ctypes.c_int64
_SIGNATURES = {
    "mud_measure": ([I, I, I, I, I, I, I, I], I),
    "mud_transliterate": ([I, I, I, I, I, I, I, I, I, I, I], I),
}

_library: ctypes.CDLL | None = None
_table: tuple[bytes, np.ndarray, np.ndarray, np.ndarray] | None = None
_lock = threading.Lock()


class BuildError(RuntimeError):
    pass


def build(force: bool = False) -> pathlib.Path:
    if not force and LIB.exists() and LIB.stat().st_mtime >= SRC.stat().st_mtime:
        return LIB
    mojo = shutil.which("mojo")
    if mojo is None:
        raise BuildError("mojo was not found; run `pixi run build`")
    LIB.parent.mkdir(parents=True, exist_ok=True)
    process = subprocess.run(
        [mojo, "build", "--emit", "shared-lib", str(SRC), "-o", str(LIB)],
        capture_output=True,
        text=True,
        timeout=1800,
    )
    if process.returncode or not LIB.exists():
        raise BuildError((process.stderr or process.stdout).strip()[:4000])
    return LIB


def lib() -> ctypes.CDLL:
    global _library
    if _library is None:
        with _lock:
            if _library is None:
                loaded = ctypes.CDLL(build())
                for name, (argtypes, restype) in _SIGNATURES.items():
                    function = getattr(loaded, name)
                    function.argtypes = argtypes
                    function.restype = restype
                _library = loaded
    return _library


def table() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    global _table
    if _table is None:
        raw = DATA.read_bytes()
        magic = raw[:8]
        if magic != b"MUDATA1\0":
            raise RuntimeError("invalid mojo-unidecode data table")
        table_size = int.from_bytes(raw[8:12], "little")
        payload_size = int.from_bytes(raw[12:16], "little")
        maximum_length = int.from_bytes(raw[16:20], "little")
        if sys.byteorder != "little":
            raise RuntimeError("mojo-unidecode requires a little-endian host")
        if not table_size or not payload_size or maximum_length > 255:
            raise RuntimeError("invalid mojo-unidecode data table header")
        offsets_end = HEADER_SIZE + table_size * 4
        lengths_end = offsets_end + table_size
        payload_end = lengths_end + payload_size
        if payload_end != len(raw):
            raise RuntimeError("truncated mojo-unidecode data table")
        offsets = np.frombuffer(raw, dtype="<i4", count=table_size, offset=HEADER_SIZE)
        lengths = np.frombuffer(raw, dtype=np.uint8, count=table_size, offset=offsets_end)
        payload = np.frombuffer(raw, dtype=np.uint8, count=payload_size, offset=lengths_end)
        mapped = offsets >= 0
        if np.any(offsets[mapped].astype(np.int64) + lengths[mapped] > payload_size):
            raise RuntimeError("invalid offset in mojo-unidecode data table")
        if int(lengths.max(initial=0)) != maximum_length:
            raise RuntimeError("invalid maximum length in mojo-unidecode data table")
        _table = raw, offsets, lengths, payload
    return _table[1:]


def address(array: np.ndarray) -> int:
    return int(array.ctypes.data)
