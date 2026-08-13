#!/usr/bin/env python3
"""Hash numerical source inputs for downstream receipts."""

import hashlib
from pathlib import Path

sources = [
    Path("lib/github.com/Jesssullivan/futhark-bessel/bessel.fut"),
    Path("lib/github.com/Jesssullivan/futhark-bessel/root_cache.fut"),
    Path("scripts/generate_constants.py"),
    Path("evidence/provenance.json"),
    Path("evidence/error-budget.json"),
]
digest = hashlib.sha256()
for source in sources:
    digest.update(source.as_posix().encode())
    digest.update(b"\0")
    digest.update(source.read_bytes())
    digest.update(b"\0")
print(f"sha256:{digest.hexdigest()}  numerical-source-bundle")
