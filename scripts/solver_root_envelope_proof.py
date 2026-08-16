#!/usr/bin/env python3
# SPDX-License-Identifier: ISC
"""Certify mathematical-root accuracy at source-interpreted solver outputs.

This theorem joins three deliberately separate authorities for indices 1..256:
the bit-exact source-solver output manifest, the existing independently rounded
mathematical-root reference bits, and a new FLINT/Arb evaluation of ``J1`` at
each exact solver output.  mpmath independently replays both root rounding and
the residual balls.  No backend execution or bracket-containment claim is made.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import struct
from pathlib import Path
from typing import Any

import mpmath as mp

import solver_root_manifest as manifest_generator

IMPLEMENTATION = Path(
    "lib/github.com/Jesssullivan/futhark-bessel/bessel_internal.fut"
)
ROOT_SOLVER_EVIDENCE = Path("evidence/root-solver-arithmetic.json")
MANIFEST = Path("evidence/solver-root-outputs.jsonl")
CERTIFICATES = Path("evidence/solver-root-envelope-certificates.jsonl")
REFERENCE_CERTIFICATES = Path("evidence/arb-certificates.jsonl")
ORACLE = Path("oracle/solver_root_envelopes.c")
REFERENCE_ORACLE = Path("oracle/arb_oracle.c")
MANIFEST_GENERATOR = Path("scripts/solver_root_manifest.py")
VERIFIER = Path("scripts/solver_root_envelope_proof.py")
OUTPUT = Path("evidence/solver-root-envelopes.json")

ROOT_COUNT = 256
EXPECTED_IMPLEMENTATION_SHA256 = (
    "2b459fb3e24e82a825db5f44cc8b3ebe9c8387d598235f84c4e80996b4e7d9d1"
)
EXPECTED_MAXIMUM_ULP_ERROR = {"f32": 3, "f64": 21203}
F64_INDEX4_WITNESS = {
    "index": 4,
    "solver_root_bits": "0x402aa5baf3113875",
    "reference_root_bits": "0x402aa5baf310e5a2",
    "ulp_error": 21203,
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bit_width(precision: str) -> int:
    return 32 if precision == "f32" else 64


def parse_bits(text: Any, precision: str, label: str = "root") -> int:
    width = bit_width(precision)
    if not isinstance(text, str) or not re.fullmatch(
        rf"0x[0-9a-f]{{{width // 4}}}", text
    ):
        raise SystemExit(f"malformed {precision} {label} bits: {text!r}")
    return int(text, 16)


def bits_of(precision: str, value: float) -> int:
    if precision == "f32":
        return struct.unpack(">I", struct.pack(">f", value))[0]
    return struct.unpack(">Q", struct.pack(">d", value))[0]


def value_from_bits(precision: str, bits: int) -> float:
    if precision == "f32":
        return struct.unpack(">f", struct.pack(">I", bits))[0]
    return struct.unpack(">d", struct.pack(">Q", bits))[0]


def mp_exact_float(value: float) -> mp.mpf:
    numerator, denominator = value.as_integer_ratio()
    return mp.mpf(numerator) / denominator


def nonnegative_hex(text: Any, label: str) -> float:
    if not isinstance(text, str) or not re.fullmatch(
        r"0x(?:0|1)(?:\.[0-9a-f]+)?p[+-][0-9]+", text
    ):
        raise SystemExit(f"malformed hexadecimal {label}: {text!r}")
    try:
        value = float.fromhex(text)
    except ValueError as error:
        raise SystemExit(f"malformed hexadecimal {label}: {text!r}") from error
    if not math.isfinite(value) or value < 0.0:
        raise SystemExit(f"nonfinite or negative {label}: {text!r}")
    return value


def parse_ball(text: Any) -> tuple[mp.mpf, mp.mpf]:
    if not isinstance(text, str):
        raise SystemExit("malformed Arb solver residual ball")
    stripped = text.removeprefix("[").removesuffix("]")
    exact = re.fullmatch(r"([+-]?[0-9.]+(?:e[+-]?[0-9]+)?)", stripped)
    if exact:
        value = mp.mpf(exact.group(1))
        return value, value
    ball = re.fullmatch(
        r"([+-]?[0-9.]+(?:e[+-]?[0-9]+)?) \+/- "
        r"([0-9.]+(?:e[+-]?[0-9]+)?)",
        stripped,
    )
    if not ball:
        raise SystemExit(f"malformed Arb solver residual ball: {text!r}")
    midpoint = mp.mpf(ball.group(1))
    radius = mp.mpf(ball.group(2))
    if radius < 0:
        raise SystemExit(f"negative Arb solver residual radius: {text!r}")
    return midpoint - radius, midpoint + radius


def independently_rounds_to(
    precision: str, reference: mp.mpf, candidate_bits: int
) -> bool:
    normal_min = 0x00800000 if precision == "f32" else 0x0010000000000000
    infinity = 0x7F800000 if precision == "f32" else 0x7FF0000000000000
    if candidate_bits < normal_min or candidate_bits >= infinity:
        raise SystemExit(f"non-positive-normal {precision} reference root bits")
    candidate = mp_exact_float(value_from_bits(precision, candidate_bits))
    predecessor = mp_exact_float(value_from_bits(precision, candidate_bits - 1))
    successor = mp_exact_float(value_from_bits(precision, candidate_bits + 1))
    lower_midpoint = (predecessor + candidate) / 2
    upper_midpoint = (candidate + successor) / 2
    if candidate_bits % 2 == 0:
        return lower_midpoint <= reference <= upper_midpoint
    return lower_midpoint < reference < upper_midpoint


def decode_rows(data: bytes, label: str) -> list[dict[str, Any]]:
    try:
        text = data.decode()
        rows = [json.loads(line) for line in text.splitlines()]
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SystemExit(f"malformed {label} ledger") from error
    return rows


def load_manifest(data: bytes) -> dict[str, list[dict[str, Any]]]:
    rows = decode_rows(data, "solver-root output manifest")
    if len(rows) != 2 * ROOT_COUNT:
        raise SystemExit(
            f"expected exactly {2 * ROOT_COUNT} solver-root manifest rows, "
            f"got {len(rows)}"
        )
    expected = [
        (f"{precision}_solver_j1_root_output", index)
        for index in range(1, ROOT_COUNT + 1)
        for precision in ("f32", "f64")
    ]
    actual = [(row.get("kind"), row.get("index")) for row in rows]
    if actual != expected:
        raise SystemExit(
            "solver-root manifest rows must cover ordered f32/f64 pairs for "
            "indices 1..256"
        )
    required = {
        "implementation_sha256",
        "index",
        "kind",
        "root_bits",
        "root_solver_evidence_sha256",
        "source_transcript_sha256",
    }
    for row in rows:
        precision = row["kind"].split("_", 1)[0]
        if set(row) != required:
            raise SystemExit(
                f"solver-root manifest fields drifted at {precision} index "
                f"{row['index']}"
            )
        parse_bits(row["root_bits"], precision, "solver-root")
        for field in (
            "implementation_sha256",
            "root_solver_evidence_sha256",
            "source_transcript_sha256",
        ):
            if not isinstance(row[field], str) or not re.fullmatch(
                r"[0-9a-f]{64}", row[field]
            ):
                raise SystemExit(
                    f"malformed {field} at {precision} index {row['index']}"
                )
    return {
        precision: [
            row
            for row in rows
            if row["kind"] == f"{precision}_solver_j1_root_output"
        ]
        for precision in ("f32", "f64")
    }


def verify_manifest(
    data: bytes, expected_bytes: bytes | None = None
) -> dict[str, list[dict[str, Any]]]:
    grouped = load_manifest(data)
    implementation_sha = sha256(IMPLEMENTATION)
    evidence_sha = sha256(ROOT_SOLVER_EVIDENCE)
    root_solver = json.loads(ROOT_SOLVER_EVIDENCE.read_text())
    for precision in ("f32", "f64"):
        transcript_sha = root_solver.get("results", {}).get(precision, {}).get(
            "transcript", {}
        ).get("sha256")
        for row in grouped[precision]:
            if row["implementation_sha256"] != implementation_sha:
                raise SystemExit("solver-root manifest implementation hash drifted")
            if row["root_solver_evidence_sha256"] != evidence_sha:
                raise SystemExit("solver-root manifest evidence hash drifted")
            if row["source_transcript_sha256"] != transcript_sha:
                raise SystemExit(
                    f"{precision} solver-root manifest transcript hash drifted"
                )
    canonical = (
        manifest_generator.generate_bytes()
        if expected_bytes is None
        else expected_bytes
    )
    if data != canonical:
        raise SystemExit(
            "solver-root manifest disagrees with the bound source interpreter"
        )
    return grouped


def load_certificates(data: bytes) -> dict[str, list[dict[str, Any]]]:
    rows = decode_rows(data, "solver-root envelope certificate")
    if len(rows) != 2 * ROOT_COUNT:
        raise SystemExit(
            f"expected exactly {2 * ROOT_COUNT} solver-root certificate rows, "
            f"got {len(rows)}"
        )
    expected = [
        (f"{precision}_solver_j1_root_envelope", index)
        for index in range(1, ROOT_COUNT + 1)
        for precision in ("f32", "f64")
    ]
    actual = [(row.get("kind"), row.get("index")) for row in rows]
    if actual != expected:
        raise SystemExit(
            "solver-root certificate rows must cover ordered f32/f64 pairs for "
            "indices 1..256"
        )
    for row in rows:
        precision = row["kind"].split("_", 1)[0]
        required = {
            "kind",
            "index",
            f"solver_root_{precision}_bits",
            f"solver_root_{precision}_hex",
            "true_residual_ball",
            "true_residual_upper_hex",
            "certified_true_residual",
        }
        if set(row) != required:
            raise SystemExit(
                f"solver-root certificate fields drifted at {precision} index "
                f"{row['index']}"
            )
        bits = parse_bits(
            row[f"solver_root_{precision}_bits"], precision, "solver-root"
        )
        value = nonnegative_hex(
            row[f"solver_root_{precision}_hex"],
            f"{precision} solver-root value",
        )
        if bits_of(precision, value) != bits:
            raise SystemExit(
                f"{precision} solver-root hexadecimal/bits mismatch at index "
                f"{row['index']}"
            )
        lo, hi = parse_ball(row["true_residual_ball"])
        upper = nonnegative_hex(
            row["true_residual_upper_hex"],
            f"{precision} solver true residual upper bound",
        )
        if (
            row["certified_true_residual"] is not True
            or lo < 0
            or hi < lo
            or mp_exact_float(upper) < hi
        ):
            raise SystemExit(
                f"invalid {precision} solver true-residual certificate at index "
                f"{row['index']}"
            )
    return {
        precision: [
            row
            for row in rows
            if row["kind"] == f"{precision}_solver_j1_root_envelope"
        ]
        for precision in ("f32", "f64")
    }


def load_reference_rows(data: bytes) -> list[dict[str, Any]]:
    rows = decode_rows(data, "Arb reference certificate")
    roots = [row for row in rows if row.get("kind") == "j1_root_bracket"]
    roots.sort(key=lambda row: row.get("index", -1))
    if [row.get("index") for row in roots] != list(range(1, ROOT_COUNT + 1)):
        raise SystemExit("Arb reference ledger must cover root indices 1..256")
    required = {
        "kind",
        "index",
        "lo_hex",
        "hi_hex",
        "j1_lo",
        "j1_hi",
        "root_f64_reference_bits",
        "root_f32_reference_bits",
        "bisections",
        "certified_sign_change",
        "certified_unique_rounding",
    }
    for row in roots:
        if set(row) != required:
            raise SystemExit(f"Arb reference fields drifted at index {row['index']}")
        if (
            row["bisections"] != 160
            or row["certified_sign_change"] is not True
            or row["certified_unique_rounding"] is not True
        ):
            raise SystemExit(f"Arb reference certificate drifted at index {row['index']}")
        parse_bits(row["root_f32_reference_bits"], "f32", "reference-root")
        parse_bits(row["root_f64_reference_bits"], "f64", "reference-root")
    return roots


def verify_independent_oracle_source() -> None:
    source = ORACLE.read_text()
    forbidden_inputs = (
        "root_cache.fut",
        "bessel_internal.fut",
        "arb-certificates.jsonl",
        "root-envelope-certificates.jsonl",
        "arb_oracle.c",
        "root_envelopes.c",
        "root_solver_proof.py",
    )
    if any(item in source for item in forbidden_inputs):
        raise SystemExit("solver-root residual oracle acquired a forbidden authority")
    if source.count("arb_hypgeom_bessel_j") != 1:
        raise SystemExit("solver-root residual oracle Bessel authority drifted")
    if "solver-root-outputs.jsonl" not in source:
        raise SystemExit("solver-root residual oracle manifest input drifted")


def joined_witness(
    precision: str,
    manifest_row: dict[str, Any],
    certificate_row: dict[str, Any],
    reference_row: dict[str, Any],
    ulp_error: int,
) -> dict[str, Any]:
    return {
        "index": manifest_row["index"],
        "solver_root_bits": manifest_row["root_bits"],
        "reference_root_bits": reference_row[f"root_{precision}_reference_bits"],
        "ulp_error": ulp_error,
        "true_residual_ball": certificate_row["true_residual_ball"],
        "true_residual_upper_hex": certificate_row["true_residual_upper_hex"],
    }


def verify_certificate_manifest_bindings(
    manifest_rows: dict[str, list[dict[str, Any]]],
    certificate_rows: dict[str, list[dict[str, Any]]],
) -> None:
    for precision in ("f32", "f64"):
        for index, (manifest_row, certificate_row) in enumerate(
            zip(
                manifest_rows[precision],
                certificate_rows[precision],
                strict=True,
            ),
            start=1,
        ):
            solver_bits = parse_bits(
                manifest_row["root_bits"], precision, "solver-root"
            )
            certificate_bits = parse_bits(
                certificate_row[f"solver_root_{precision}_bits"],
                precision,
                "solver-root",
            )
            if certificate_bits != solver_bits:
                raise SystemExit(
                    f"{precision} Arb certificate disagrees with source solver "
                    f"bits at index {index}"
                )


def verify_mpmath_row(
    precision: str,
    index: int,
    solver_bits: int,
    certificate_row: dict[str, Any],
    reference_bits: int,
    reference: mp.mpf,
) -> tuple[int, mp.mpf, mp.mpf]:
    if not independently_rounds_to(precision, reference, reference_bits):
        raise SystemExit(
            f"mpmath disagrees with Arb reference rounding at {precision} "
            f"index {index}"
        )
    ulp_error = abs(solver_bits - reference_bits)
    solver_root = mp_exact_float(value_from_bits(precision, solver_bits))
    residual = abs(mp.besselj(1, solver_root))
    ball_lo, ball_hi = parse_ball(certificate_row["true_residual_ball"])
    if ball_lo < 0 or not ball_lo <= residual <= ball_hi:
        raise SystemExit(
            f"mpmath {precision} solver residual escaped Arb ball at index "
            f"{index}"
        )
    upper_value = nonnegative_hex(
        certificate_row["true_residual_upper_hex"],
        f"{precision} solver true residual upper bound",
    )
    upper = mp_exact_float(upper_value)
    if upper < ball_hi or upper < residual:
        raise SystemExit(
            f"{precision} solver residual escaped hexadecimal upper bound "
            f"at index {index}"
        )
    return ulp_error, residual, upper


def verify_precision(
    precision: str,
    manifest_rows: list[dict[str, Any]],
    certificate_rows: list[dict[str, Any]],
    reference_rows: list[dict[str, Any]],
    mathematical_roots: list[mp.mpf],
) -> dict[str, Any]:
    maximum_ulp_error = -1
    maximum_ulp_witness: dict[str, Any] | None = None
    maximum_upper = mp.mpf(-1)
    maximum_upper_witness: dict[str, Any] | None = None
    maximum_replay = mp.mpf(-1)
    maximum_replay_index = 0
    mismatched_roots = 0

    for index, (manifest_row, certificate_row, reference_row, reference) in enumerate(
        zip(
            manifest_rows,
            certificate_rows,
            reference_rows,
            mathematical_roots,
            strict=True,
        ),
        start=1,
    ):
        solver_bits = parse_bits(
            manifest_row["root_bits"], precision, "solver-root"
        )
        reference_bits = parse_bits(
            reference_row[f"root_{precision}_reference_bits"],
            precision,
            "reference-root",
        )
        ulp_error, residual, upper = verify_mpmath_row(
            precision,
            index,
            solver_bits,
            certificate_row,
            reference_bits,
            reference,
        )
        if ulp_error != 0:
            mismatched_roots += 1

        witness = joined_witness(
            precision,
            manifest_row,
            certificate_row,
            reference_row,
            ulp_error,
        )
        if ulp_error > maximum_ulp_error:
            maximum_ulp_error = ulp_error
            maximum_ulp_witness = witness
        if upper > maximum_upper:
            maximum_upper = upper
            maximum_upper_witness = witness
        if residual > maximum_replay:
            maximum_replay = residual
            maximum_replay_index = index

    if maximum_ulp_error != EXPECTED_MAXIMUM_ULP_ERROR[precision]:
        raise SystemExit(
            f"{precision} solver maximum ULP error drifted: "
            f"expected {EXPECTED_MAXIMUM_ULP_ERROR[precision]}, got "
            f"{maximum_ulp_error}"
        )
    if precision == "f64":
        index4 = joined_witness(
            precision,
            manifest_rows[3],
            certificate_rows[3],
            reference_rows[3],
            abs(
                parse_bits(manifest_rows[3]["root_bits"], precision)
                - parse_bits(reference_rows[3]["root_f64_reference_bits"], precision)
            ),
        )
        if {
            key: index4[key] for key in F64_INDEX4_WITNESS
        } != F64_INDEX4_WITNESS:
            raise SystemExit("fixed f64 solver-root index-4 witness drifted")
        if maximum_ulp_witness is None or {
            key: maximum_ulp_witness[key] for key in F64_INDEX4_WITNESS
        } != F64_INDEX4_WITNESS:
            raise SystemExit("f64 index 4 is no longer the maximum ULP witness")

    if maximum_ulp_witness is None or maximum_upper_witness is None:
        raise SystemExit(f"missing {precision} solver envelope extrema")
    return {
        "root_count": len(manifest_rows),
        "solver_outputs_differing_from_correctly_rounded_root_count": (
            mismatched_roots
        ),
        "root_ulp_error_upper": maximum_ulp_error,
        "maximum_ulp_witness": maximum_ulp_witness,
        "true_residual_abs_upper_hex": maximum_upper_witness[
            "true_residual_upper_hex"
        ],
        "maximum_true_residual_witness": maximum_upper_witness,
        "independent_maximum_true_residual_decimal": mp.nstr(
            maximum_replay, 50, min_fixed=0, max_fixed=0
        ),
        "independent_maximum_true_residual_index": maximum_replay_index,
    }


def verify_all(
    manifest_bytes: bytes,
    certificate_bytes: bytes,
    reference_bytes: bytes,
    expected_manifest_bytes: bytes | None = None,
) -> dict[str, dict[str, Any]]:
    mp.mp.dps = 160
    manifest_rows = verify_manifest(manifest_bytes, expected_manifest_bytes)
    certificate_rows = load_certificates(certificate_bytes)
    verify_certificate_manifest_bindings(manifest_rows, certificate_rows)
    reference_rows = load_reference_rows(reference_bytes)
    mathematical_roots = [
        mp.besseljzero(1, index) for index in range(1, ROOT_COUNT + 1)
    ]
    return {
        precision: verify_precision(
            precision,
            manifest_rows[precision],
            certificate_rows[precision],
            reference_rows,
            mathematical_roots,
        )
        for precision in ("f32", "f64")
    }


def generate() -> dict[str, Any]:
    implementation_sha = sha256(IMPLEMENTATION)
    if implementation_sha != EXPECTED_IMPLEMENTATION_SHA256:
        raise SystemExit("implementation SHA drifted; re-audit solver-root envelope")
    verify_independent_oracle_source()
    manifest_bytes = MANIFEST.read_bytes()
    certificate_bytes = CERTIFICATES.read_bytes()
    reference_bytes = REFERENCE_CERTIFICATES.read_bytes()
    results = verify_all(manifest_bytes, certificate_bytes, reference_bytes)
    root_solver = json.loads(ROOT_SOLVER_EVIDENCE.read_text())
    transcript_hashes = {
        precision: root_solver["results"][precision]["transcript"]["sha256"]
        for precision in ("f32", "f64")
    }
    return {
        "schema_version": "futhark-bessel.solver-root-envelopes.v1",
        "status": "SOURCE_GRAPH_SOLVER_MATHEMATICAL_ROOT_ENVELOPES_CERTIFIED",
        "release_conformance": False,
        "scope": {
            "covered": (
                "positive_j1_root_solved returned-root bit patterns for every "
                "index 1..256, separately in f32 and f64; ULP distance against "
                "the existing Arb-certified correctly rounded mathematical J1 "
                "root and independent Arb/mpmath bounds on |J1(root)|"
            ),
            "excluded": [
                "containment of a solver output in an Arb mathematical-root isolating bracket",
                "the implementation-reported approximate residual value",
                "C/WASM/WebGPU lowering, contraction, reassociation, and runtime behavior",
                "release conformance and behavior outside root indices 1..256",
            ],
        },
        "authority": {
            "implementation": str(IMPLEMENTATION),
            "implementation_sha256": implementation_sha,
            "root_solver_source_evidence": str(ROOT_SOLVER_EVIDENCE),
            "root_solver_source_evidence_sha256": sha256(ROOT_SOLVER_EVIDENCE),
            "source_transcript_sha256": transcript_hashes,
            "solver_output_manifest": str(MANIFEST),
            "solver_output_manifest_rows": len(manifest_bytes.splitlines()),
            "solver_output_manifest_sha256": hashlib.sha256(
                manifest_bytes
            ).hexdigest(),
            "solver_output_manifest_generator": str(MANIFEST_GENERATOR),
            "solver_output_manifest_generator_sha256": sha256(MANIFEST_GENERATOR),
            "oracle": str(ORACLE),
            "oracle_sha256": sha256(ORACLE),
            "certificate_ledger": str(CERTIFICATES),
            "certificate_rows": len(certificate_bytes.splitlines()),
            "certificate_ledger_sha256": hashlib.sha256(
                certificate_bytes
            ).hexdigest(),
            "certificate_library": "FLINT/Arb 3.6.0 arb_hypgeom_bessel_j at 512-bit precision",
            "reference_oracle": str(REFERENCE_ORACLE),
            "reference_oracle_sha256": sha256(REFERENCE_ORACLE),
            "reference_certificates": str(REFERENCE_CERTIFICATES),
            "reference_certificates_sha256": hashlib.sha256(
                reference_bytes
            ).hexdigest(),
            "independent_verifier": str(VERIFIER),
            "independent_verifier_sha256": sha256(VERIFIER),
            "independent_library": "mpmath 1.4.1 besselj/besseljzero at 160 decimal digits",
        },
        "proof_obligation": {
            "id": "FP-ROOT-SOLVER-MATHEMATICAL-ROOT-ENVELOPES",
            "status": "PROVED",
            "statement": (
                "The bit-exact source-graph solver outputs have all-index "
                "mathematical-root ULP and independent true-residual envelopes."
            ),
        },
        "envelopes": {
            precision: {
                "precision": precision,
                "index_domain": {"minimum": 1, "maximum": ROOT_COUNT},
                **results[precision],
            }
            for precision in ("f32", "f64")
        },
        "join": {
            "all_source_outputs_joined_to_reference_bits_and_residual_balls": True,
            "joined_rows": 2 * ROOT_COUNT,
            "fixed_f64_index4_witness": {
                **F64_INDEX4_WITNESS,
                "true_residual_ball": results["f64"]["maximum_ulp_witness"][
                    "true_residual_ball"
                ],
                "true_residual_upper_hex": results["f64"][
                    "maximum_ulp_witness"
                ]["true_residual_upper_hex"],
            },
        },
        "independent_replay": {
            "reference_root_rounding_validated_for_all_rows": True,
            "solver_true_residual_enclosed_for_all_rows": True,
            "precision_results": {
                precision: {
                    "root_count": results[precision]["root_count"],
                    "maximum_true_residual_decimal": results[precision][
                        "independent_maximum_true_residual_decimal"
                    ],
                    "maximum_true_residual_index": results[precision][
                        "independent_maximum_true_residual_index"
                    ],
                }
                for precision in ("f32", "f64")
            },
        },
        "release_implications": {
            "solver_mathematical_root_ulp_and_true_residual": "CERTIFIED_SOURCE_GRAPH",
            "solver_bracket_containment": "NOT_CLAIMED",
            "backend_lowering_equivalence": "OPEN",
            "backend_runtime_conformance": "OPEN",
            "overall_release_status": "INCOMPLETE",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--write", action="store_true")
    action.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = json.dumps(generate(), indent=2, sort_keys=True) + "\n"
    if args.write:
        OUTPUT.write_text(rendered)
        print(f"wrote {OUTPUT}")
        return
    if not OUTPUT.exists() or OUTPUT.read_text() != rendered:
        raise SystemExit(
            "solver-root envelope evidence is stale; run "
            "scripts/solver_root_envelope_proof.py --write"
        )
    print(
        "OK f32/f64 source solver mathematical-root ULP and true-residual "
        "envelopes for indices 1..256; backend and release conformance remain OPEN"
    )


if __name__ == "__main__":
    main()
