#!/usr/bin/env python3
"""Hash numerical source inputs for downstream receipts."""

import hashlib
from pathlib import Path

sources = [
    Path("lib/github.com/Jesssullivan/futhark-bessel/bessel.fut"),
    Path("lib/github.com/Jesssullivan/futhark-bessel/bessel_internal.fut"),
    Path("lib/github.com/Jesssullivan/futhark-bessel/root_cache.fut"),
    Path("scripts/generate_constants.py"),
    Path("oracle/approximation_bounds.c"),
    Path("oracle/adjacent_composition.c"),
    Path("scripts/approximation_proof.py"),
    Path("scripts/adjacent_reduction_bands.py"),
    Path("scripts/adjacent_composition_proof.py"),
    Path("scripts/floating_point_analysis.py"),
    Path("scripts/check_observed_envelopes.py"),
    Path("scripts/test_evidence_fail_closed.py"),
    Path("evidence/real-approximation-bounds.json"),
    Path("evidence/adjacent-reduction-bands.json"),
    Path("evidence/adjacent-composition-proof.json"),
    Path("evidence/floating-point-analysis.json"),
    Path("evidence/observed-regression-envelopes.json"),
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
