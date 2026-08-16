#!/usr/bin/env python3
# SPDX-License-Identifier: ISC
"""Mutation tests for the f32/f64 cached-root certificate boundary."""

from __future__ import annotations

import json
import mpmath as mp
import re
import tempfile
from pathlib import Path
from typing import Any, Callable

import root_envelope_proof as proof


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
    return ("\n".join(json.dumps(row) for row in rows) + "\n").encode()


def row_at(rows: list[dict[str, Any]], precision: str, index: int) -> dict[str, Any]:
    matches = [
        row
        for row in rows
        if row.get("kind") == f"{precision}_cached_j1_root_envelope"
        and row.get("index") == index
    ]
    if len(matches) != 1:
        raise SystemExit(f"fixture cannot locate {precision} row {index}")
    return matches[0]


def mutate_cache_root(cache: str, precision: str) -> str:
    marker = f"module {precision}_cache = {{"
    cache_prefix, module = cache.split(marker, 1)
    root_array = re.search(
        rf"def root: \[256\]{precision} = \[(?P<body>.*?)\n  \]",
        module,
        re.DOTALL,
    )
    if root_array is None:
        raise SystemExit(f"fixture could not locate cached {precision} root array")
    first_literal = root_array.group("body").split(",", 1)[0].strip()
    replacement = "0x1.0000000000000p+0f32" if precision == "f32" else (
        "0x1.0000000000000p+0"
    )
    mutated_body = root_array.group("body").replace(first_literal, replacement, 1)
    mutated_module = (
        module[: root_array.start("body")]
        + mutated_body
        + module[root_array.end("body") :]
    )
    return cache_prefix + marker + mutated_module


def main() -> None:
    original_bytes = proof.CERTIFICATES.read_bytes()
    rows = [json.loads(line) for line in original_bytes.decode().splitlines()]
    cache = proof.CACHE.read_text()
    implementation = proof.IMPLEMENTATION.read_text()
    reference_rows = proof.load_reference_rows(proof.REFERENCE_CERTIFICATES.read_bytes())
    envelope_rows = proof.load_rows(original_bytes)

    expect_blocked(
        lambda: proof.load_rows(encoded(rows[:-1])),
        "expected exactly 512",
    )

    reordered = json.loads(json.dumps(rows))
    reordered[0], reordered[1] = reordered[1], reordered[0]
    expect_blocked(
        lambda: proof.load_rows(encoded(reordered)),
        "ordered f32/f64 pairs",
    )

    missing_reference_rounding = json.loads(json.dumps(reference_rows))
    missing_reference_rounding[0]["certified_unique_rounding"] = False
    expect_blocked(
        lambda: proof.load_reference_rows(encoded(missing_reference_rounding)),
        "missing reference rounding certificate",
    )

    wrong_reference_bisections = json.loads(json.dumps(reference_rows))
    wrong_reference_bisections[0]["bisections"] = 159
    expect_blocked(
        lambda: proof.load_reference_rows(encoded(wrong_reference_bisections)),
        "reference bisection count drifted",
    )

    wrong_reference = json.loads(json.dumps(reference_rows))
    wrong_reference[0]["root_f64_reference_bits"] = "0x0000000000000000"
    expect_blocked(
        lambda: proof.verify_reference_bindings(
            wrong_reference, envelope_rows, cache
        ),
        "independent f64 root-envelope certificate disagrees",
    )

    original_envelope_oracle = proof.ORACLE
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "root_envelopes.c"
        path.write_text(f'/* reads {proof.CACHE.as_posix()} */\n')
        try:
            proof.ORACLE = path
            expect_blocked(
                proof.verify_independent_source_separation,
                "separate envelope oracle acquired",
            )
        finally:
            proof.ORACLE = original_envelope_oracle

    wrong_pre_fix_sha = proof.PRE_FIX_CACHE_SHA256
    try:
        proof.PRE_FIX_CACHE_SHA256 = "0" * 64
        expect_blocked(
            lambda: proof.correction_document(
                reference_rows,
                original_bytes,
                proof.REFERENCE_CERTIFICATES.read_bytes(),
                cache,
                proof.sha256(proof.IMPLEMENTATION),
            ),
            "pre-fix cache SHA drifted",
        )
    finally:
        proof.PRE_FIX_CACHE_SHA256 = wrong_pre_fix_sha

    mp.mp.dps = 120
    references = [
        mp.besseljzero(1, index) for index in range(1, proof.ROOT_COUNT + 1)
    ]

    for precision in ("f32", "f64"):
        missing_rounding = json.loads(json.dumps(rows))
        row_at(missing_rounding, precision, 1)[
            f"certified_unique_{precision}_rounding"
        ] = False
        grouped = proof.load_rows(encoded(missing_rounding))
        expect_blocked(
            lambda selected=grouped[precision]: proof.verify_precision(
                selected, cache, implementation, precision, references
            ),
            f"missing unique-{precision}-rounding certificate",
        )

        wrong_bits = json.loads(json.dumps(rows))
        zero_bits = "0x00000000" if precision == "f32" else "0x0000000000000000"
        row_at(wrong_bits, precision, 1)[f"root_{precision}_bits"] = zero_bits
        grouped = proof.load_rows(encoded(wrong_bits))
        expect_blocked(
            lambda selected=grouped[precision]: proof.verify_precision(
                selected, cache, implementation, precision, references
            ),
            f"{precision} root hexadecimal/bits mismatch",
        )

        escaped_residual = json.loads(json.dumps(rows))
        row_at(escaped_residual, precision, 1)[
            "true_residual_upper_hex"
        ] = "0x0p+0"
        grouped = proof.load_rows(encoded(escaped_residual))
        expect_blocked(
            lambda selected=grouped[precision]: proof.verify_precision(
                selected, cache, implementation, precision, references
            ),
            f"{precision} residual escaped hexadecimal upper bound",
        )

        mutated_cache = mutate_cache_root(cache, precision)
        selected = proof.load_rows(original_bytes)[precision]
        expect_blocked(
            lambda changed=mutated_cache, rows_for_precision=selected: (
                proof.verify_precision(
                    rows_for_precision,
                    changed,
                    implementation,
                    precision,
                    references,
                )
            ),
            f"cached {precision} root escaped Arb-certified bits",
        )

        mutated_implementation = implementation.replace(
            f"let root = {precision}_cache.root[i]",
            f"let root = {precision}_cache.lo[i]",
            1,
        )
        expect_blocked(
            lambda changed=mutated_implementation, rows_for_precision=selected: (
                proof.verify_precision(
                    rows_for_precision,
                    cache,
                    changed,
                    precision,
                    references,
                )
            ),
            f"public {precision} cached-root source path drifted",
        )

    print("OK f32/f64 cached-root evidence mutations fail closed")


if __name__ == "__main__":
    main()
