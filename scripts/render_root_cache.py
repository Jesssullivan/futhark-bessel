#!/usr/bin/env python3
"""Render disposable Futhark root brackets from independent Arb evidence."""

from __future__ import annotations

import argparse
import json
import math
import re
import struct
from pathlib import Path

EVIDENCE = Path("evidence/arb-certificates.jsonl")
CACHE = Path("lib/github.com/Jesssullivan/futhark-bessel/root_cache.fut")


def as_f32(value: float) -> float:
    return struct.unpack(">f", struct.pack(">f", value))[0]


def f32_bits(value: float) -> int:
    return struct.unpack(">I", struct.pack(">f", value))[0]


def from_f32_bits(bits: int) -> float:
    return struct.unpack(">f", struct.pack(">I", bits))[0]


def from_f64_bits(bits: int) -> float:
    return struct.unpack(">d", struct.pack(">Q", bits))[0]


def reference_bits(row: dict[str, object], precision: str) -> int:
    width = 32 if precision == "f32" else 64
    field = f"root_{precision}_reference_bits"
    text = row.get(field)
    if not isinstance(text, str) or not re.fullmatch(
        rf"0x[0-9a-f]{{{width // 4}}}", text
    ):
        raise SystemExit(f"malformed {precision} root reference bits")
    return int(text, 16)


def outward_f32(lo: float, hi: float) -> tuple[float, float]:
    lo32 = as_f32(lo)
    hi32 = as_f32(hi)
    if lo32 > lo:
        lo32 = from_f32_bits(f32_bits(lo32) - 1)
    if hi32 < hi:
        hi32 = from_f32_bits(f32_bits(hi32) + 1)
    return lo32, hi32


def array(name: str, scalar: str, values: list[str]) -> str:
    chunks = [values[i : i + 4] for i in range(0, len(values), 4)]
    lines = [f"  def {name}: [256]{scalar} = ["]
    for index, chunk in enumerate(chunks):
        suffix = "," if index < len(chunks) - 1 else ""
        lines.append("    " + ", ".join(chunk) + suffix)
    lines.append("  ]")
    return "\n".join(lines)


def render() -> str:
    rows = [json.loads(line) for line in EVIDENCE.read_text().splitlines()]
    roots = [row for row in rows if row["kind"] == "j1_root_bracket"]
    roots.sort(key=lambda row: row["index"])
    if [row["index"] for row in roots] != list(range(1, 257)):
        raise SystemExit("root evidence must contain exactly indices 1..256")
    required = {
        "kind",
        "index",
        "lo_hex",
        "hi_hex",
        "j1_lo",
        "j1_hi",
        "root_f64_reference_bits",
        "root_f32_reference_bits",
        "bisections",
        "certified_sign_change",
        "certified_unique_rounding",
    }
    for row in roots:
        if set(row) != required:
            raise SystemExit(f"root evidence fields drifted at index {row['index']}")
        if row["bisections"] != 160:
            raise SystemExit(f"root bisection count drifted at index {row['index']}")
        if row["certified_sign_change"] is not True:
            raise SystemExit(f"missing root sign-change proof at index {row['index']}")
        if row["certified_unique_rounding"] is not True:
            raise SystemExit(f"missing root rounding proof at index {row['index']}")

    lo64 = [row["lo_hex"] for row in roots]
    hi64 = [row["hi_hex"] for row in roots]
    root64_values = [
        from_f64_bits(reference_bits(row, "f64")) for row in roots
    ]
    root32_values = [
        from_f32_bits(reference_bits(row, "f32")) for row in roots
    ]
    pairs32 = [
        outward_f32(float.fromhex(row["lo_hex"]), float.fromhex(row["hi_hex"]))
        for row in roots
    ]
    for index, (row, root64, root32, pair32) in enumerate(
        zip(roots, root64_values, root32_values, pairs32, strict=True), start=1
    ):
        lo = float.fromhex(row["lo_hex"])
        hi = float.fromhex(row["hi_hex"])
        if not all(math.isfinite(value) for value in (lo, hi, root64, root32)):
            raise SystemExit(f"nonfinite root evidence at index {index}")
        lo_bits = struct.unpack(">Q", struct.pack(">d", lo))[0]
        hi_bits = struct.unpack(">Q", struct.pack(">d", hi))[0]
        if hi_bits != lo_bits + 1:
            raise SystemExit(f"non-adjacent f64 root bracket at index {index}")
        if not lo <= root64 <= hi:
            raise SystemExit(f"certified f64 root escaped bracket at index {index}")
        if not pair32[0] <= root32 <= pair32[1]:
            raise SystemExit(f"certified f32 root escaped bracket at index {index}")
    root64 = [value.hex() for value in root64_values]
    lo32 = [value[0].hex() + "f32" for value in pairs32]
    hi32 = [value[1].hex() + "f32" for value in pairs32]
    root32 = [value.hex() + "f32" for value in root32_values]

    sections = [
        "-- SPDX-License-Identifier: ISC",
        "-- GENERATED DISPOSABLE CACHE. Authority: oracle/arb_oracle.c.",
        "-- Regenerate with `just oracle` then scripts/render_root_cache.py.",
        "",
        "module f64_cache = {",
        array("lo", "f64", lo64),
        array("hi", "f64", hi64),
        array("root", "f64", root64),
        "}",
        "",
        "module f32_cache = {",
        array("lo", "f32", lo32),
        array("hi", "f32", hi32),
        array("root", "f32", root32),
        "}",
        "",
    ]
    return "\n".join(sections)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    generated = render()
    if args.check:
        if not CACHE.exists() or CACHE.read_text() != generated:
            raise SystemExit("root cache is stale; run scripts/render_root_cache.py")
        print("OK disposable root cache matches 256 independent Arb certificates")
    else:
        CACHE.write_text(generated)
        print(f"wrote {CACHE}")


if __name__ == "__main__":
    main()
