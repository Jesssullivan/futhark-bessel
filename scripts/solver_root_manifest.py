#!/usr/bin/env python3
# SPDX-License-Identifier: ISC
"""Render the canonical source-graph solver-root output manifest.

The manifest is an ignored, reproducible bridge between the exact-rational
source interpreter and the independent FLINT/Arb residual oracle.  Every row
contains only one returned root bit pattern plus hashes that bind it to the
committed source-arithmetic theorem and that precision's complete transcript.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import root_solver_proof as source_proof

ROOT_SOLVER_EVIDENCE = Path("evidence/root-solver-arithmetic.json")
OUTPUT = Path("evidence/solver-root-outputs.jsonl")
ROOT_COUNT = 256


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_row(row: dict[str, Any]) -> bytes:
    return (
        json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()


def load_source_evidence() -> dict[str, Any]:
    try:
        evidence = json.loads(ROOT_SOLVER_EVIDENCE.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit("missing or malformed root-solver source evidence") from error
    if evidence.get("schema_version") != (
        "futhark-bessel.root-solver-arithmetic.v1"
    ) or evidence.get("status") != "SOURCE_GRAPH_ROOT_SOLVER_ARITHMETIC_PROVED":
        raise SystemExit("root-solver source evidence identity drifted")
    authority = evidence.get("authority", {})
    if (
        authority.get("implementation_source")
        != str(source_proof.IMPLEMENTATION)
        or authority.get("implementation_sha256")
        != source_proof.sha256(source_proof.IMPLEMENTATION)
        or authority.get("analyzer") != str(source_proof.ANALYZER)
        or authority.get("analyzer_sha256")
        != source_proof.sha256(source_proof.ANALYZER)
    ):
        raise SystemExit("root-solver source evidence authority drifted")
    return evidence


def generate_rows() -> list[dict[str, Any]]:
    source = source_proof.IMPLEMENTATION.read_text()
    implementation_sha, _, _ = source_proof.verify_source(source)
    evidence = load_source_evidence()
    evidence_sha = sha256(ROOT_SOLVER_EVIDENCE)

    results = {
        precision: [
            source_proof.solve(source_proof.FORMATS[precision], index)
            for index in range(1, ROOT_COUNT + 1)
        ]
        for precision in ("f32", "f64")
    }
    transcript_sha: dict[str, str] = {}
    for precision in ("f32", "f64"):
        transcript = hashlib.sha256()
        row_count = 0
        for index, result in enumerate(results[precision], start=1):
            for row in result.transcript_rows:
                transcript.update(
                    source_proof.canonical_row(
                        {"index": index, "precision": precision, **row}
                    )
                )
                row_count += 1
        committed = evidence.get("results", {}).get(precision, {}).get(
            "transcript", {}
        )
        if committed != {
            "canonicalization": "UTF-8 JSON Lines, sorted keys, compact separators",
            "events": "initial, every bisection iteration, final",
            "row_count": row_count,
            "sha256": transcript.hexdigest(),
        }:
            raise SystemExit(
                f"{precision} source transcript disagrees with committed evidence"
            )
        transcript_sha[precision] = transcript.hexdigest()

    return [
        {
            "implementation_sha256": implementation_sha,
            "index": index,
            "kind": f"{precision}_solver_j1_root_output",
            "root_bits": source_proof.FORMATS[precision].bits_hex(
                results[precision][index - 1].root
            ),
            "root_solver_evidence_sha256": evidence_sha,
            "source_transcript_sha256": transcript_sha[precision],
        }
        for index in range(1, ROOT_COUNT + 1)
        for precision in ("f32", "f64")
    ]


def generate_bytes() -> bytes:
    return b"".join(canonical_row(row) for row in generate_rows())


def main() -> None:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--write", action="store_true")
    action.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = generate_bytes()
    if args.write:
        OUTPUT.write_bytes(rendered)
        print(f"wrote {OUTPUT} ({len(rendered.splitlines())} rows)")
        return
    if not OUTPUT.exists() or OUTPUT.read_bytes() != rendered:
        raise SystemExit(
            "solver-root output manifest is stale; run "
            "scripts/solver_root_manifest.py --write"
        )
    print("OK canonical f32/f64 solver-root output manifest (512 rows)")


if __name__ == "__main__":
    main()
