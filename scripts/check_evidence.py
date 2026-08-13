#!/usr/bin/env python3
"""Structural checks for independent interval evidence."""

import json
import math
import re
import struct
import sys
from pathlib import Path

rows = [json.loads(line) for line in Path(sys.argv[1]).read_text().splitlines()]
if len(rows) != 342:
    raise SystemExit(f"expected exactly 342 evidence rows, got {len(rows)}")
expected_values = {(kind, index) for kind in ("j0", "j1") for index in range(10)}
expected_roots = {("j1_root_bracket", index) for index in range(1, 257)}
expected_conformance = {
    ("conformance_value", precision, index)
    for precision in ("f32", "f64")
    for index in range(33)
}
actual_values_and_roots = {
    (row["kind"], row["index"])
    for row in rows
    if row["kind"] != "conformance_value"
}
if actual_values_and_roots != expected_values | expected_roots:
    raise SystemExit(
        f"evidence key mismatch: "
        f"{actual_values_and_roots ^ (expected_values | expected_roots)}"
    )
actual_conformance = {
    (row["kind"], row["precision"], row["index"])
    for row in rows
    if row["kind"] == "conformance_value"
}
if actual_conformance != expected_conformance:
    raise SystemExit(
        f"conformance evidence key mismatch: "
        f"{actual_conformance ^ expected_conformance}"
    )


def parse_bits(text: str, width: int) -> int:
    if not re.fullmatch(rf"0x[0-9a-f]{{{width // 4}}}", text):
        raise SystemExit(f"malformed {width}-bit hexadecimal value: {text}")
    return int(text, 16)


seen_x: dict[str, set[int]] = {"f32": set(), "f64": set()}
for row in rows:
    if row["kind"] == "j1_root_bracket":
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
        if (
            set(row) != required
            or not row["certified_sign_change"]
            or not row["certified_unique_rounding"]
        ):
            raise SystemExit(f"malformed root certificate: {row}")
        root64_bits = parse_bits(row["root_f64_reference_bits"], 64)
        root32_bits = parse_bits(row["root_f32_reference_bits"], 32)
        lo = float.fromhex(row["lo_hex"])
        hi = float.fromhex(row["hi_hex"])
        if not lo < hi:
            raise SystemExit(f"unordered root bracket: {row}")
        lo_bits = struct.unpack(">Q", struct.pack(">d", lo))[0]
        hi_bits = struct.unpack(">Q", struct.pack(">d", hi))[0]
        if hi_bits != lo_bits + 1:
            raise SystemExit(f"root bracket endpoints are not adjacent f64: {row}")
        if root64_bits not in {lo_bits, hi_bits}:
            raise SystemExit(f"rounded f64 root escaped its certified bracket: {row}")
        lo32_bits = struct.unpack(">I", struct.pack(">f", lo))[0]
        hi32_bits = struct.unpack(">I", struct.pack(">f", hi))[0]
        if root32_bits != lo32_bits or root32_bits != hi32_bits:
            raise SystemExit(f"rounded f32 root is not certified by its bracket: {row}")
    elif row["kind"] == "conformance_value":
        required = {
            "kind",
            "precision",
            "index",
            "domain",
            "x_bits",
            "j0_reference_bits",
            "j1_reference_bits",
            "j0_ball",
            "j1_ball",
            "certified_unique_rounding",
        }
        if set(row) != required or not row["certified_unique_rounding"]:
            raise SystemExit(f"malformed conformance certificate: {row}")
        precision = row["precision"]
        width = 32 if precision == "f32" else 64
        x_bits = parse_bits(row["x_bits"], width)
        parse_bits(row["j0_reference_bits"], width)
        parse_bits(row["j1_reference_bits"], width)
        if x_bits in seen_x[precision]:
            raise SystemExit(f"duplicate {precision} conformance input: {row}")
        seen_x[precision].add(x_bits)
        if precision == "f32":
            x = struct.unpack(">f", struct.pack(">I", x_bits))[0]
            switch = 6.0
        else:
            x = struct.unpack(">d", struct.pack(">Q", x_bits))[0]
            switch = 12.0
        if not math.isfinite(x) or abs(x) > 1024.0:
            raise SystemExit(f"conformance input outside finite domain: {row}")
        expected_domain = "series" if abs(x) <= switch else "asymptotic"
        if row["domain"] != expected_domain:
            raise SystemExit(f"incorrect conformance domain: {row}")
    elif set(row) != {"kind", "index", "x", "value"}:
        raise SystemExit(f"unexpected value evidence fields: {row}")
print(f"OK {len(rows)} structurally valid Arb certificates")
