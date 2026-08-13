#!/usr/bin/env python3
# SPDX-License-Identifier: ISC
"""Mutation tests for the f32 cached-root certificate boundary."""

from __future__ import annotations

import json
import re
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


def main() -> None:
    original_bytes = proof.CERTIFICATES.read_bytes()
    rows = proof.load_rows(original_bytes)
    cache = proof.CACHE.read_text()
    implementation = proof.IMPLEMENTATION.read_text()

    expect_blocked(
        lambda: proof.verify_rows(encoded(rows[:-1]), cache, implementation),
        "expected exactly 256",
    )

    missing_rounding = json.loads(json.dumps(rows))
    missing_rounding[0]["certified_unique_f32_rounding"] = False
    expect_blocked(
        lambda: proof.verify_rows(encoded(missing_rounding), cache, implementation),
        "missing unique-rounding certificate",
    )

    wrong_bits = json.loads(json.dumps(rows))
    wrong_bits[0]["root_f32_bits"] = "0x00000000"
    expect_blocked(
        lambda: proof.verify_rows(encoded(wrong_bits), cache, implementation),
        "root hexadecimal/bits mismatch",
    )

    escaped_residual = json.loads(json.dumps(rows))
    escaped_residual[0]["true_residual_upper_hex"] = "0x0p+0"
    expect_blocked(
        lambda: proof.verify_rows(encoded(escaped_residual), cache, implementation),
        "residual escaped hexadecimal upper bound",
    )

    cache_prefix, f32_module = cache.split("module f32_cache = {", 1)
    root_array = re.search(
        r"def root: \[256\]f32 = \[(?P<body>.*?)\n  \]",
        f32_module,
        re.DOTALL,
    )
    if root_array is None:
        raise SystemExit("fixture could not locate cached root array")
    first_literal = root_array.group("body").split(",", 1)[0].strip()
    mutated_body = root_array.group("body").replace(
        first_literal, "0x1.0000000000000p+0f32", 1
    )
    mutated_module = (
        f32_module[: root_array.start("body")]
        + mutated_body
        + f32_module[root_array.end("body") :]
    )
    mutated_cache = cache_prefix + "module f32_cache = {" + mutated_module
    expect_blocked(
        lambda: proof.verify_rows(original_bytes, mutated_cache, implementation),
        "cached root escaped Arb-certified bits",
    )

    mutated_implementation = implementation.replace(
        "let root = f32_cache.root[i]", "let root = f32_cache.lo[i]", 1
    )
    expect_blocked(
        lambda: proof.verify_rows(original_bytes, cache, mutated_implementation),
        "public f32 cached-root source path drifted",
    )

    print("OK f32 cached-root evidence mutations fail closed")


if __name__ == "__main__":
    main()
