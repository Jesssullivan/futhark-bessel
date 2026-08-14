#!/usr/bin/env python3
# SPDX-License-Identifier: ISC
"""Mutation tests for the compact floating-point evidence gates."""

from __future__ import annotations

import json
import hashlib
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import adjacent_composition_proof as adjacent
import check_observed_envelopes as envelopes
import floating_point_analysis as floating


def expect_blocked(function: Any, fragment: str) -> None:
    try:
        function()
    except SystemExit as error:
        if fragment not in str(error):
            raise SystemExit(
                f"wrong fail-closed reason: expected {fragment!r}, got {error!r}"
            ) from error
        return
    raise SystemExit(f"mutation did not fail closed: expected {fragment!r}")


@contextmanager
def patched_json(path: Path, document: dict[str, Any]) -> Iterator[Path]:
    with tempfile.TemporaryDirectory() as directory:
        mutated = Path(directory) / path.name
        mutated.write_text(json.dumps(document))
        yield mutated


def test_envelope_limits() -> None:
    for invalid in (
        "nan",
        "inf",
        "-inf",
        "-0x0p+0",
        "0X1P+0",
        "0x1.0p+0",
        "0x01p+0",
        "0x0p-1",
        "0x1p-0",
        "0x2p+0",
        "0x1p+999999",
        "0x1p-999999",
        "0x1.00000000000000001p+0",
        -1,
        None,
    ):
        expect_blocked(
            lambda value=invalid: envelopes.hexadecimal(value),
            "hexadecimal envelope",
        )
    for invalid in (-1, True, False, 1.0, "1", None):
        expect_blocked(
            lambda value=invalid: envelopes.ulp_ceiling(value, "fixture"),
            "invalid ULP envelope",
        )
    for invalid in ("nan", "inf", "-inf", "-0x0.0p+0", "0X1.0P+0", None):
        expect_blocked(
            lambda value=invalid: envelopes.observed_hexadecimal(value, "fixture"),
            "invalid observed hexadecimal value",
        )
    for invalid in ("NaN", "Infinity", "-1e-9", "-0", None):
        expect_blocked(
            lambda value=invalid: envelopes.observed_decimal(value, "fixture"),
            "invalid observed decimal value",
        )


def test_exact_real_binding() -> None:
    original_path = floating.EXACT_REAL
    original = json.loads(original_path.read_text())
    implementation_sha = hashlib.sha256(floating.IMPLEMENTATION.read_bytes()).hexdigest()
    mutations = (
        ({"status": "CERTIFIED_EXACT_REAL_WHOLE_DOMAIN"}, "schema"),
        (
            {
                **original,
                "authority": {
                    **original["authority"],
                    "implementation_sha256": "0" * 64,
                },
            },
            "implementation SHA",
        ),
        (
            {
                **original,
                "authority": {
                    **original["authority"],
                    "implementation_source": "different/source.fut",
                },
            },
            "implementation source",
        ),
        (
            {
                **original,
                "scope": {
                    **original["scope"],
                    "semantic_model": "ordinary binary floating point",
                },
            },
            "scope drifted",
        ),
        (
            {
                **original,
                "range_reduction_partitions": {
                    **original["range_reduction_partitions"],
                    "f32": {
                        **original["range_reduction_partitions"]["f32"],
                        "j0": {
                            **original["range_reduction_partitions"]["f32"]["j0"],
                            "reduced_argument_absolute_upper_hex": "0x1p+99",
                        },
                    },
                },
            },
            "reduced-argument authority",
        ),
        (
            {
                **original,
                "range_reduction_partitions": {
                    **original["range_reduction_partitions"],
                    "f64": {
                        **original["range_reduction_partitions"]["f64"],
                        "j1": {
                            **original["range_reduction_partitions"]["f64"]["j1"],
                            "tie_policy": "one quadrant only",
                        },
                    },
                },
            },
            "tie policy",
        ),
    )
    for document, fragment in mutations:
        expect_blocked(
            lambda value=document: floating.validate_exact_real(
                value, implementation_sha
            ),
            fragment,
        )


def test_adjacent_authority_binding() -> None:
    original_path = floating.ADJACENT_PROOF
    original = json.loads(original_path.read_text())
    implementation_sha = hashlib.sha256(floating.IMPLEMENTATION.read_bytes()).hexdigest()
    mutations = (
        (
            {**original, "status": "ADJACENT_REDUCTION_COMPOSITION_OPEN"},
            "not proved",
        ),
        (
            {
                **original,
                "authority": {
                    **original["authority"],
                    "transition_bands_sha256": "0" * 64,
                },
            },
            "transition_bands hash drifted",
        ),
        (
            {
                **original,
                "release_implications": {
                    **original["release_implications"],
                    "backend_lowering_equivalence": "PROVED",
                },
            },
            "release implications drifted",
        ),
        (
            {
                **original,
                "transition_census": {
                    **original["transition_census"],
                    "f32": {
                        **original["transition_census"]["f32"],
                        "j0": {
                            **original["transition_census"]["f32"]["j0"],
                            "transition_band_count": 647,
                        },
                    },
                },
            },
            "census drifted",
        ),
    )
    for document, fragment in mutations:
        with patched_json(original_path, document) as mutated:
            floating.ADJACENT_PROOF = mutated
            expect_blocked(
                lambda: floating.load_adjacent_proof(implementation_sha), fragment
            )
    floating.ADJACENT_PROOF = original_path


