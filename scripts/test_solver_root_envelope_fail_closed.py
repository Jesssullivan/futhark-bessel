#!/usr/bin/env python3
# SPDX-License-Identifier: ISC
"""Mutation tests for the source solver mathematical-root envelope boundary."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

import mpmath as mp

import solver_root_envelope_proof as proof
import solver_root_manifest as manifest_generator

ROOT = Path(__file__).resolve().parents[1]


def expect_blocked(function: Callable[[], Any], fragment: str) -> None:
    try:
        function()
    except SystemExit as error:
        if fragment not in str(error):
            raise SystemExit(
                f"wrong fail-closed reason: expected {fragment!r}, got {error!r}"
            ) from error
        return
    raise SystemExit(f"mutation did not fail closed: expected {fragment!r}")


def encoded(rows: list[dict[str, Any]]) -> bytes:
    return b"".join(manifest_generator.canonical_row(row) for row in rows)


def row_at(
    rows: list[dict[str, Any]], kind: str, index: int
) -> dict[str, Any]:
    matches = [
        row
        for row in rows
        if row.get("kind") == kind and row.get("index") == index
    ]
    if len(matches) != 1:
        raise SystemExit(f"fixture cannot locate {kind} row {index}")
    return matches[0]


def structural_mutations(
    rows: list[dict[str, Any]],
    loader: Callable[[bytes], Any],
    count_fragment: str,
    order_fragment: str,
) -> None:
    expect_blocked(lambda: loader(encoded(rows[:-1])), count_fragment)
    expect_blocked(lambda: loader(encoded(rows + [rows[-1]])), count_fragment)

    duplicated = json.loads(json.dumps(rows))
    duplicated[1] = json.loads(json.dumps(duplicated[0]))
    expect_blocked(lambda: loader(encoded(duplicated)), order_fragment)

    reordered = json.loads(json.dumps(rows))
    reordered[0], reordered[1] = reordered[1], reordered[0]
    expect_blocked(lambda: loader(encoded(reordered)), order_fragment)


def run_preflight(directory: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts/release_preflight.py")],
        cwd=directory,
        check=False,
        capture_output=True,
        text=True,
    )


def require_preflight_reason(directory: Path, fragment: str) -> None:
    completed = run_preflight(directory)
    output = completed.stdout + completed.stderr
    if completed.returncode != 1 or fragment not in output:
        raise SystemExit(
            f"wrong release-preflight result: expected {fragment!r}, got "
            f"exit {completed.returncode}: {output!r}"
        )


def test_release_preflight_root_boundaries() -> None:
    """Exercise the full boundary only after ignored ledgers are generated."""

    for required in (proof.MANIFEST, proof.CERTIFICATES):
        if not required.is_file():
            raise SystemExit(
                f"solver-root preflight test requires generated ledger {required}"
            )

    with tempfile.TemporaryDirectory() as directory:
        fixture = Path(directory)
        shutil.copy(ROOT / "RELEASE.md", fixture / "RELEASE.md")
        shutil.copytree(ROOT / "evidence", fixture / "evidence")
        implementation = fixture / "lib/github.com/Jesssullivan/futhark-bessel"
        implementation.mkdir(parents=True)
        shutil.copy(
            proof.IMPLEMENTATION,
            implementation / proof.IMPLEMENTATION.name,
        )
        scripts = fixture / "scripts"
        scripts.mkdir()
        for source in (
            "scripts/root_solver_proof.py",
            "scripts/solver_root_manifest.py",
            "scripts/solver_root_envelope_proof.py",
        ):
            shutil.copy(ROOT / source, scripts)
        oracle = fixture / "oracle"
        oracle.mkdir()
        for source in (
            "oracle/arb_oracle.c",
            "oracle/solver_root_envelopes.c",
        ):
            shutil.copy(ROOT / source, oracle)

        require_preflight_reason(fixture, "5 release gates remain unchecked")

        solver_path = fixture / "evidence/root-solver-arithmetic.json"
        solver = json.loads(solver_path.read_text())
        solver["release_implications"][
            "solver_mathematical_root_ulp_and_true_residual"
        ] = "PROVED"
        solver_path.write_text(json.dumps(solver))
        require_preflight_reason(fixture, "root-solver release boundary drifted")
        shutil.copy(ROOT / "evidence/root-solver-arithmetic.json", solver_path)

        budget_path = fixture / "evidence/error-budget.json"
        budget = json.loads(budget_path.read_text())
        budget["root_evidence"]["root_solver_source_graph"]["status"] = "OPEN"
        budget_path.write_text(json.dumps(budget))
        require_preflight_reason(fixture, "root-solver error-budget entry drifted")
        shutil.copy(ROOT / "evidence/error-budget.json", budget_path)

        floating_path = fixture / "evidence/floating-point-analysis.json"
        floating = json.loads(floating_path.read_text())
        floating["open_obligations"][0]["id"] = "FP-ROOT-SOLVER-ARITHMETIC"
        floating_path.write_text(json.dumps(floating))
        require_preflight_reason(fixture, "floating-point obligation set drifted")

        shutil.copy(ROOT / "evidence/floating-point-analysis.json", floating_path)
        envelope_path = fixture / "evidence/solver-root-envelopes.json"
        envelope = json.loads(envelope_path.read_text())
        envelope["envelopes"]["f64"]["root_ulp_error_upper"] = 21202
        envelope_path.write_text(json.dumps(envelope))
        floating = json.loads(floating_path.read_text())
        floating["authority"]["solver_root_envelopes_sha256"] = hashlib.sha256(
            envelope_path.read_bytes()
        ).hexdigest()
        floating_path.write_text(json.dumps(floating))
        require_preflight_reason(fixture, "f64 solver-root envelope drifted")


def main() -> None:
    mp.mp.dps = 160
    manifest_bytes = proof.MANIFEST.read_bytes()
    certificate_bytes = proof.CERTIFICATES.read_bytes()
    reference_bytes = proof.REFERENCE_CERTIFICATES.read_bytes()
    manifest_rows = [
        json.loads(line) for line in manifest_bytes.decode().splitlines()
    ]
    certificate_rows = [
        json.loads(line) for line in certificate_bytes.decode().splitlines()
    ]
    references = proof.load_reference_rows(reference_bytes)
    # The immediately preceding proof check regenerated this same canonical
    # manifest from the source interpreter; reuse its bytes so mutation testing
    # does not perform a redundant all-index solver replay.
    expected_manifest = manifest_bytes

    proof.verify_manifest(manifest_bytes, expected_manifest)
    grouped_manifest = proof.load_manifest(manifest_bytes)
    grouped_certificates = proof.load_certificates(certificate_bytes)
    proof.verify_certificate_manifest_bindings(
        grouped_manifest, grouped_certificates
    )

    structural_mutations(
        manifest_rows,
        proof.load_manifest,
        "expected exactly 512 solver-root manifest rows",
        "ordered f32/f64 pairs",
    )
    structural_mutations(
        certificate_rows,
        proof.load_certificates,
        "expected exactly 512 solver-root certificate rows",
        "ordered f32/f64 pairs",
    )

    for field, reason in (
        ("implementation_sha256", "implementation hash drifted"),
        ("root_solver_evidence_sha256", "evidence hash drifted"),
        ("source_transcript_sha256", "transcript hash drifted"),
    ):
        stale = json.loads(json.dumps(manifest_rows))
        stale[0][field] = "0" * 64
        expect_blocked(
            lambda changed=encoded(stale): proof.verify_manifest(
                changed, expected_manifest
            ),
            reason,
        )

    bit_substitution = json.loads(json.dumps(certificate_rows))
    bit_row = row_at(
        bit_substitution, "f64_solver_j1_root_envelope", 4
    )
    substituted_bits = int(bit_row["solver_root_f64_bits"], 16) + 1
    substituted_value = proof.value_from_bits("f64", substituted_bits)
    bit_row["solver_root_f64_bits"] = f"0x{substituted_bits:016x}"
    bit_row["solver_root_f64_hex"] = substituted_value.hex()
    substituted_certificates = proof.load_certificates(encoded(bit_substitution))
    expect_blocked(
        lambda: proof.verify_certificate_manifest_bindings(
            grouped_manifest, substituted_certificates
        ),
        "Arb certificate disagrees with source solver bits at index 4",
    )

    cached_root_substitution = json.loads(json.dumps(manifest_rows))
    cached_row = row_at(
        cached_root_substitution, "f64_solver_j1_root_output", 4
    )
    cached_row["root_bits"] = references[3]["root_f64_reference_bits"]
    expect_blocked(
        lambda: proof.verify_manifest(
            encoded(cached_root_substitution), expected_manifest
        ),
        "disagrees with the bound source interpreter",
    )

    residual_substitution = json.loads(json.dumps(certificate_rows))
    target = row_at(
        residual_substitution, "f64_solver_j1_root_envelope", 4
    )
    donor = row_at(
        certificate_rows, "f64_solver_j1_root_envelope", 5
    )
    target["true_residual_ball"] = donor["true_residual_ball"]
    target["true_residual_upper_hex"] = donor["true_residual_upper_hex"]
    parsed_substitution = proof.load_certificates(encoded(residual_substitution))
    expect_blocked(
        lambda: proof.verify_mpmath_row(
            "f64",
            4,
            int(grouped_manifest["f64"][3]["root_bits"], 16),
            parsed_substitution["f64"][3],
            int(references[3]["root_f64_reference_bits"], 16),
            mp.besseljzero(1, 4),
        ),
        "solver residual escaped Arb ball at index 4",
    )

    index4 = {
        "index": 4,
        "solver_root_bits": grouped_manifest["f64"][3]["root_bits"],
        "reference_root_bits": references[3]["root_f64_reference_bits"],
        "ulp_error": abs(
            int(grouped_manifest["f64"][3]["root_bits"], 16)
            - int(references[3]["root_f64_reference_bits"], 16)
        ),
    }
    if index4 != proof.F64_INDEX4_WITNESS:
        raise SystemExit("fixed f64 index-4 mutation witness drifted")

    original_oracle = proof.ORACLE
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "solver_root_envelopes.c"
        path.write_text(
            "/* root_cache.fut */\n"
            "arb_hypgeom_bessel_j(value, order, x, 512);\n"
            "/* solver-root-outputs.jsonl */\n"
        )
        try:
            proof.ORACLE = path
            expect_blocked(
                proof.verify_independent_oracle_source,
                "forbidden authority",
            )
        finally:
            proof.ORACLE = original_oracle

    test_release_preflight_root_boundaries()

    print(
        "OK solver-root manifest/certificate/hash/bit/residual/cache "
        "substitutions fail closed; f64 index-4 witness is fixed"
    )


if __name__ == "__main__":
    main()
