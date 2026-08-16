#!/usr/bin/env python3
"""Independent multiprecision spot cross-check of Arb certificates."""

from __future__ import annotations

import json
import re
import struct
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
        if row["kind"] == "j1_root_bracket":
            reference = mp.besseljzero(1, row["index"])
            lo = mp.mpf(float.fromhex(row["lo_hex"]))
            hi = mp.mpf(float.fromhex(row["hi_hex"]))
            if not lo < reference < hi:
                raise SystemExit(
                    f"mpmath root escaped Arb bracket: J1 root {row['index']}"
                )
            rounded64 = struct.unpack(">Q", struct.pack(">d", float(reference)))[0]
            rounded32 = struct.unpack(
                ">I", struct.pack(">f", float(reference))
            )[0]
            if rounded64 != int(row["root_f64_reference_bits"], 16):
                raise SystemExit(
                    f"mpmath disagrees with rounded f64 root {row['index']}"
                )
            if rounded32 != int(row["root_f32_reference_bits"], 16):
                raise SystemExit(
                    f"mpmath disagrees with rounded f32 root {row['index']}"
                )
            continue
        if row["kind"] == "conformance_value":
            if row["precision"] == "f32":
                x = struct.unpack(
                    ">f", struct.pack(">I", int(row["x_bits"], 16))
                )[0]
                pack_format = ">f"
                bits_format = ">I"
            else:
                x = struct.unpack(
                    ">d", struct.pack(">Q", int(row["x_bits"], 16))
                )[0]
                pack_format = ">d"
                bits_format = ">Q"
            for order in (0, 1):
                reference = mp.besselj(order, mp.mpf(x))
                lo, hi = parse_ball(row[f"j{order}_ball"])
                if not lo <= reference <= hi:
                    raise SystemExit(
                        f"mpmath reference escaped Arb conformance ball: "
                        f"J{order}({x!r})"
                    )
                rounded = struct.unpack(
                    bits_format, struct.pack(pack_format, float(reference))
                )[0]
                if rounded != int(row[f"j{order}_reference_bits"], 16):
                    raise SystemExit(
                        f"mpmath disagrees with rounded {row['precision']} "
                        f"J{order} reference at {x!r}"
                    )
            continue
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
