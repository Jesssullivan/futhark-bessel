#!/usr/bin/env python3
"""Release remains deliberately fail-closed until certified gates exist."""

from pathlib import Path

unchecked = [line for line in Path("RELEASE.md").read_text().splitlines() if "- [ ]" in line]
if unchecked:
    raise SystemExit(f"BLOCKED: {len(unchecked)} release gates remain unchecked")
print("OK all release gates recorded")
