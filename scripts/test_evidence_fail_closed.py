#!/usr/bin/env python3
# SPDX-License-Identifier: ISC
"""Mutation tests for the compact floating-point evidence gates."""

from __future__ import annotations

import json
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

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
        with patched_json(original_path, document) as mutated:
            floating.EXACT_REAL = mutated
            expect_blocked(floating.generate, fragment)
    floating.EXACT_REAL = original_path


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
    test_parity_shape()
    print("OK floating-point evidence mutations fail closed")


if __name__ == "__main__":
    main()
