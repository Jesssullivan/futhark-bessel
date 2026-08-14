#!/usr/bin/env python3
# SPDX-License-Identifier: ISC
"""Mutation tests for the source solver mathematical-root envelope boundary."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Callable

import mpmath as mp

import solver_root_envelope_proof as proof
import solver_root_manifest as manifest_generator


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

    print(
        "OK solver-root manifest/certificate/hash/bit/residual/cache "
        "substitutions fail closed; f64 index-4 witness is fixed"
    )


if __name__ == "__main__":
    main()
