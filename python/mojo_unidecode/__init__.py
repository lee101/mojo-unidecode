"""Fast Unicode-to-ASCII transliteration powered by Mojo."""

import ctypes
import warnings
from typing import Dict, Optional, Sequence

import numpy as np

from ._lib import address, lib, table


Cache: Dict[int, Optional[Sequence[Optional[str]]]] = {}


class UnidecodeError(ValueError):
    def __init__(self, message: str, index: Optional[int] = None) -> None:
        super().__init__(message)
        self.index = index


_MODES = {"ignore": 0, "replace": 1, "preserve": 2, "strict": 3}


def _warn_surrogates(string: str) -> None:
    for char in string:
        if 0xD800 <= ord(char) <= 0xDFFF:
            warnings.warn(
                f"Surrogate character {char!r} will be ignored. "
                "You might be using a narrow Python build.",
                RuntimeWarning,
                stacklevel=3,
            )


def _unknown_error(string: str, index: int) -> UnidecodeError:
    return UnidecodeError(
        f"no replacement found for character {string[index]!r} in position {index}",
        index,
    )


def _unidecode(string: str, errors: str, replace_str: str) -> str:
    if not string:
        return ""

    mode = _MODES.get(errors, 4)
    encoded = string.encode("utf-32le", errors="surrogatepass")
    codepoints = np.frombuffer(encoded, dtype="<u4")
    offsets, lengths, payload = table()
    replacement = replace_str.encode("utf-8", errors="surrogatepass")
    replacement_buffer = ctypes.create_string_buffer(replacement)
    surrogate_found = ctypes.c_int64()
    kernel = lib()

    measured = kernel.mud_measure(
        address(codepoints),
        codepoints.size,
        address(offsets),
        address(lengths),
        offsets.size,
        mode,
        len(replacement),
        ctypes.addressof(surrogate_found),
    )
    if surrogate_found.value:
        _warn_surrogates(string)
    if measured < 0:
        if measured < -len(string):
            raise UnidecodeError(f"invalid value for errors parameter {errors!r}")
        raise _unknown_error(string, -measured - 1)
    if measured == 0:
        return ""

    destination = np.empty(measured, dtype=np.uint8)
    written = kernel.mud_transliterate(
        address(codepoints),
        codepoints.size,
        address(offsets),
        address(lengths),
        address(payload),
        offsets.size,
        mode,
        ctypes.addressof(replacement_buffer),
        len(replacement),
        address(destination),
        destination.size,
    )
    if written != measured:
        raise RuntimeError(
            f"native transliteration wrote {written} bytes; expected {measured}"
        )
    return destination.tobytes().decode("utf-8", errors="surrogatepass")


def unidecode_expect_ascii(
    string: str, errors: str = "ignore", replace_str: str = "?"
) -> str:
    if string.isascii():
        return string
    return _unidecode(string, errors, replace_str)


def unidecode_expect_nonascii(
    string: str, errors: str = "ignore", replace_str: str = "?"
) -> str:
    return _unidecode(string, errors, replace_str)


unidecode = unidecode_expect_ascii

__all__ = [
    "Cache",
    "UnidecodeError",
    "unidecode",
    "unidecode_expect_ascii",
    "unidecode_expect_nonascii",
]
