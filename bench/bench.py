from __future__ import annotations

import math
import os
import platform
import sys
import time


sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "python")
)

import mojo_unidecode as mojo  # noqa: E402
import unidecode as upstream  # noqa: E402


def timeit(function, repeat: int = 5) -> float:
    best = math.inf
    for _ in range(repeat):
        start = time.perf_counter()
        function()
        best = min(best, time.perf_counter() - start)
    return best


def benchmark(name: str, text: str) -> tuple[str, float, float, float]:
    ours = lambda: mojo.unidecode(text)
    reference = lambda: upstream.unidecode(text)
    assert ours() == reference()
    mojo_time = timeit(ours)
    upstream_time = timeit(reference)
    return name, mojo_time, upstream_time, upstream_time / mojo_time


def main() -> None:
    cases = [
        ("ASCII, 1.20M chars", "The quick brown fox jumps over the lazy dog. " * 26_667),
        ("Latin, 1.20M chars", "Café déjà vu; naïve résumé. " * 44_445),
        ("Cyrillic, 1.08M chars", "Москва и Санкт-Петербург. " * 43_200),
        ("CJK, 1.00M chars", "北京上海廣州深圳中華人民共和國" * 66_667),
        (
            "Mixed, 1.04M chars",
            "Café Москва 北京 — déjà vu. \N{GRINNING FACE} " * 32_500,
        ),
    ]

    mojo.unidecode("warmup Москва 北京")
    print(f"Machine: {platform.processor() or platform.machine()} ({platform.platform()})")
    print("| Input | mojo-unidecode | Unidecode 1.4.0 | Speedup |")
    print("|---|---:|---:|---:|")
    for name, mojo_time, upstream_time, ratio in (
        benchmark(name, text) for name, text in cases
    ):
        label = "faster" if ratio >= 1 else "slower"
        print(
            f"| {name} | {mojo_time * 1000:.2f} ms | "
            f"{upstream_time * 1000:.2f} ms | {ratio:.2f}x {label} |"
        )


if __name__ == "__main__":
    main()
