#!/usr/bin/env python3
"""Structural checks for independent interval evidence."""

import json
import struct
import sys
from pathlib import Path

rows = [json.loads(line) for line in Path(sys.argv[1]).read_text().splitlines()]
expected_values = {(kind, index) for kind in ("j0", "j1") for index in range(10)}
expected_roots = {("j1_root_bracket", index) for index in range(1, 257)}
expected = expected_values | expected_roots
actual = {(row["kind"], row["index"]) for row in rows}
if actual != expected:
    raise SystemExit(f"evidence key mismatch: {actual ^ expected}")
for row in rows:
    if row["kind"] == "j1_root_bracket":
        required = {
            "kind",
            "index",
            "lo_hex",
            "hi_hex",
            "j1_lo",
            "j1_hi",
            "bisections",
            "certified_sign_change",
        }
        if set(row) != required or not row["certified_sign_change"]:
            raise SystemExit(f"malformed root certificate: {row}")
        lo = float.fromhex(row["lo_hex"])
        hi = float.fromhex(row["hi_hex"])
        if not lo < hi:
            raise SystemExit(f"unordered root bracket: {row}")
        lo_bits = struct.unpack(">Q", struct.pack(">d", lo))[0]
        hi_bits = struct.unpack(">Q", struct.pack(">d", hi))[0]
        if hi_bits != lo_bits + 1:
            raise SystemExit(f"root bracket endpoints are not adjacent f64: {row}")
    elif set(row) != {"kind", "index", "x", "value"}:
        raise SystemExit(f"unexpected value evidence fields: {row}")
print(f"OK {len(rows)} structurally valid Arb certificates")
