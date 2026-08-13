#!/usr/bin/env python3
"""Independent multiprecision spot cross-check of Arb certificates."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import mpmath as mp


def parse_ball(text: str) -> tuple[mp.mpf, mp.mpf]:
    text = text.removeprefix("[").removesuffix("]")
    exact = re.fullmatch(r"([+-]?[0-9.]+(?:e[+-]?[0-9]+)?)", text)
    if exact:
        value = mp.mpf(exact.group(1))
        return value, value
    ball = re.fullmatch(
        r"([+-]?[0-9.]+(?:e[+-]?[0-9]+)?) \+/- ([0-9.]+(?:e[+-]?[0-9]+)?)",
        text,
    )
    if not ball:
        raise ValueError(f"unsupported Arb ball: {text}")
    mid = mp.mpf(ball.group(1))
    rad = mp.mpf(ball.group(2))
    return mid - rad, mid + rad


def main(path_text: str) -> None:
    mp.mp.dps = 100
    rows = [json.loads(line) for line in Path(path_text).read_text().splitlines()]
    for row in rows:
        x = mp.mpf(row["x"])
        order = 0 if row["kind"] == "j0" else 1
        reference = mp.besselj(order, x)
        lo, hi = parse_ball(row["value"])
        if not lo <= reference <= hi:
            raise SystemExit(
                f"mpmath reference escaped Arb ball: {row['kind']}({row['x']})"
            )
    print(f"OK mpmath cross-check contained in {len(rows)} Arb certificates")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: mpmath_crosscheck.py CERTIFICATES.jsonl")
    main(sys.argv[1])
