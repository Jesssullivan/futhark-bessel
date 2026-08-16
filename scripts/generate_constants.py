#!/usr/bin/env python3
"""Regenerate range-reduction constants from the Chudnovsky definition."""

from __future__ import annotations

import argparse
import struct
from decimal import Decimal, getcontext
from pathlib import Path


def chudnovsky_pi() -> Decimal:
    getcontext().prec = 120
    c = Decimal(426880) * Decimal(10005).sqrt()
    m, ell, x, k = 1, 13591409, 1, 6
    series = Decimal(ell)
    for i in range(1, 12):
        m = (k**3 - 16 * k) * m // i**3
        ell += 545140134
        x *= -262537412640768000
        series += Decimal(m * ell) / Decimal(x)
        k += 12
    return c / series


def f32(value: Decimal) -> float:
    return struct.unpack(">f", struct.pack(">f", float(value)))[0]


def f32_split(value: Decimal, clear_bits: int) -> tuple[float, float, float]:
    nearest = f32(value)
    bits = struct.unpack(">I", struct.pack(">f", nearest))[0]
    hi = struct.unpack(">f", struct.pack(">I", bits & ~((1 << clear_bits) - 1)))[0]
    lo = f32(value - Decimal(hi))
    tail = f32(value - Decimal(hi) - Decimal(lo))
    return hi, lo, tail


def f64_split(value: Decimal, clear_bits: int) -> tuple[float, float, float]:
    bits = struct.unpack(">Q", struct.pack(">d", float(value)))[0]
    hi = struct.unpack(">d", struct.pack(">Q", bits & ~((1 << clear_bits) - 1)))[0]
    lo = float(value - Decimal(hi))
    tail = float(value - Decimal(hi) - Decimal(lo))
    return hi, lo, tail


def constants() -> list[str]:
    pi = chudnovsky_pi()
    f64_hi, f64_lo, f64_tail = f64_split(pi / 2, 24)
    f32_hi, f32_lo, f32_tail = f32_split(pi / 2, 10)
    values = [
        float(Decimal(2) / pi).hex(),
        f64_hi.hex(),
        f64_lo.hex(),
        f64_tail.hex(),
        float(pi).hex(),
        float(pi / 4).hex(),
        float(3 * pi / 4).hex(),
        f32(Decimal(2) / pi).hex() + "f32",
        f32_hi.hex() + "f32",
        f32_lo.hex() + "f32",
        f32_tail.hex() + "f32",
        f32(pi).hex() + "f32",
        f32(pi / 4).hex() + "f32",
        f32(3 * pi / 4).hex() + "f32",
    ]
    return values


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    generated = constants()
    if args.check:
        source = Path(
            "lib/github.com/Jesssullivan/futhark-bessel/bessel_internal.fut"
        ).read_text()
        missing = [value for value in generated if value not in source]
        if missing:
            raise SystemExit(f"generated constants missing from source: {missing}")
        print(f"OK {len(generated)} definition-generated hexadecimal constants")
    else:
        print("\n".join(generated))


if __name__ == "__main__":
    main()