def test_solver_root_authority_binding() -> None:
    original_path = floating.SOLVER_ROOT_ENVELOPES
    original = json.loads(original_path.read_text())
    implementation_sha = hashlib.sha256(
        floating.IMPLEMENTATION.read_bytes()
    ).hexdigest()
    mutations = (
        (
            {
                **original,
                "status": "SOURCE_GRAPH_SOLVER_MATHEMATICAL_ROOT_ENVELOPES_OPEN",
            },
            "identity drifted",
        ),
        (
            {
                **original,
                "authority": {
                    **original["authority"],
                    "oracle_sha256": "0" * 64,
                },
            },
            "oracle hash drifted",
        ),
        (
            {
                **original,
                "envelopes": {
                    **original["envelopes"],
                    "f64": {
                        **original["envelopes"]["f64"],
                        "root_ulp_error_upper": 21202,
                    },
                },
            },
            "f64 solver-root envelope drifted",
        ),
        (
            {
                **original,
                "release_implications": {
                    **original["release_implications"],
                    "backend_lowering_equivalence": "PROVED",
                },
            },
            "release boundary drifted",
        ),
    )
    for document, fragment in mutations:
        with patched_json(original_path, document) as mutated:
            floating.SOLVER_ROOT_ENVELOPES = mutated
            expect_blocked(
                lambda: floating.load_solver_root_envelopes(implementation_sha),
                fragment,
            )
    floating.SOLVER_ROOT_ENVELOPES = original_path


def test_transition_band_integrity() -> None:
    original = json.loads(adjacent.BANDS.read_text())
    original_case = original["cases"][0]
    mutations = (
        ("allowed", "IEEE band enclosure drifted"),
        ("span", "mismatch span drifted"),
        ("radius", "shadow radius drifted"),
        ("edge", "domain edge separation drifted"),
    )
    for mutation, fragment in mutations:
        case = json.loads(json.dumps(original_case))
        if mutation == "allowed":
            case["partition"]["bands"][0]["allowed_indices"] = [
                case["partition"]["bands"][0]["k"]
            ]
        elif mutation == "span":
            band = next(
                item
                for item in case["partition"]["bands"]
                if item["mismatch_spans"]
            )
            band["mismatch_spans"][0]["exact_index"] += 100
        elif mutation == "radius":
            case["parameters"]["shadow_reduction_radius"] = {
                "numerator": "0",
                "denominator": "1",
            }
        else:
            case["partition"]["domain_edge_separation"]["preceding_band_k"] += 1
        expect_blocked(
            lambda value=case: adjacent.verify_band_case(value, "f32", 0),
            fragment,
        )


def test_adjacent_certificate_integrity() -> None:
    adjacent.mp.mp.dps = 180
    rows = [
        json.loads(line)
        for line in adjacent.CERTIFICATES.read_text().splitlines()
    ]

    def render(items: list[dict[str, Any]]) -> bytes:
        return ("\n".join(json.dumps(item) for item in items) + "\n").encode()

    selected = json.loads(json.dumps(rows))
    quadrant = next(item for item in selected if item["kind"] == "adjacent_quadrant")
    quadrant["selected_quadrant"] = (quadrant["selected_quadrant"] + 1) % 4
    expect_blocked(
        lambda: adjacent.verify_certificates(render(selected)),
        "selected quadrant drifted",
    )

    escaped = json.loads(json.dumps(rows))
    quadrant = next(item for item in escaped if item["kind"] == "adjacent_quadrant")
    quadrant["shadow_math_absolute_error"] = "0"
    expect_blocked(
        lambda: adjacent.verify_certificates(render(escaped)),
        "escaped Arb certificate",
    )

    expect_blocked(
        lambda: adjacent.verify_certificates(render(rows[:-1])),
        "expected 36",
    )


def test_parity_shape() -> None:
    original = json.loads(envelopes.OBSERVATIONS.read_text())
    for parity in ({}, {"f32": {}, "f64": {}}, {"f32": original["backend_bit_parity"]["f32"]}):
        expect_blocked(
            lambda value=parity: envelopes.check_parity(
                {**original, "backend_bit_parity": value}
            ),
            "bit parity drifted",
        )


def main() -> None:
    test_envelope_limits()
    test_exact_real_binding()
    test_adjacent_authority_binding()
    test_solver_root_authority_binding()
    test_transition_band_integrity()
    test_adjacent_certificate_integrity()
    test_parity_shape()
    print("OK floating-point evidence mutations fail closed")


if __name__ == "__main__":
    main()
