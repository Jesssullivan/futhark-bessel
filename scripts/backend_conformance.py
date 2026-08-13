#!/usr/bin/env python3
# SPDX-License-Identifier: ISC
"""Run C/WASM numerical observations against independent Arb goldens."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import struct
import subprocess
from pathlib import Path
from typing import Any

import mpmath as mp

CERTIFICATES = Path("evidence/arb-certificates.jsonl")
BASELINE = Path("evidence/backend-observations.json")
PROGRAM = Path("tests/backend_conformance.fut")
FUTHARK_COMMIT = "8d6d12f0c31e133d7b5bd39c1254c541aa6ef70a"
NIXPKGS_REVISION = "2fcb964de67fcf60b43471c55d5d99e61a9ccb5a"
EMSCRIPTEN_VERSION = "6.0.5"
NODE_VERSION = "22.23.2"
ROOT_COUNT = 256


def command_output(command: list[str]) -> str:
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=300,
            env={**os.environ, "LC_ALL": "C", "TZ": "UTC"},
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        stderr = getattr(error, "stderr", None)
        detail = f"\n{stderr.strip()}" if isinstance(stderr, str) and stderr else ""
        raise SystemExit(f"backend command failed: {' '.join(command)}{detail}") from error
    return completed.stdout.strip()


def verify_toolchain() -> None:
    futhark_version = command_output(["futhark", "--version"])
    if "Futhark 0.27.0" not in futhark_version or FUTHARK_COMMIT not in futhark_version:
        raise SystemExit("unexpected Futhark compiler identity")
    emcc_version = command_output(["emcc", "--version"]).splitlines()[0]
    if EMSCRIPTEN_VERSION not in emcc_version:
        raise SystemExit(f"expected Emscripten {EMSCRIPTEN_VERSION}: {emcc_version}")
    node_version = command_output(["node", "--version"]).removeprefix("v")
    if node_version != NODE_VERSION:
        raise SystemExit(f"expected Node.js {NODE_VERSION}, got {node_version}")


def load_certificates() -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    rows = [json.loads(line) for line in CERTIFICATES.read_text().splitlines()]
    values = {
        precision: sorted(
            [
                row
                for row in rows
                if row["kind"] == "conformance_value"
                and row["precision"] == precision
            ],
            key=lambda row: row["index"],
        )
        for precision in ("f32", "f64")
    }
    roots = sorted(
        [row for row in rows if row["kind"] == "j1_root_bracket"],
        key=lambda row: row["index"],
    )
    for precision in ("f32", "f64"):
        if [row["index"] for row in values[precision]] != list(range(33)):
            raise SystemExit(f"incomplete {precision} conformance value certificates")
        if not all(row["certified_unique_rounding"] for row in values[precision]):
            raise SystemExit(f"uncertified {precision} golden rounding")
    if [row["index"] for row in roots] != list(range(1, ROOT_COUNT + 1)):
        raise SystemExit("root certificates must cover indices 1..256")
    if not all(row["certified_unique_rounding"] for row in roots):
        raise SystemExit("root goldens lack unique-rounding certificates")
    return values, roots


def futhark_array(values: list[int], suffix: str, width: int) -> str:
    digits = width // 4
    return "[" + ",".join(f"0x{value:0{digits}x}{suffix}" for value in values) + "]"


def parse_futhark_bits(output: str, suffix: str, width: int) -> list[int]:
    if not output.startswith("[") or not output.endswith("]"):
        raise SystemExit(f"unexpected Futhark output: {output[:200]!r}")
    inside = output[1:-1].strip()
    if not inside:
        return []
    token = re.compile(rf"(?:0x[0-9a-fA-F]+|[0-9]+){suffix}")
    parsed: list[int] = []
    for raw in inside.split(","):
        item = raw.strip()
        if not token.fullmatch(item):
            raise SystemExit(f"malformed Futhark bit token: {item!r}")
        number = item[: -len(suffix)]
        value = int(number, 16 if number.startswith("0x") else 10)
        if value >= 1 << width:
            raise SystemExit(f"Futhark output exceeds {width} bits: {item}")
        parsed.append(value)
    return parsed


def run_observation(
    backend: str,
    executable: Path,
    precision: str,
    value_rows: list[dict[str, Any]],
    roots: list[dict[str, Any]],
) -> dict[str, list[int]]:
    width = 32 if precision == "f32" else 64
    suffix = precision.replace("f", "u")
    x_bits = [int(row["x_bits"], 16) for row in value_rows]
    indices = [row["index"] for row in roots]
    expression = (
        f"observe_{precision} {futhark_array(x_bits, suffix, width)} "
        f"{futhark_array(indices, 'i32', 32)}"
    )
    output = command_output(
        [
            "futhark",
            "script",
            "--skip-compilation",
            str(executable),
            "--expression",
            expression,
        ]
    )
    bits = parse_futhark_bits(output, suffix, width)
    value_count = len(value_rows)
    expected_count = value_count * 2 + ROOT_COUNT * 2
    if len(bits) != expected_count:
        raise SystemExit(
            f"{backend}/{precision} returned {len(bits)} words; "
            f"expected {expected_count}"
        )
    return {
        "j0": bits[:value_count],
        "j1": bits[value_count : value_count * 2],
        "roots": bits[value_count * 2 : value_count * 2 + ROOT_COUNT],
        "residuals": bits[value_count * 2 + ROOT_COUNT :],
    }


def compile_backend(backend: str) -> Path:
    build = Path("build")
    build.mkdir(exist_ok=True)
    executable = build / f"backend-conformance-{backend}"
    command_output(
        [
            "futhark",
            backend,
            "--server",
            "--Werror",
            str(PROGRAM),
            "-o",
            str(executable),
        ]
    )
    return executable


def float_from_bits(bits: int, width: int) -> float:
    if width == 32:
        return struct.unpack(">f", struct.pack(">I", bits))[0]
    return struct.unpack(">d", struct.pack(">Q", bits))[0]


def ordered_bits(bits: int, width: int) -> int:
    sign = 1 << (width - 1)
    mask = (1 << width) - 1
    return (~bits & mask) if bits & sign else bits | sign


def ulp_distance(observed: int, reference: int, width: int) -> int:
    return abs(ordered_bits(observed, width) - ordered_bits(reference, width))


def value_metric(
    rows: list[dict[str, Any]],
    observed: list[int],
    function: str,
    domain: str,
    width: int,
) -> dict[str, Any]:
    selected = [index for index, row in enumerate(rows) if row["domain"] == domain]
    maximum_absolute = -1.0
    maximum_ulp = -1
    worst_absolute = None
    worst_ulp = None
    for index in selected:
        observed_bits = observed[index]
        reference_bits = int(rows[index][f"{function}_reference_bits"], 16)
        observed_value = float_from_bits(observed_bits, width)
        reference_value = float_from_bits(reference_bits, width)
        if not math.isfinite(observed_value):
            raise SystemExit(
                f"nonfinite {function} observation at {rows[index]['x_bits']}"
            )
        absolute = abs(observed_value - reference_value)
        ulps = ulp_distance(observed_bits, reference_bits, width)
        if absolute > maximum_absolute:
            maximum_absolute = absolute
            worst_absolute = rows[index]["x_bits"]
        if ulps > maximum_ulp:
            maximum_ulp = ulps
            worst_ulp = rows[index]["x_bits"]
    return {
        "sample_count": len(selected),
        "max_absolute_error_against_rounded_reference_hex": maximum_absolute.hex(),
        "max_ulp_error": maximum_ulp,
        "worst_absolute_error_x_bits": worst_absolute,
        "worst_ulp_error_x_bits": worst_ulp,
    }


def root_metric(
    roots: list[dict[str, Any]],
    observed_roots: list[int],
    reported_residuals: list[int],
    precision: str,
    width: int,
) -> dict[str, Any]:
    maximum_absolute = -1.0
    maximum_ulp = -1
    maximum_reported_residual = -1.0
    maximum_independent_residual = mp.mpf("-1")
    worst_absolute = 0
    worst_ulp = 0
    worst_reported_residual = 0
    worst_independent_residual = 0
    reference_field = f"root_{precision}_reference_bits"
    for row, observed_bits, residual_bits in zip(
        roots, observed_roots, reported_residuals, strict=True
    ):
        observed = float_from_bits(observed_bits, width)
        reference_bits = int(row[reference_field], 16)
        reference = float_from_bits(reference_bits, width)
        reported_residual = float_from_bits(residual_bits, width)
        if not math.isfinite(observed) or not math.isfinite(reported_residual):
            raise SystemExit(f"nonfinite root observation at index {row['index']}")
        absolute = abs(observed - reference)
        ulps = ulp_distance(observed_bits, reference_bits, width)
        independent_residual = abs(mp.besselj(1, mp.mpf(observed)))
        if absolute > maximum_absolute:
            maximum_absolute = absolute
            worst_absolute = row["index"]
        if ulps > maximum_ulp:
            maximum_ulp = ulps
            worst_ulp = row["index"]
        if reported_residual > maximum_reported_residual:
            maximum_reported_residual = reported_residual
            worst_reported_residual = row["index"]
        if independent_residual > maximum_independent_residual:
            maximum_independent_residual = independent_residual
            worst_independent_residual = row["index"]
    return {
        "sample_count": len(roots),
        "max_absolute_error_against_rounded_reference_hex": maximum_absolute.hex(),
        "max_ulp_error": maximum_ulp,
        "max_reported_residual_hex": maximum_reported_residual.hex(),
        "max_independent_residual_decimal": mp.nstr(
            maximum_independent_residual, 30, min_fixed=0, max_fixed=0
        ),
        "worst_absolute_error_index": worst_absolute,
        "worst_ulp_error_index": worst_ulp,
        "worst_reported_residual_index": worst_reported_residual,
        "worst_independent_residual_index": worst_independent_residual,
    }


def backend_metrics(
    rows: list[dict[str, Any]],
    roots: list[dict[str, Any]],
    raw: dict[str, list[int]],
    precision: str,
) -> dict[str, Any]:
    width = 32 if precision == "f32" else 64
    return {
        "status": "OBSERVED_SAMPLES_NOT_RELEASE_CONFORMANCE",
        "values": {
            domain: {
                function: value_metric(rows, raw[function], function, domain, width)
                for function in ("j0", "j1")
            }
            for domain in ("series", "asymptotic")
        },
        "roots": root_metric(
            roots, raw["roots"], raw["residuals"], precision, width
        ),
    }


def mismatch_counts(c: dict[str, list[int]], wasm: dict[str, list[int]]) -> dict[str, int]:
    return {
        field: sum(left != right for left, right in zip(c[field], wasm[field], strict=True))
        for field in ("j0", "j1", "roots", "residuals")
    }


def generate() -> dict[str, Any]:
    verify_toolchain()
    mp.mp.dps = 100
    values, roots = load_certificates()
    raw: dict[str, dict[str, dict[str, list[int]]]] = {}
    observations: dict[str, dict[str, dict[str, Any]]] = {}
    parity: dict[str, dict[str, int]] = {}
    executables = {backend: compile_backend(backend) for backend in ("c", "wasm")}
    for precision in ("f32", "f64"):
        raw[precision] = {}
        observations[precision] = {}
        for backend in ("c", "wasm"):
            raw[precision][backend] = run_observation(
                backend, executables[backend], precision, values[precision], roots
            )
            observations[precision][backend] = backend_metrics(
                values[precision], roots, raw[precision][backend], precision
            )
        parity[precision] = mismatch_counts(
            raw[precision]["c"], raw[precision]["wasm"]
        )
    authority_rows = [*values["f32"], *values["f64"], *roots]
    authority_bytes = json.dumps(
        authority_rows, sort_keys=True, separators=(",", ":")
    ).encode()
    return {
        "schema_version": "futhark-bessel.backend-observations.v1",
        "status": "OBSERVED_BASELINE_NOT_RELEASE_CONFORMANCE",
        "release_gate": "BLOCKED_PENDING_DECLARED_ENVELOPES_AND_COMPLETE_CERTIFICATION",
        "toolchain": {
            "nixpkgs_revision": NIXPKGS_REVISION,
            "futhark_version": "0.27.0 prerelease",
            "futhark_git_commit": FUTHARK_COMMIT,
            "emscripten_version": EMSCRIPTEN_VERSION,
            "node_version": NODE_VERSION,
        },
        "sample_authority": {
            "source": str(CERTIFICATES),
            "sha256": hashlib.sha256(authority_bytes).hexdigest(),
            "f32_value_samples": len(values["f32"]),
            "f64_value_samples": len(values["f64"]),
            "root_samples_per_precision": len(roots),
            "certifier": "FLINT/Arb 3.6.0 unique IEEE rounding",
        },
        "observations": observations,
        "backend_bit_parity": parity,
        "webgpu": {
            "status": "COMPILED_NOT_EXECUTED",
            "release_conformance": False,
            "reason": "The pinned headless CI runner exposes no ratified WebGPU adapter/runtime.",
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
        BASELINE.write_text(generated)
        print(f"wrote {BASELINE}")
        return
    if not BASELINE.exists() or BASELINE.read_text() != generated:
        raise SystemExit(
            "backend observation baseline is stale; run "
            "scripts/backend_conformance.py --write"
        )
    recorded = json.loads(generated)
    parity = recorded["backend_bit_parity"]
    print(
        "OK C/WASM runtime observations match the Arb-golden baseline; "
        f"bit mismatches f32={sum(parity['f32'].values())} "
        f"f64={sum(parity['f64'].values())}; release envelopes remain OPEN"
    )


if __name__ == "__main__":
    main()
