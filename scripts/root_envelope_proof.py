#!/usr/bin/env python3
# SPDX-License-Identifier: ISC
"""Certify the f32 public cached-root ULP and mathematical residual envelope.

The FLINT/Arb ledger is generated independently from the Futhark package.  This
checker replays every root with mpmath, binds the resulting bits to the checked
in disposable cache, and emits a compact, fail-closed summary.  It deliberately
does not certify ``positive_j1_root_solved`` or any backend lowering.
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

CERTIFICATES = Path("evidence/root-envelope-certificates.jsonl")
CACHE = Path("lib/github.com/Jesssullivan/futhark-bessel/root_cache.fut")
IMPLEMENTATION = Path("lib/github.com/Jesssullivan/futhark-bessel/bessel_internal.fut")
ORACLE = Path("oracle/root_envelopes.c")
VERIFIER = Path("scripts/root_envelope_proof.py")
OUTPUT = Path("evidence/f32-root-envelope.json")

ROOT_COUNT = 256
DECLARED_TRUE_RESIDUAL_ENVELOPE_HEX = "0x1.0000000000000p-19"
EXPECTED_IMPLEMENTATION_SHA256 = (
    "2b459fb3e24e82a825db5f44cc8b3ebe9c8387d598235f84c4e80996b4e7d9d1"
)

EXPECTED_FIELDS = {
    "kind",
    "index",
    "root_f32_bits",
    "root_f32_hex",
    "true_residual_ball",
    "true_residual_upper_hex",
    "bisections",
    "certified_unique_f32_rounding",
    "certified_true_residual",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def f32_bits(value: float) -> int:
    return struct.unpack(">I", struct.pack(">f", value))[0]


def f32_from_bits(bits: int) -> float:
    return struct.unpack(">f", struct.pack(">I", bits))[0]


def parse_bits(text: Any) -> int:
    if not isinstance(text, str) or not re.fullmatch(r"0x[0-9a-f]{8}", text):
        raise SystemExit(f"malformed f32 root bits: {text!r}")
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


def parse_cache_arrays(text: str) -> dict[str, list[float]]:
    marker = "module f32_cache = {"
    if text.count(marker) != 1:
        raise SystemExit("cannot locate unique f32 root cache module")
    module = text.split(marker, 1)[1]
    arrays: dict[str, list[float]] = {}
    for name in ("lo", "hi", "root"):
        match = re.search(
            rf"def {name}: \[256\]f32 = \[(?P<body>.*?)\n  \]",
            module,
            re.DOTALL,
        )
        if match is None:
            raise SystemExit(f"cannot locate f32 cache array {name}")
        tokens = [item.strip() for item in match.group("body").split(",")]
        if len(tokens) != ROOT_COUNT or any(not item.endswith("f32") for item in tokens):
            raise SystemExit(f"f32 cache array {name} must contain exactly 256 literals")
        try:
            values = [float.fromhex(item.removesuffix("f32")) for item in tokens]
        except ValueError as error:
            raise SystemExit(f"malformed f32 cache array {name}") from error
        if any(f32_from_bits(f32_bits(value)) != value for value in values):
            raise SystemExit(f"non-binary32 value in f32 cache array {name}")
        arrays[name] = values
    return arrays


def check_public_cache_path(source: str) -> None:
    marker = "module f32_impl = {"
    if source.count(marker) != 1:
        raise SystemExit("cannot locate unique f32 implementation module")
    module = source.split(marker, 1)[1]
    required = (
        "let root = f32_cache.root[i]",
        "lo = f32_cache.lo[i]",
        "hi = f32_cache.hi[i]",
        "residual = f32.abs (j1_finite root)",
        "converged = true",
    )
    if any(module.count(fragment) != 1 for fragment in required):
        raise SystemExit("public f32 cached-root source path drifted")


def load_rows(data: bytes) -> list[dict[str, Any]]:
    try:
        rows = [json.loads(line) for line in data.decode().splitlines()]
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SystemExit("malformed root-envelope certificate ledger") from error
    if len(rows) != ROOT_COUNT:
        raise SystemExit(f"expected exactly 256 root-envelope rows, got {len(rows)}")
    if [row.get("index") for row in rows] != list(range(1, ROOT_COUNT + 1)):
        raise SystemExit("root-envelope rows must cover ordered indices 1..256")
    return rows


def verify_rows(
    data: bytes, cache_text: str, implementation_text: str
) -> dict[str, Any]:
    mp.mp.dps = 120
    arrays = parse_cache_arrays(cache_text)
    check_public_cache_path(implementation_text)
    rows = load_rows(data)
    declared_residual = float.fromhex(DECLARED_TRUE_RESIDUAL_ENVELOPE_HEX)
    maximum_upper = -1.0
    maximum_value = mp.mpf("-1")
    worst_upper_index = 0
    worst_value_index = 0

    for expected_index, row in enumerate(rows, start=1):
        if set(row) != EXPECTED_FIELDS:
            raise SystemExit(f"root-envelope row fields drifted at index {expected_index}")
        if row["kind"] != "f32_cached_j1_root_envelope":
            raise SystemExit(f"unexpected root-envelope kind at index {expected_index}")
        if row["index"] != expected_index or row["bisections"] != 192:
            raise SystemExit(f"root-envelope coverage drifted at index {expected_index}")
        if row["certified_unique_f32_rounding"] is not True:
            raise SystemExit(f"missing unique-rounding certificate at index {expected_index}")
        if row["certified_true_residual"] is not True:
            raise SystemExit(f"missing true-residual certificate at index {expected_index}")

        certified_bits = parse_bits(row["root_f32_bits"])
        root_hex = nonnegative_hex(row["root_f32_hex"], "root")
        if f32_bits(root_hex) != certified_bits:
            raise SystemExit(f"root hexadecimal/bits mismatch at index {expected_index}")
        cached_root = arrays["root"][expected_index - 1]
        if f32_bits(cached_root) != certified_bits:
            raise SystemExit(f"cached root escaped Arb-certified bits at index {expected_index}")

        reference = mp.besseljzero(1, expected_index)
        independently_rounded = f32_bits(float(reference))
        if independently_rounded != certified_bits:
            raise SystemExit(f"mpmath disagrees with root rounding at index {expected_index}")
        cache_lo = mp.mpf(arrays["lo"][expected_index - 1])
        cache_hi = mp.mpf(arrays["hi"][expected_index - 1])
        if not cache_lo <= reference <= cache_hi:
            raise SystemExit(f"mathematical root escaped cached bracket at index {expected_index}")
        if not cache_lo <= mp.mpf(cached_root) <= cache_hi:
            raise SystemExit(f"cached root escaped cached bracket at index {expected_index}")

        residual = abs(mp.besselj(1, mp.mpf(cached_root)))
        ball_lo, ball_hi = parse_ball(row["true_residual_ball"])
        if ball_lo < 0 or not ball_lo <= residual <= ball_hi:
            raise SystemExit(f"mpmath residual escaped Arb ball at index {expected_index}")
        residual_upper = nonnegative_hex(
            row["true_residual_upper_hex"], "true residual upper bound"
        )
        if mp.mpf(residual_upper) < ball_hi or mp.mpf(residual_upper) < residual:
            raise SystemExit(f"residual escaped hexadecimal upper bound at index {expected_index}")
        if residual_upper > declared_residual:
            raise SystemExit(
                f"root {expected_index} escaped declared true-residual envelope "
                f"{DECLARED_TRUE_RESIDUAL_ENVELOPE_HEX}"
            )
        if residual_upper > maximum_upper:
            maximum_upper = residual_upper
            worst_upper_index = expected_index
        if residual > maximum_value:
            maximum_value = residual
            worst_value_index = expected_index

    return {
        "root_count": len(rows),
        "maximum_ulp_error": 0,
        "declared_true_residual_abs_upper_hex": DECLARED_TRUE_RESIDUAL_ENVELOPE_HEX,
        "certified_maximum_true_residual_upper_hex": maximum_upper.hex(),
        "certified_maximum_true_residual_upper_index": worst_upper_index,
        "independent_maximum_true_residual_decimal": mp.nstr(
            maximum_value, 40, min_fixed=0, max_fixed=0
        ),
        "independent_maximum_true_residual_index": worst_value_index,
    }


def generate() -> dict[str, Any]:
    implementation_sha = sha256(IMPLEMENTATION)
    if implementation_sha != EXPECTED_IMPLEMENTATION_SHA256:
        raise SystemExit("implementation SHA drifted; re-audit root evidence scope")
    certificate_bytes = CERTIFICATES.read_bytes()
    cache_text = CACHE.read_text()
    implementation_text = IMPLEMENTATION.read_text()
    results = verify_rows(certificate_bytes, cache_text, implementation_text)
    return {
        "schema_version": "futhark-bessel.f32-root-envelope.v1",
        "status": "SOURCE_CACHE_ROOT_ENVELOPE_CERTIFIED",
        "release_conformance": False,
        "scope": {
            "covered": (
                "all 256 binary32 root literals returned by the public cached "
                "positive_j1_root path; ULP distance is measured against the "
                "correctly rounded mathematical J1 root and residual means the "
                "independent mathematical value |J1(r_hat)|"
            ),
            "excluded": (
                "positive_j1_root_solved arithmetic and stopping logic, the "
                "implementation-reported approximate residual, f64 root "
                "envelopes, and C/WASM/WebGPU lowering or runtime conformance"
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
            "implementation": str(IMPLEMENTATION),
            "implementation_sha256": implementation_sha,
            "certificate_library": "FLINT/Arb 3.6.0 arb_hypgeom_bessel_j",
        },
        "envelopes": {
            "precision": "f32",
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
        "release_implications": {
            "f32_cached_root_ulp_and_mathematical_residual": "CERTIFIED",
            "f32_reported_residual": "BACKEND_CONFORMANCE_OPEN",
            "f64_root_envelope": "OPEN",
            "root_solver_arithmetic": "OPEN",
            "backend_lowering_equivalence": "OPEN",
            "overall_release_status": "INCOMPLETE",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--write", action="store_true")
    action.add_argument("--check", action="store_true")
    args = parser.parse_args()
    generated = json.dumps(generate(), indent=2, sort_keys=True) + "\n"
    if args.write:
        OUTPUT.write_text(generated)
        print(f"wrote {OUTPUT}")
        return
    if not OUTPUT.exists() or OUTPUT.read_text() != generated:
        raise SystemExit(
            "f32 root-envelope summary is stale; run "
            "scripts/root_envelope_proof.py --write"
        )
    print(
        "OK all 256 cached f32 roots are correctly rounded with certified "
        f"true residual <= {DECLARED_TRUE_RESIDUAL_ENVELOPE_HEX}; "
        "solver arithmetic and backend conformance remain OPEN"
    )


if __name__ == "__main__":
    main()
