#!/usr/bin/env python3
"""Hash numerical source inputs for downstream receipts."""

import hashlib
from pathlib import Path

source = Path("lib/github.com/Jesssullivan/futhark-bessel/bessel.fut")
digest = hashlib.sha256(source.read_bytes()).hexdigest()
print(f"sha256:{digest}  {source}")
