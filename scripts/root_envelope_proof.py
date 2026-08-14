#!/usr/bin/env python3
# SPDX-License-Identifier: ISC
"""Certify f32/f64 public cached-root ULP and true-residual envelopes.

The FLINT/Arb ledger is generated independently from the Futhark package.  This
checker replays every root with mpmath, binds each precision's bits to the
checked-in disposable cache, and emits separate compact, fail-closed summaries.
It deliberately does not certify ``positive_j1_root_solved``, the residual
reported by the Futhark approximation, or any backend lowering.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import struct
import subprocess
from pathlib import Path
from typing import Any

import mpmath as mp

CERTIFICATES = Path("evidence/root-envelope-certificates.jsonl")
REFERENCE_CERTIFICATES = Path("evidence/arb-certificates.jsonl")
CACHE = Path("lib/github.com/Jesssullivan/futhark-bessel/root_cache.fut")
IMPLEMENTATION = Path("lib/github.com/Jesssullivan/futhark-bessel/bessel_internal.fut")
ORACLE = Path("oracle/root_envelopes.c")
REFERENCE_ORACLE = Path("oracle/arb_oracle.c")
RENDERER = Path("scripts/render_root_cache.py")
RENDERER_MUTATIONS = Path("scripts/test_render_root_cache_fail_closed.py")
VERIFIER = Path("scripts/root_envelope_proof.py")
OUTPUTS = {
    "f32": Path("evidence/f32-root-envelope.json"),
    "f64": Path("evidence/f64-root-envelope.json"),
}
CORRECTION_OUTPUT = Path("evidence/f64-root-cache-correction.json")

ROOT_COUNT = 256
DECLARED_TRUE_RESIDUAL_ENVELOPE_HEX = {
    "f32": "0x1.0000000000000p-19",
    "f64": "0x1.0000000000000p-48",
}
EXPECTED_IMPLEMENTATION_SHA256 = (
    "2b459fb3e24e82a825db5f44cc8b3ebe9c8387d598235f84c4e80996b4e7d9d1"
)
PRE_FIX_COMMIT = "6efb9fe4f26bede371dd442c29e3c0d0f4e996e2"
PRE_FIX_CACHE_SHA256 = (
    "ba31e5cb5d34ca65ba6a2ff0b6d194b2bd1cfe8a286ebb70479766ae16c04642"
)
PRE_FIX_RENDERER_SHA256 = (
    "705aea38d8e4f44bc035e9604e2f2126487302994a598561eddb75446fed7710"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bit_width(precision: str) -> int:
    return 32 if precision == "f32" else 64


def bits_of(precision: str, value: float) -> int:
    if precision == "f32":
        return struct.unpack(">I", struct.pack(">f", value))[0]
    return struct.unpack(">Q", struct.pack(">d", value))[0]


def value_from_bits(precision: str, bits: int) -> float:
    if precision == "f32":
        return struct.unpack(">f", struct.pack(">I", bits))[0]
    return struct.unpack(">d", struct.pack(">Q", bits))[0]


def independently_rounds_to(
    precision: str, reference: mp.mpf, candidate_bits: int
) -> bool:
    """Check that a positive normal reference lies in this RNE rounding cell."""
    normal_min = 0x00800000 if precision == "f32" else 0x0010000000000000
    infinity = 0x7F800000 if precision == "f32" else 0x7FF0000000000000
    if candidate_bits < normal_min or candidate_bits >= infinity:
        raise SystemExit(f"non-positive-normal {precision} root bits")
    candidate = mp.mpf(value_from_bits(precision, candidate_bits))
    predecessor = mp.mpf(value_from_bits(precision, candidate_bits - 1))
    successor = mp.mpf(value_from_bits(precision, candidate_bits + 1))
    lower_midpoint = (predecessor + candidate) / 2
    upper_midpoint = (candidate + successor) / 2
    if candidate_bits % 2 == 0:
        return lower_midpoint <= reference <= upper_midpoint
    return lower_midpoint < reference < upper_midpoint


def parse_bits(text: Any, precision: str) -> int:
    width = bit_width(precision)
    if not isinstance(text, str) or not re.fullmatch(
        rf"0x[0-9a-f]{{{width // 4}}}", text
    ):
        raise SystemExit(f"malformed {precision} root bits: {text!r}")
    return int(text, 16)


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
        raise SystemExit("malformed Arb residual ball")
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
        raise SystemExit(f"malformed Arb residual ball: {text!r}")
    midpoint = mp.mpf(ball.group(1))
    radius = mp.mpf(ball.group(2))
    if radius < 0:
        raise SystemExit(f"negative Arb residual radius: {text!r}")
    return midpoint - radius, midpoint + radius


def precision_module(text: str, precision: str, source: str) -> str:
    marker = f"module {precision}_cache = {{" if source == "cache" else (
        f"module {precision}_impl = {{"
    )
    if text.count(marker) != 1:
        raise SystemExit(f"cannot locate unique {precision} {source} module")
    module = text.split(marker, 1)[1]
    if precision == "f64":
        next_marker = "module f32_cache = {" if source == "cache" else (
            "module f32_impl = {"
        )
        if module.count(next_marker) != 1:
            raise SystemExit(f"cannot locate {precision} {source} module boundary")
        module = module.split(next_marker, 1)[0]
    return module


def parse_cache_arrays(text: str, precision: str) -> dict[str, list[float]]:
    module = precision_module(text, precision, "cache")
    suffix = "f32" if precision == "f32" else ""
    arrays: dict[str, list[float]] = {}
    for name in ("lo", "hi", "root"):
        match = re.search(
            rf"def {name}: \[256\]{precision} = \[(?P<body>.*?)\n  \]",
            module,
            re.DOTALL,
        )
        if match is None:
            raise SystemExit(f"cannot locate {precision} cache array {name}")
        tokens = [item.strip() for item in match.group("body").split(",")]
        if len(tokens) != ROOT_COUNT:
            raise SystemExit(
                f"{precision} cache array {name} must contain exactly 256 literals"
            )
        if suffix and any(not item.endswith(suffix) for item in tokens):
            raise SystemExit(f"{precision} cache array {name} has an untyped literal")
        if not suffix and any(item.endswith("f32") for item in tokens):
            raise SystemExit(f"{precision} cache array {name} has a wrong-width literal")
        values = [
            nonnegative_hex(item.removesuffix(suffix), f"{precision} cache {name}")
            for item in tokens
        ]
        if any(
            value_from_bits(precision, bits_of(precision, value)) != value
            for value in values
        ):
            raise SystemExit(f"non-{precision} value in cache array {name}")
        arrays[name] = values
    return arrays


def check_public_cache_path(source: str, precision: str) -> None:
    module = precision_module(source, precision, "implementation")
    required = (
        f"let root = {precision}_cache.root[i]",
        f"lo = {precision}_cache.lo[i]",
        f"hi = {precision}_cache.hi[i]",
        f"residual = {precision}.abs (j1_finite root)",
        "converged = true",
    )
    if any(module.count(fragment) != 1 for fragment in required):
        raise SystemExit(f"public {precision} cached-root source path drifted")


def load_rows(data: bytes) -> dict[str, list[dict[str, Any]]]:
    try:
        rows = [json.loads(line) for line in data.decode().splitlines()]
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SystemExit("malformed root-envelope certificate ledger") from error
    if len(rows) != 2 * ROOT_COUNT:
        raise SystemExit(
            f"expected exactly {2 * ROOT_COUNT} root-envelope rows, got {len(rows)}"
        )
    expected = [
        (f"{precision}_cached_j1_root_envelope", index)
        for index in range(1, ROOT_COUNT + 1)
        for precision in ("f32", "f64")
    ]
    actual = [(row.get("kind"), row.get("index")) for row in rows]
    if actual != expected:
        raise SystemExit(
            "root-envelope rows must cover ordered f32/f64 pairs for indices 1..256"
        )
    return {
        precision: [
            row
            for row in rows
            if row["kind"] == f"{precision}_cached_j1_root_envelope"
        ]
        for precision in ("f32", "f64")
    }


def load_reference_rows(data: bytes) -> list[dict[str, Any]]:
    try:
        rows = [json.loads(line) for line in data.decode().splitlines()]
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SystemExit("malformed Arb reference certificate ledger") from error
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
            raise SystemExit(f"Arb reference root fields drifted at index {row['index']}")
        if row["certified_sign_change"] is not True:
            raise SystemExit(f"missing sign-change certificate at index {row['index']}")
        if row["certified_unique_rounding"] is not True:
            raise SystemExit(f"missing reference rounding certificate at index {row['index']}")
        if row["bisections"] != 160:
            raise SystemExit(f"reference bisection count drifted at index {row['index']}")
        parse_bits(row["root_f32_reference_bits"], "f32")
        parse_bits(row["root_f64_reference_bits"], "f64")
    return roots


def verify_reference_bindings(
    reference_rows: list[dict[str, Any]],
    envelope_rows: dict[str, list[dict[str, Any]]],
    cache_text: str,
) -> None:
    for precision in ("f32", "f64"):
        cache_roots = parse_cache_arrays(cache_text, precision)["root"]
        for index, (reference, envelope, cached_root) in enumerate(
            zip(
                reference_rows,
                envelope_rows[precision],
                cache_roots,
                strict=True,
            ),
            start=1,
        ):
            reference_value = parse_bits(
                reference[f"root_{precision}_reference_bits"], precision
            )
            envelope_value = parse_bits(envelope[f"root_{precision}_bits"], precision)
            if envelope_value != reference_value:
                raise SystemExit(
                    f"independent {precision} root-envelope certificate disagrees "
                    f"with Arb reference bits at index {index}"
                )
            if bits_of(precision, cached_root) != reference_value:
                raise SystemExit(
                    f"generated {precision} cache disagrees with Arb reference bits "
                    f"at index {index}"
                )


def verify_independent_source_separation() -> None:
    reference_source = REFERENCE_ORACLE.read_text()
    envelope_source = ORACLE.read_text()
    forbidden_reference_inputs = (
        CACHE.as_posix(),
        IMPLEMENTATION.as_posix(),
        RENDERER.as_posix(),
        CERTIFICATES.as_posix(),
        "root_cache.fut",
        "bessel_internal.fut",
        "render_root_cache.py",
        "root-envelope-certificates.jsonl",
    )
    forbidden_envelope_inputs = (
        CACHE.as_posix(),
        IMPLEMENTATION.as_posix(),
        RENDERER.as_posix(),
        REFERENCE_CERTIFICATES.as_posix(),
        "root_cache.fut",
        "bessel_internal.fut",
        "render_root_cache.py",
        "arb-certificates.jsonl",
    )
    if any(value in reference_source for value in forbidden_reference_inputs):
        raise SystemExit("reference oracle acquired a generated-cache dependency")
    if any(value in envelope_source for value in forbidden_envelope_inputs):
        raise SystemExit("separate envelope oracle acquired a cache/reference dependency")


def git_show(commit: str, path: Path) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{commit}:{path.as_posix()}"],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise SystemExit(
            f"cannot inspect pre-fix evidence at {commit}:{path.as_posix()}"
        )
    return result.stdout


def correction_document(
    reference_rows: list[dict[str, Any]],
    certificate_bytes: bytes,
    reference_bytes: bytes,
    cache_text: str,
    implementation_sha: str,
) -> dict[str, Any]:
    pre_fix_cache_bytes = git_show(PRE_FIX_COMMIT, CACHE)
    pre_fix_renderer_bytes = git_show(PRE_FIX_COMMIT, RENDERER)
    pre_fix_implementation_bytes = git_show(PRE_FIX_COMMIT, IMPLEMENTATION)
    if hashlib.sha256(pre_fix_cache_bytes).hexdigest() != PRE_FIX_CACHE_SHA256:
        raise SystemExit("pre-fix cache SHA drifted")
    if hashlib.sha256(pre_fix_renderer_bytes).hexdigest() != PRE_FIX_RENDERER_SHA256:
        raise SystemExit("pre-fix renderer SHA drifted")
    if hashlib.sha256(pre_fix_implementation_bytes).hexdigest() != (
        EXPECTED_IMPLEMENTATION_SHA256
    ):
        raise SystemExit("pre-fix implementation SHA drifted")

    pre_fix_cache_text = pre_fix_cache_bytes.decode()
    pre_fix_roots = {
        precision: parse_cache_arrays(pre_fix_cache_text, precision)["root"]
        for precision in ("f32", "f64")
    }
    current_roots = {
        precision: parse_cache_arrays(cache_text, precision)["root"]
        for precision in ("f32", "f64")
    }
    reference_bits = {
        precision: [
            parse_bits(row[f"root_{precision}_reference_bits"], precision)
            for row in reference_rows
        ]
        for precision in ("f32", "f64")
    }
    pre_fix_ulp_errors = {
        precision: [
            abs(bits_of(precision, root) - certified)
            for root, certified in zip(
                pre_fix_roots[precision], reference_bits[precision], strict=True
            )
        ]
        for precision in ("f32", "f64")
    }
    current_ulp_errors = {
        precision: [
            abs(bits_of(precision, root) - certified)
            for root, certified in zip(
                current_roots[precision], reference_bits[precision], strict=True
            )
        ]
        for precision in ("f32", "f64")
    }
    f64_mismatches = [
        index
        for index, error in enumerate(pre_fix_ulp_errors["f64"], start=1)
        if error != 0
    ]
    if len(f64_mismatches) != 111 or max(pre_fix_ulp_errors["f64"]) != 1:
        raise SystemExit("pre-fix f64 mismatch census drifted")
    if f64_mismatches[0] != 1:
        raise SystemExit("pre-fix root-1 witness is missing")
    if any(pre_fix_ulp_errors["f32"]):
        raise SystemExit("pre-fix f32 roots unexpectedly disagreed with reference bits")
    if any(current_ulp_errors["f32"]) or any(current_ulp_errors["f64"]):
        raise SystemExit("corrected root cache still disagrees with reference bits")
    f32_changed = sum(
        bits_of("f32", before) != bits_of("f32", after)
        for before, after in zip(
            pre_fix_roots["f32"], current_roots["f32"], strict=True
        )
    )
    if f32_changed != 0:
        raise SystemExit("f32 root cache changed during f64 correction")
    f64_changes = [
        (index, abs(bits_of("f64", before) - bits_of("f64", after)))
        for index, (before, after) in enumerate(
            zip(pre_fix_roots["f64"], current_roots["f64"], strict=True),
            start=1,
        )
        if bits_of("f64", before) != bits_of("f64", after)
    ]
    f64_changed_indices = [index for index, _ in f64_changes]
    if f64_changed_indices != f64_mismatches:
        raise SystemExit("f64 corrected-root census drifted from pre-fix mismatches")
    if any(distance != 1 for _, distance in f64_changes):
        raise SystemExit("f64 cache correction contains a non-1-ULP change")

    pre_fix_root1 = bits_of("f64", pre_fix_roots["f64"][0])
    certified_root1 = reference_bits["f64"][0]
    if pre_fix_root1 != 0x400EA75575AF6F08:
        raise SystemExit("pre-fix root-1 cached bits drifted")
    if certified_root1 != 0x400EA75575AF6F09:
        raise SystemExit("certified root-1 reference bits drifted")
    f64_corrections = [
        {
            "index": index,
            "cached_bits": (
                f"0x{bits_of('f64', pre_fix_roots['f64'][index - 1]):016x}"
            ),
            "certified_bits": f"0x{reference_bits['f64'][index - 1]:016x}",
            "ulp_error": pre_fix_ulp_errors["f64"][index - 1],
        }
        for index in f64_mismatches
    ]

    return {
        "schema_version": "futhark-bessel.f64-root-cache-correction.v1",
        "status": "SOURCE_CACHE_GENERATOR_CORRECTED",
        "release_conformance": False,
        "pre_fix": {
            "commit": PRE_FIX_COMMIT,
            "root_cache": str(CACHE),
            "root_cache_sha256": PRE_FIX_CACHE_SHA256,
            "renderer": str(RENDERER),
            "renderer_sha256": PRE_FIX_RENDERER_SHA256,
            "implementation": str(IMPLEMENTATION),
            "implementation_sha256": implementation_sha,
            "f64_mismatched_root_count": len(f64_mismatches),
            "f64_mismatched_root_indices": f64_mismatches,
            "f64_corrections": f64_corrections,
            "f64_maximum_ulp_error": max(pre_fix_ulp_errors["f64"]),
            "f32_mismatched_root_count": sum(
                error != 0 for error in pre_fix_ulp_errors["f32"]
            ),
            "defect": (
                "the renderer evaluated the midpoint expression for adjacent "
                "f64 endpoints in binary64; adding the representable half-ULP "
                "to an endpoint is a halfway rounding tie, so it selected an "
                "endpoint by ties-to-even instead of by the mathematical root's "
                "position relative to the real midpoint"
            ),
            "first_witness": {
                "index": 1,
                "cached_bits": f"0x{pre_fix_root1:016x}",
                "certified_bits": f"0x{certified_root1:016x}",
                "ulp_error": abs(pre_fix_root1 - certified_root1),
            },
        },
        "correction": {
            "method": (
                "render the independently Arb-certified reference bits rather "
                "than selecting an endpoint through a floating midpoint"
            ),
            "renderer": str(RENDERER),
            "renderer_sha256": sha256(RENDERER),
            "renderer_mutation_checks": str(RENDERER_MUTATIONS),
            "renderer_mutation_checks_sha256": sha256(RENDERER_MUTATIONS),
            "root_cache": str(CACHE),
            "root_cache_sha256": sha256(CACHE),
            "f32_changed_root_count": f32_changed,
            "f64_changed_root_count": len(f64_changed_indices),
            "f64_every_change_exactly_one_ulp": True,
            "f32_remaining_ulp_mismatches": sum(
                error != 0 for error in current_ulp_errors["f32"]
            ),
            "f64_remaining_ulp_mismatches": sum(
                error != 0 for error in current_ulp_errors["f64"]
            ),
        },
        "authority": {
            "reference_oracle": str(REFERENCE_ORACLE),
            "reference_oracle_sha256": sha256(REFERENCE_ORACLE),
            "reference_certificates": str(REFERENCE_CERTIFICATES),
            "reference_certificates_sha256": hashlib.sha256(
                reference_bytes
            ).hexdigest(),
            "separate_envelope_oracle": str(ORACLE),
            "separate_envelope_oracle_sha256": sha256(ORACLE),
            "separate_envelope_certificates": str(CERTIFICATES),
            "separate_envelope_certificates_sha256": hashlib.sha256(
                certificate_bytes
            ).hexdigest(),
            "implementation": str(IMPLEMENTATION),
            "implementation_sha256": implementation_sha,
            "verifier": str(VERIFIER),
            "verifier_sha256": sha256(VERIFIER),
            "certificate_relationship": (
                "the reference oracle's uniquely rounded bits feed the renderer; "
                "the separate envelope oracle recomputes roots and residuals "
                "without consuming the cache; mpmath independently replays both"
            ),
        },
        "scope": {
            "covered": (
                "the historical f64 endpoint-selection defect, its root-1 "
                "witness and complete 256-root mismatch census, corrected cache "
                "binding, confirmation that all f32 root literals are unchanged, "
                "and the independently certified source-cache true-residual "
                "envelope |J1(r_hat)| <= 0x1p-48"
            ),
            "excluded": (
                "positive_j1_root_solved arithmetic and stopping logic, the "
                "implementation-reported approximate residual, and C/WASM/WebGPU "
                "lowering or runtime conformance"
            ),
        },
    }


def verify_precision(
    rows: list[dict[str, Any]],
    cache_text: str,
    implementation_text: str,
    precision: str,
    references: list[mp.mpf],
) -> dict[str, Any]:
    arrays = parse_cache_arrays(cache_text, precision)
    check_public_cache_path(implementation_text, precision)
    declared_residual = float.fromhex(
        DECLARED_TRUE_RESIDUAL_ENVELOPE_HEX[precision]
    )
    bits_field = f"root_{precision}_bits"
    hex_field = f"root_{precision}_hex"
    unique_field = f"certified_unique_{precision}_rounding"
    expected_fields = {
        "kind",
        "index",
        bits_field,
        hex_field,
        "true_residual_ball",
        "true_residual_upper_hex",
        "bisections",
        unique_field,
        "certified_true_residual",
    }
    maximum_upper = -1.0
    maximum_value = mp.mpf("-1")
    maximum_ulp_error = -1
    worst_upper_index = 0
    worst_value_index = 0

    for expected_index, (row, reference) in enumerate(
        zip(rows, references, strict=True), start=1
    ):
        if set(row) != expected_fields:
            raise SystemExit(
                f"{precision} root-envelope row fields drifted at index {expected_index}"
            )
        if row["kind"] != f"{precision}_cached_j1_root_envelope":
            raise SystemExit(
                f"unexpected {precision} root-envelope kind at index {expected_index}"
            )
        if row["index"] != expected_index or row["bisections"] != 192:
            raise SystemExit(
                f"{precision} root-envelope coverage drifted at index {expected_index}"
            )
        if row[unique_field] is not True:
            raise SystemExit(
                f"missing unique-{precision}-rounding certificate at index "
                f"{expected_index}"
            )
        if row["certified_true_residual"] is not True:
            raise SystemExit(
                f"missing {precision} true-residual certificate at index "
                f"{expected_index}"
            )

        certified_bits = parse_bits(row[bits_field], precision)
        root_hex = nonnegative_hex(row[hex_field], f"{precision} root")
        if bits_of(precision, root_hex) != certified_bits:
            raise SystemExit(
                f"{precision} root hexadecimal/bits mismatch at index {expected_index}"
            )
        cached_root = arrays["root"][expected_index - 1]
        cached_bits = bits_of(precision, cached_root)
        if cached_bits != certified_bits:
            raise SystemExit(
                f"cached {precision} root escaped Arb-certified bits at index "
                f"{expected_index}"
            )

        if not independently_rounds_to(precision, reference, certified_bits):
            raise SystemExit(
                f"mpmath disagrees with {precision} root rounding at index "
                f"{expected_index}"
            )
        ulp_error = abs(cached_bits - certified_bits)
        maximum_ulp_error = max(maximum_ulp_error, ulp_error)

        cache_lo = mp.mpf(arrays["lo"][expected_index - 1])
        cache_hi = mp.mpf(arrays["hi"][expected_index - 1])
        cached_root_exact = mp.mpf(cached_root)
        if not cache_lo <= reference <= cache_hi:
            raise SystemExit(
                f"mathematical root escaped cached {precision} bracket at index "
                f"{expected_index}"
            )
        if not cache_lo <= cached_root_exact <= cache_hi:
            raise SystemExit(
                f"cached {precision} root escaped cached bracket at index "
                f"{expected_index}"
            )

        residual = abs(mp.besselj(1, cached_root_exact))
        ball_lo, ball_hi = parse_ball(row["true_residual_ball"])
        if ball_lo < 0 or not ball_lo <= residual <= ball_hi:
            raise SystemExit(
                f"mpmath {precision} residual escaped Arb ball at index "
                f"{expected_index}"
            )
        residual_upper = nonnegative_hex(
            row["true_residual_upper_hex"],
            f"{precision} true residual upper bound",
        )
        if mp.mpf(residual_upper) < ball_hi or mp.mpf(residual_upper) < residual:
            raise SystemExit(
                f"{precision} residual escaped hexadecimal upper bound at index "
                f"{expected_index}"
            )
        if residual_upper > declared_residual:
            raise SystemExit(
                f"{precision} root {expected_index} escaped declared true-residual "
                f"envelope {DECLARED_TRUE_RESIDUAL_ENVELOPE_HEX[precision]}"
            )
        if residual_upper > maximum_upper:
            maximum_upper = residual_upper
            worst_upper_index = expected_index
        if residual > maximum_value:
            maximum_value = residual
            worst_value_index = expected_index

    return {
        "root_count": len(rows),
        "maximum_ulp_error": maximum_ulp_error,
        "declared_true_residual_abs_upper_hex": (
            DECLARED_TRUE_RESIDUAL_ENVELOPE_HEX[precision]
        ),
        "certified_maximum_true_residual_upper_hex": maximum_upper.hex(),
        "certified_maximum_true_residual_upper_index": worst_upper_index,
        "independent_maximum_true_residual_decimal": mp.nstr(
            maximum_value, 40, min_fixed=0, max_fixed=0
        ),
        "independent_maximum_true_residual_index": worst_value_index,
    }


def verify_rows(
    data: bytes, cache_text: str, implementation_text: str
) -> dict[str, dict[str, Any]]:
    mp.mp.dps = 120
    grouped = load_rows(data)
    references = [mp.besseljzero(1, index) for index in range(1, ROOT_COUNT + 1)]
    return {
        precision: verify_precision(
            grouped[precision],
            cache_text,
            implementation_text,
            precision,
            references,
        )
        for precision in ("f32", "f64")
    }


def release_implications() -> dict[str, str]:
    return {
        "f32_cached_root_ulp_and_mathematical_residual": "CERTIFIED",
        "f64_cached_root_ulp_and_mathematical_residual": "CERTIFIED",
        "f32_reported_residual": "BACKEND_CONFORMANCE_OPEN",
        "f64_reported_residual": "BACKEND_CONFORMANCE_OPEN",
        "root_solver_arithmetic": "OPEN",
        "backend_lowering_equivalence": "OPEN",
        "overall_release_status": "INCOMPLETE",
    }


def document(
    precision: str,
    results: dict[str, Any],
    certificate_bytes: bytes,
    implementation_sha: str,
) -> dict[str, Any]:
    binary_name = "binary32" if precision == "f32" else "binary64"
    return {
        "schema_version": f"futhark-bessel.{precision}-root-envelope.v1",
        "status": "SOURCE_CACHE_ROOT_ENVELOPE_CERTIFIED",
        "release_conformance": False,
        "scope": {
            "covered": (
                f"all 256 {binary_name} root literals returned by the public "
                "cached positive_j1_root path; ULP distance is measured against "
                "the correctly rounded mathematical J1 root and residual means "
                "the independent mathematical value |J1(r_hat)|; Arb-certified "
                "reference bits generate the disposable, non-authoritative cache, "
                "while a separate Arb computation and mpmath replay verify it"
            ),
            "excluded": (
                "positive_j1_root_solved arithmetic and stopping logic, the "
                "implementation-reported approximate residual, and C/WASM/WebGPU "
                "lowering or runtime conformance"
            ),
        },
        "authority": {
            "oracle": str(ORACLE),
            "oracle_sha256": sha256(ORACLE),
            "certificates": str(CERTIFICATES),
            "certificates_sha256": hashlib.sha256(certificate_bytes).hexdigest(),
            "independent_verifier": str(VERIFIER),
            "independent_verifier_sha256": sha256(VERIFIER),
            "independent_library": "mpmath 1.4.1 besselj/besseljzero",
            "root_cache": str(CACHE),
            "root_cache_sha256": sha256(CACHE),
            "root_cache_role": "NON_AUTHORITATIVE_DERIVED_ARTIFACT",
            "root_cache_renderer": str(RENDERER),
            "root_cache_renderer_sha256": sha256(RENDERER),
            "root_cache_renderer_mutation_checks": str(RENDERER_MUTATIONS),
            "root_cache_renderer_mutation_checks_sha256": sha256(
                RENDERER_MUTATIONS
            ),
            "root_reference_oracle": str(REFERENCE_ORACLE),
            "root_reference_oracle_sha256": sha256(REFERENCE_ORACLE),
            "root_reference_certificates": str(REFERENCE_CERTIFICATES),
            "root_reference_certificates_sha256": sha256(REFERENCE_CERTIFICATES),
            "implementation": str(IMPLEMENTATION),
            "implementation_sha256": implementation_sha,
            "certificate_library": "FLINT/Arb 3.6.0 arb_hypgeom_bessel_j",
        },
        "envelopes": {
            "precision": precision,
            "index_domain": {"minimum": 1, "maximum": ROOT_COUNT},
            "root_ulp_error_upper": results["maximum_ulp_error"],
            "true_residual_abs_upper_hex": results[
                "declared_true_residual_abs_upper_hex"
            ],
            "certified_maximum_true_residual_upper_hex": results[
                "certified_maximum_true_residual_upper_hex"
            ],
            "certified_maximum_true_residual_upper_index": results[
                "certified_maximum_true_residual_upper_index"
            ],
        },
        "independent_replay": {
            "maximum_true_residual_decimal": results[
                "independent_maximum_true_residual_decimal"
            ],
            "maximum_true_residual_index": results[
                "independent_maximum_true_residual_index"
            ],
            "root_count": results["root_count"],
            "all_correctly_rounded": True,
        },
        "release_implications": release_implications(),
    }


def generate() -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    implementation_sha = sha256(IMPLEMENTATION)
    if implementation_sha != EXPECTED_IMPLEMENTATION_SHA256:
        raise SystemExit("implementation SHA drifted; re-audit root evidence scope")
    certificate_bytes = CERTIFICATES.read_bytes()
    reference_bytes = REFERENCE_CERTIFICATES.read_bytes()
    cache_text = CACHE.read_text()
    implementation_text = IMPLEMENTATION.read_text()
    verify_independent_source_separation()
    envelope_rows = load_rows(certificate_bytes)
    reference_rows = load_reference_rows(reference_bytes)
    verify_reference_bindings(reference_rows, envelope_rows, cache_text)
    results = verify_rows(certificate_bytes, cache_text, implementation_text)
    documents = {
        precision: document(
            precision,
            results[precision],
            certificate_bytes,
            implementation_sha,
        )
        for precision in ("f32", "f64")
    }
    correction = correction_document(
        reference_rows,
        certificate_bytes,
        reference_bytes,
        cache_text,
        implementation_sha,
    )
    return documents, correction


def main() -> None:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--write", action="store_true")
    action.add_argument("--check", action="store_true")
    args = parser.parse_args()
    generated, correction = generate()
    rendered = {
        precision: json.dumps(generated[precision], indent=2, sort_keys=True) + "\n"
        for precision in ("f32", "f64")
    }
    rendered_correction = json.dumps(correction, indent=2, sort_keys=True) + "\n"
    if args.write:
        for precision, output in OUTPUTS.items():
            output.write_text(rendered[precision])
            print(f"wrote {output}")
        CORRECTION_OUTPUT.write_text(rendered_correction)
        print(f"wrote {CORRECTION_OUTPUT}")
        return
    for precision, output in OUTPUTS.items():
        if not output.exists() or output.read_text() != rendered[precision]:
            raise SystemExit(
                f"{precision} root-envelope summary is stale; run "
                "scripts/root_envelope_proof.py --write"
            )
    if (
        not CORRECTION_OUTPUT.exists()
        or CORRECTION_OUTPUT.read_text() != rendered_correction
    ):
        raise SystemExit(
            "f64 root-cache correction witness is stale; run "
            "scripts/root_envelope_proof.py --write"
        )
    print(
        "OK all 256 cached f32/f64 roots are correctly rounded with certified "
        "true residual <= "
        f"{DECLARED_TRUE_RESIDUAL_ENVELOPE_HEX['f32']} (f32) and "
        f"{DECLARED_TRUE_RESIDUAL_ENVELOPE_HEX['f64']} (f64); solver arithmetic "
        "and backend conformance remain OPEN"
    )


if __name__ == "__main__":
    main()
