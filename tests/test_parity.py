from __future__ import annotations

import inspect
import warnings

import numpy as np
import pytest
import unidecode as upstream

import mojo_unidecode as mojo
from mojo_unidecode._lib import address, lib, table


@pytest.mark.parametrize(
    "text",
    [
        "",
        "plain ASCII",
        "Café déjà vu",
        "kožušček",
        "Κνωσός",
        "Москва и Санкт-Петербург",
        "北京, 中國",
        "30 \N{EURO SIGN} / \N{POUND SIGN} 5",
        "北亰",
        "emoji \N{GRINNING FACE} is unmapped",
        "naïve—résumé… №42",
    ],
)
def test_published_and_representative_vectors(text: str) -> None:
    assert mojo.unidecode(text) == upstream.unidecode(text)
    assert mojo.unidecode_expect_nonascii(text) == upstream.unidecode_expect_nonascii(text)


@pytest.mark.parametrize("errors", ["ignore", "replace", "preserve"])
@pytest.mark.parametrize("replace_str", ["?", "[unknown]", "", "ø"])
def test_error_modes(errors: str, replace_str: str) -> None:
    text = "known café \U0001f9cc unknown \U000f0000 end"
    assert mojo.unidecode(text, errors, replace_str) == upstream.unidecode(
        text, errors, replace_str
    )


def test_strict_error_matches_index_and_message() -> None:
    text = "café \U0001f9cc"
    with pytest.raises(upstream.UnidecodeError) as reference:
        upstream.unidecode(text, errors="strict")
    with pytest.raises(mojo.UnidecodeError) as actual:
        mojo.unidecode(text, errors="strict")
    assert actual.value.index == reference.value.index
    assert str(actual.value) == str(reference.value)


def test_invalid_errors_matches_upstream() -> None:
    assert mojo.unidecode("é", errors="wat") == upstream.unidecode("é", errors="wat")
    with pytest.raises(mojo.UnidecodeError, match="invalid value"):
        mojo.unidecode("é\U0001f9cc", errors="wat")
    assert mojo.unidecode("ASCII", errors="wat") == "ASCII"


def test_surrogate_warning_and_result_match() -> None:
    text = "a\ud800b"
    with warnings.catch_warnings(record=True) as reference_warnings:
        warnings.simplefilter("always")
        expected = upstream.unidecode(text)
    with warnings.catch_warnings(record=True) as actual_warnings:
        warnings.simplefilter("always")
        actual = mojo.unidecode(text)
    assert actual == expected
    assert len(actual_warnings) == len(reference_warnings)
    assert str(actual_warnings[0].message) == str(reference_warnings[0].message)


def test_surrogate_warning_after_strict_error_matches() -> None:
    text = "\U0001f9cc before \ud800"
    with warnings.catch_warnings(record=True) as reference_warnings:
        warnings.simplefilter("always")
        with pytest.raises(upstream.UnidecodeError):
            upstream.unidecode(text, errors="strict")
    with warnings.catch_warnings(record=True) as actual_warnings:
        warnings.simplefilter("always")
        with pytest.raises(mojo.UnidecodeError):
            mojo.unidecode(text, errors="strict")
    assert [str(item.message) for item in actual_warnings] == [
        str(item.message) for item in reference_warnings
    ]


@pytest.mark.parametrize("input_tail", range(8))
def test_simd_input_and_replacement_tails(input_tail: int) -> None:
    replacements = "".join(
        chr(codepoint)
        for codepoint in (
            0x00A0,
            0x00A2,
            0x00A9,
            0x00BC,
            0x0BF1,
            0x0482,
            0x09F8,
            0x2662,
            0x0488,
            0x2654,
            0x0489,
            0x2657,
            0x722B,
        )
    )
    text = "vectorized ASCII run " + replacements + ("x" * input_tail)
    assert mojo.unidecode_expect_nonascii(text) == upstream.unidecode_expect_nonascii(
        text
    )


def test_ascii_fast_path_preserves_identity() -> None:
    text = "same object"
    assert mojo.unidecode(text) is text


def test_public_signatures_match() -> None:
    for name in ("unidecode", "unidecode_expect_ascii", "unidecode_expect_nonascii"):
        assert inspect.signature(getattr(mojo, name)) == inspect.signature(
            getattr(upstream, name)
        )


def test_ffi_buffers_have_native_layout_and_are_contiguous() -> None:
    offsets, lengths, payload = table()
    assert offsets.dtype == np.dtype("<i4")
    assert lengths.dtype == np.dtype("u1")
    assert payload.dtype == np.dtype("u1")
    assert offsets.flags.c_contiguous
    assert lengths.flags.c_contiguous
    assert payload.flags.c_contiguous


def test_ffi_rejects_an_undersized_destination() -> None:
    codepoints = np.array([ord("A")], dtype="<u4")
    offsets, lengths, payload = table()
    destination = np.empty(1, dtype=np.uint8)
    written = lib().mud_transliterate(
        address(codepoints),
        codepoints.size,
        address(offsets),
        address(lengths),
        address(payload),
        offsets.size,
        0,
        0,
        0,
        address(destination),
        0,
    )
    assert written < 0


def test_every_upstream_table_entry() -> None:
    for start in range(0x80, 0x1F700, 8192):
        stop = min(start + 8192, 0x1F700)
        text = "".join(
            chr(codepoint)
            for codepoint in range(start, stop)
            if not 0xD800 <= codepoint <= 0xDFFF
        )
        assert mojo.unidecode_expect_nonascii(text) == upstream.unidecode_expect_nonascii(
            text
        )
