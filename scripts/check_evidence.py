#!/usr/bin/env python3
"""Structural checks for independent interval evidence."""

import json
import sys
from pathlib import Path

rows = [json.loads(line) for line in Path(sys.argv[1]).read_text().splitlines()]
expected = {(kind, index) for kind in ("j0", "j1") for index in range(10)}
actual = {(row["kind"], row["index"]) for row in rows}
if actual != expected:
    raise SystemExit(f"evidence key mismatch: {actual ^ expected}")
for row in rows:
    if set(row) != {"kind", "index", "x", "value"}:
        raise SystemExit(f"unexpected evidence fields: {row}")
print(f"OK {len(rows)} structurally valid Arb certificates")
