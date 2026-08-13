#!/usr/bin/env python3
"""Render disposable Futhark root brackets from independent Arb evidence."""

from __future__ import annotations

import argparse
import json
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


def outward_f32(lo: float, hi: float) -> tuple[float, float, float]:
    midpoint = lo + (hi - lo) / 2.0
    root = as_f32(midpoint)
    lo32 = as_f32(lo)
    hi32 = as_f32(hi)
    if lo32 > lo:
        lo32 = from_f32_bits(f32_bits(lo32) - 1)
    if hi32 < hi:
        hi32 = from_f32_bits(f32_bits(hi32) + 1)
    return lo32, hi32, root


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

    lo64 = [row["lo_hex"] for row in roots]
    hi64 = [row["hi_hex"] for row in roots]
    root64 = [
        (float.fromhex(row["lo_hex"]) +
         (float.fromhex(row["hi_hex"]) - float.fromhex(row["lo_hex"])) / 2.0).hex()
        for row in roots
    ]
    triples32 = [
        outward_f32(float.fromhex(row["lo_hex"]), float.fromhex(row["hi_hex"]))
        for row in roots
    ]
    lo32 = [value[0].hex() + "f32" for value in triples32]
    hi32 = [value[1].hex() + "f32" for value in triples32]
    root32 = [value[2].hex() + "f32" for value in triples32]

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
