#!/usr/bin/env python3
"""Fail closed on disallowed approximation-table provenance."""

from pathlib import Path

DISALLOWED = ("numerical recipes", "cephes", "hart")
ALLOWED_CONTRACT_FILES = {"AGENTS.md", "RELEASE.md"}
ALLOWED_CONTRACT_FILES.add(Path(__file__).name)

for path in Path(".").rglob("*"):
    if not path.is_file() or ".git" in path.parts:
        continue
    if path.name in ALLOWED_CONTRACT_FILES:
        continue
    try:
        text = path.read_text().lower()
    except UnicodeDecodeError:
        continue
    for phrase in DISALLOWED:
        if phrase in text:
            raise SystemExit(f"disallowed approximation provenance in {path}: {phrase}")

print("OK no disallowed approximation provenance in source or evidence")
