#!/usr/bin/env python3
# SPDX-License-Identifier: ISC
"""Verify and summarize whole-domain real-arithmetic bound certificates."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from fractions import Fraction
from pathlib import Path
from typing import Any

import mpmath as mp

CERTIFICATES = Path("evidence/real-approximation-certificates.jsonl")
SUMMARY = Path("evidence/real-approximation-bounds.json")
IMPLEMENTATION = Path(
    "lib/github.com/Jesssullivan/futhark-bessel/bessel_internal.fut"
)
DOMAIN_MAX = Fraction(1024)
N_ABS_BOUND = 653

CONFIGS: dict[str, dict[str, Any]] = {
    "f32": {
        "switch": Fraction(6),
        "series_last": 48,
        "hankel_last": 7,
        "sin_first_omitted": 11,
        "cos_first_omitted": 12,
        "two_over_pi": "0x1.45f306p-1",
        "pio2": ("0x1.9218p+0", "0x1.ed511p-14", "0x1.68c234p-39"),
        "pi_used": "0x1.921fb6p+1",
        "offsets": ("0x1.921fb6p-1", "0x1.2d97c8p+1"),
    },
    "f64": {
        "switch": Fraction(12),
        "series_last": 96,
        "hankel_last": 12,
        "sin_first_omitted": 15,
        "cos_first_omitted": 14,
        "two_over_pi": "0x1.45f306dc9c883p-1",
        "pio2": (
            "0x1.921fb54000000p+0",
            "0x1.10b4611a62633p-30",
            "0x1.45c06e0e68948p-86",
        ),
        "pi_used": "0x1.921fb54442d18p+1",
        "offsets": ("0x1.921fb54442d18p-1", "0x1.2d97c7f3321d2p+1"),
    },
}


def function_body(module: str, function: str) -> str:
    match = re.search(
        rf"^  def {re.escape(function)}\b.*?(?=^  (?:def|type)\b|^}})",
        module,
        flags=re.MULTILINE | re.DOTALL,
    )
    if match is None:
        raise SystemExit(f"cannot locate implementation function {function}")
    return match.group(0)


def verify_source_contract() -> str:
    source = IMPLEMENTATION.read_text()
    module_match = re.search(
        r"module f64_impl = \{(?P<f64>.*?)^}\n\nmodule f32_impl = \{(?P<f32>.*?)^}\n?",
        source,
        flags=re.MULTILINE | re.DOTALL,
    )
    if module_match is None:
        raise SystemExit("cannot locate f32/f64 implementation modules")
    expected = {
        "f32": {
            "series_loop": "for k < 48 do",
            "hankel_loop": "for k < 7 do",
            "switch": "if y <= 6.0",
            "sin_last": "z / 362880.0",
            "cos_last": "z * (-1.0 / 3628800.0)",
            "constants": (
                "0x1.45f3060000000p-1f32",
                "0x1.9218000000000p+0f32",
                "0x1.ed51100000000p-14f32",
                "0x1.68c2340000000p-39f32",
                "0x1.921fb60000000p+1f32",
                "0x1.921fb60000000p-1f32",
                "0x1.2d97c80000000p+1f32",
            ),
        },
        "f64": {
            "series_loop": "for k < 96 do",
            "hankel_loop": "for k < 12 do",
            "switch": "if y <= 12.0",
            "sin_last": "z / 6227020800.0",
            "cos_last": "z / 479001600.0",
            "constants": (
                "0x1.45f306dc9c883p-1",
                "0x1.921fb54000000p+0",
                "0x1.10b4611a62633p-30",
                "0x1.45c06e0e68948p-86",
                "0x1.921fb54442d18p+1",
                "0x1.921fb54442d18p-1",
                "0x1.2d97c7f3321d2p+1",
            ),
        },
    }
    for precision in ("f32", "f64"):
        module = module_match.group(precision)
        contract = expected[precision]
        for function in ("j0_series", "j1_series"):
            if contract["series_loop"] not in function_body(module, function):
                raise SystemExit(f"{precision} {function} term count drifted")
        if contract["hankel_loop"] not in function_body(module, "hankel_sums"):
            raise SystemExit(f"{precision} Hankel term count drifted")
        sincos = function_body(module, "sincos_reduced")
        if contract["sin_last"] not in sincos or contract["cos_last"] not in sincos:
            raise SystemExit(f"{precision} trigonometric Taylor degree drifted")
        for function in ("j0_finite", "j1_finite"):
            if contract["switch"] not in function_body(module, function):
                raise SystemExit(f"{precision} {function} switch drifted")
        for constant in contract["constants"]:
            if constant not in module:
                raise SystemExit(f"{precision} certified constant drifted: {constant}")
        for function in ("j0_checked", "j1_checked"):
            if "f64.abs x > 1024.0" not in function_body(
                module, function
            ) and "f32.abs x > 1024.0" not in function_body(module, function):
                raise SystemExit(f"{precision} checked domain drifted")
    return hashlib.sha256(source.encode()).hexdigest()


def exact_hex(text: str) -> Fraction:
    value = float.fromhex(text)
    if not math.isfinite(value):
        raise SystemExit(f"nonfinite hexadecimal certificate value: {text}")
    return Fraction(*value.as_integer_ratio())


def mpq(value: Fraction) -> mp.mpf:
    return mp.mpf(value.numerator) / value.denominator


def recorded(text: str) -> mp.mpf:
    return mpq(exact_hex(text))


def close_upper(text: str, value: mp.mpf, label: str) -> None:
    upper = recorded(text)
    slack = mp.mpf("1e-70") * max(mp.mpf(1), abs(value))
    if upper + slack < value:
        raise SystemExit(f"{label} is not an outward upper bound: {text} < {value}")
    if value != 0 and upper > value * mp.mpf("1.000000000001"):
        raise SystemExit(f"{label} is unexpectedly loose: {text} versus {value}")


def interval_contains(row: dict[str, Any], prefix: str, value: mp.mpf) -> None:
    lo = recorded(row[f"{prefix}_lo_hex"])
    hi = recorded(row[f"{prefix}_hi_hex"])
    if lo > hi or not lo <= value <= hi:
        raise SystemExit(f"{prefix} interval does not contain its exact value: {row}")


def coefficient(order: int, m: int) -> mp.mpf:
    value = mp.mpf(1)
    for k in range(1, m + 1):
        value *= mp.mpf(4 * order * order - (2 * k - 1) ** 2) / (8 * k)
    return value


def first_after_with_parity(last: int, parity: int) -> int:
    value = last + 1
    return value if value % 2 == parity else value + 1


def expected_components(precision: str, order: int) -> dict[str, mp.mpf | int]:
    cfg = CONFIGS[precision]
    switch = mpq(cfg["switch"])
    omitted = cfg["series_last"] + 1
    z = switch**2 / 4
    series = z**omitted / (mp.factorial(omitted) * mp.factorial(omitted + order))
    if order == 1:
        series *= switch / 2
    ratio = z / ((omitted + 1) * (omitted + 1 + order))

    first_even = first_after_with_parity(cfg["hankel_last"], 0)
    first_odd = first_after_with_parity(cfg["hankel_last"], 1)
    p_remainder = abs(coefficient(order, first_even)) / switch**first_even
    q_remainder = abs(coefficient(order, first_odd)) / switch**first_odd
    p_abs = mp.fsum(
        abs(coefficient(order, m)) / switch**m
        for m in range(0, cfg["hankel_last"] + 1, 2)
    )
    q_abs = mp.fsum(
        abs(coefficient(order, m)) / switch**m
        for m in range(1, cfg["hankel_last"] + 1, 2)
    )

    c = mpq(exact_hex(cfg["two_over_pi"]))
    split = mp.fsum(mpq(exact_hex(item)) for item in cfg["pio2"])
    offset = mpq(exact_hex(cfg["offsets"][order]))
    true_offset = (2 * order + 1) * mp.pi / 4
    phase_error = abs(true_offset - offset) + N_ABS_BOUND * abs(mp.pi / 2 - split)
    reciprocal = 1 / c
    radius = mp.mpf("0.5") * reciprocal + N_ABS_BOUND * abs(reciprocal - split)
    sin_remainder = radius ** cfg["sin_first_omitted"] / mp.factorial(
        cfg["sin_first_omitted"]
    )
    cos_remainder = radius ** cfg["cos_first_omitted"] / mp.factorial(
        cfg["cos_first_omitted"]
    )
    sin_error = phase_error + sin_remainder
    cos_error = phase_error + cos_remainder
    prefactor = mp.sqrt(2 / (mp.pi * switch))
    prefactor_used = mp.sqrt(
        2 / (mpq(exact_hex(cfg["pi_used"])) * switch)
    )
    prefactor_error = abs(prefactor_used - prefactor)
    hankel = prefactor * (p_remainder + q_remainder)
    total = (
        hankel
        + prefactor_error
        * ((1 + cos_error) * p_abs + (1 + sin_error) * q_abs)
        + prefactor * (cos_error * p_abs + sin_error * q_abs)
    )
    n_expression = (mpq(DOMAIN_MAX) - offset) * c + mp.mpf("0.5")
    return {
        "series": series,
        "ratio": ratio,
        "first_even": first_even,
        "first_odd": first_odd,
        "p_remainder": p_remainder,
        "q_remainder": q_remainder,
        "p_abs": p_abs,
        "q_abs": q_abs,
        "phase_error": phase_error,
        "radius": radius,
        "sin_error": sin_error,
        "cos_error": cos_error,
        "prefactor_error": prefactor_error,
        "hankel": hankel,
        "total": total,
        "n_expression": n_expression,
    }


def nearest_integer(value: Fraction) -> int:
    floor = value.numerator // value.denominator
    remainder = value - floor
    if remainder < Fraction(1, 2):
        return floor
    if remainder > Fraction(1, 2):
        return floor + 1
    return floor if floor % 2 == 0 else floor + 1


def mp_series(x: mp.mpf, order: int, last: int) -> mp.mpf:
    z = -(x * x) / 4
    term = mp.mpf(1) if order == 0 else x / 2
    total = term
    for k in range(last):
        term *= z / ((k + 1) * (k + 1 + order))
        total += term
    return total


def mp_taylor(x: mp.mpf, sine: bool, first_omitted: int) -> mp.mpf:
    start = 1 if sine else 0
    return mp.fsum(
        (-1) ** ((degree - start) // 2) * x**degree / mp.factorial(degree)
        for degree in range(start, first_omitted, 2)
    )


def mp_asymptotic_at_switch(precision: str, order: int) -> mp.mpf:
    cfg = CONFIGS[precision]
    x_fraction = cfg["switch"]
    offset_fraction = exact_hex(cfg["offsets"][order])
    c_fraction = exact_hex(cfg["two_over_pi"])
    n = nearest_integer((x_fraction - offset_fraction) * c_fraction)
    x = mpq(x_fraction)
    phase = x - mpq(offset_fraction)
    split = mp.fsum(mpq(exact_hex(item)) for item in cfg["pio2"])
    reduced = phase - n * split
    sin_reduced = mp_taylor(reduced, True, cfg["sin_first_omitted"])
    cos_reduced = mp_taylor(reduced, False, cfg["cos_first_omitted"])
    quadrant = n % 4
    if quadrant == 0:
        sine, cosine = sin_reduced, cos_reduced
    elif quadrant == 1:
        sine, cosine = cos_reduced, -sin_reduced
    elif quadrant == 2:
        sine, cosine = -sin_reduced, -cos_reduced
    else:
        sine, cosine = -cos_reduced, sin_reduced
    p = mp.mpf(1)
    q = mp.mpf(0)
    invpow = mp.mpf(1)
    for m in range(1, cfg["hankel_last"] + 1):
        invpow /= x
        term = (-1) ** (m // 2) * coefficient(order, m) * invpow
        if m % 2 == 0:
            p += term
        else:
            q += term
    prefactor = mp.sqrt(2 / (mpq(exact_hex(cfg["pi_used"])) * x))
    return prefactor * (cosine * p - sine * q)


def verify_bound_rows(
    rows: list[dict[str, Any]], precision: str, order: int
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    def unique(kind: str) -> dict[str, Any]:
        selected = [
            row
            for row in rows
            if row["kind"] == kind
            and row.get("precision") == precision
            and row.get("order") == order
        ]
        if len(selected) != 1:
            raise SystemExit(f"expected one {precision}/J{order} {kind} row")
        return selected[0]

    cfg = CONFIGS[precision]
    expected = expected_components(precision, order)
    series = unique("series_bound")
    asymptotic = unique("asymptotic_bound")
    switch = unique("switch_certificate")
    expected_series_fields = {
        "kind",
        "precision",
        "order",
        "domain_abs_x_lo_hex",
        "domain_abs_x_hi_hex",
        "last_retained_index",
        "first_omitted_index",
        "tail_ratio_abs_upper_hex",
        "absolute_error_upper_hex",
        "theorem",
    }
    if set(series) != expected_series_fields:
        raise SystemExit(f"malformed series certificate: {series}")
    if (
        exact_hex(series["domain_abs_x_lo_hex"]) != 0
        or exact_hex(series["domain_abs_x_hi_hex"]) != cfg["switch"]
        or series["last_retained_index"] != cfg["series_last"]
        or series["first_omitted_index"] != cfg["series_last"] + 1
        or series["theorem"] != "alternating_first_omitted_term"
    ):
        raise SystemExit(f"incorrect series contract: {series}")
    close_upper(series["tail_ratio_abs_upper_hex"], expected["ratio"], "tail ratio")
    if recorded(series["tail_ratio_abs_upper_hex"]) >= 1:
        raise SystemExit(f"series tail is not certified decreasing: {series}")
    close_upper(
        series["absolute_error_upper_hex"], expected["series"], "series error"
    )

    expected_asymptotic_fields = {
        "kind",
        "precision",
        "order",
        "domain_abs_x_lo_hex",
        "domain_abs_x_hi_hex",
        "p_first_omitted_index",
        "q_first_omitted_index",
        "p_ell",
        "q_ell",
        "dlmf_real_argument_conditions_certified",
        "p_remainder_abs_upper_hex",
        "q_remainder_abs_upper_hex",
        "hankel_truncation_abs_upper_hex",
        "phase_reconstruction_abs_upper_hex",
        "reduced_argument_abs_upper_hex",
        "sin_total_abs_upper_hex",
        "cos_total_abs_upper_hex",
        "prefactor_abs_error_upper_hex",
        "p_sum_abs_upper_hex",
        "q_sum_abs_upper_hex",
        "n_magnitude_expression_upper_hex",
        "n_abs_bound",
        "absolute_error_upper_hex",
        "theorem",
    }
    if set(asymptotic) != expected_asymptotic_fields:
        raise SystemExit(f"malformed asymptotic certificate: {asymptotic}")
    if (
        exact_hex(asymptotic["domain_abs_x_lo_hex"]) != cfg["switch"]
        or exact_hex(asymptotic["domain_abs_x_hi_hex"]) != DOMAIN_MAX
        or asymptotic["p_first_omitted_index"] != expected["first_even"]
        or asymptotic["q_first_omitted_index"] != expected["first_odd"]
        or asymptotic["p_ell"] != expected["first_even"] // 2
        or asymptotic["q_ell"] != (expected["first_odd"] - 1) // 2
        or not asymptotic["dlmf_real_argument_conditions_certified"]
        or asymptotic["n_abs_bound"] != N_ABS_BOUND
        or asymptotic["theorem"]
        != "DLMF_10.17.iii_plus_compositional_phase_bound"
    ):
        raise SystemExit(f"incorrect asymptotic contract: {asymptotic}")
    fields = {
        "p_remainder_abs_upper_hex": "p_remainder",
        "q_remainder_abs_upper_hex": "q_remainder",
        "hankel_truncation_abs_upper_hex": "hankel",
        "phase_reconstruction_abs_upper_hex": "phase_error",
        "reduced_argument_abs_upper_hex": "radius",
        "sin_total_abs_upper_hex": "sin_error",
        "cos_total_abs_upper_hex": "cos_error",
        "prefactor_abs_error_upper_hex": "prefactor_error",
        "p_sum_abs_upper_hex": "p_abs",
        "q_sum_abs_upper_hex": "q_abs",
        "n_magnitude_expression_upper_hex": "n_expression",
        "absolute_error_upper_hex": "total",
    }
    for field, component in fields.items():
        close_upper(asymptotic[field], expected[component], field)
    p_ell = asymptotic["p_ell"]
    q_ell = asymptotic["q_ell"]
    if p_ell < max(mp.mpf(order) / 2 - mp.mpf(1) / 4, 1):
        raise SystemExit("DLMF P-remainder condition is not satisfied")
    if q_ell < max(mp.mpf(order) / 2 - mp.mpf(3) / 4, 1):
        raise SystemExit("DLMF Q-remainder condition is not satisfied")
    if expected["radius"] >= mp.pi / 4 + mp.mpf("0.0001"):
        raise SystemExit("Taylor remainder radius escaped its declared theorem")
    if recorded(asymptotic["n_magnitude_expression_upper_hex"]) >= N_ABS_BOUND:
        raise SystemExit("global reduction index magnitude bound was not proved")

    expected_switch_fields = {
        "kind",
        "precision",
        "order",
        "x_hex",
        "active_branch",
        "series_actual_abs_upper_hex",
        "series_theorem_abs_upper_hex",
        "asymptotic_actual_abs_upper_hex",
        "asymptotic_theorem_abs_upper_hex",
        "branch_gap_abs_upper_hex",
        "certifier",
    }
    if set(switch) != expected_switch_fields:
        raise SystemExit(f"malformed switch certificate: {switch}")
    if (
        exact_hex(switch["x_hex"]) != cfg["switch"]
        or switch["active_branch"] != "series"
        or switch["certifier"] != "FLINT/Arb 3.6.0"
        or switch["series_theorem_abs_upper_hex"]
        != series["absolute_error_upper_hex"]
        or switch["asymptotic_theorem_abs_upper_hex"]
        != asymptotic["absolute_error_upper_hex"]
    ):
        raise SystemExit(f"incorrect switch contract: {switch}")
    x = mpq(cfg["switch"])
    reference = mp.besselj(order, x)
    exact_series_value = mp_series(x, order, cfg["series_last"])
    exact_asymptotic_value = mp_asymptotic_at_switch(precision, order)
    close_upper(
        switch["series_actual_abs_upper_hex"],
        abs(exact_series_value - reference),
        "switch series Arb observation",
    )
    close_upper(
        switch["asymptotic_actual_abs_upper_hex"],
        abs(exact_asymptotic_value - reference),
        "switch asymptotic Arb observation",
    )
    close_upper(
        switch["branch_gap_abs_upper_hex"],
        abs(exact_series_value - exact_asymptotic_value),
        "switch branch gap",
    )
    if recorded(switch["series_actual_abs_upper_hex"]) > recorded(
        switch["series_theorem_abs_upper_hex"]
    ):
        raise SystemExit("series theorem does not cover its switch observation")
    if recorded(switch["asymptotic_actual_abs_upper_hex"]) > recorded(
        switch["asymptotic_theorem_abs_upper_hex"]
    ):
        raise SystemExit("asymptotic theorem does not cover its switch observation")
    return series, asymptotic, switch


def verify_partition(
    rows: list[dict[str, Any]], precision: str, order: int, radius: mp.mpf
) -> dict[str, Any]:
    cfg = CONFIGS[precision]
    selected = [
        row
        for row in rows
        if row.get("precision") == precision and row.get("order") == order
    ]
    boundaries = [row for row in selected if row["kind"] == "range_boundary"]
    endpoints = [row for row in selected if row["kind"] == "range_endpoint"]
    partitions = [row for row in selected if row["kind"] == "range_partition"]
    if len(partitions) != 1:
        raise SystemExit(f"expected one {precision}/J{order} range partition")
    partition = partitions[0]
    c = exact_hex(cfg["two_over_pi"])
    offset = exact_hex(cfg["offsets"][order])
    split = sum((exact_hex(item) for item in cfg["pio2"]), Fraction())
    expected_ns = [
        n
        for n in range(-2048, 2049)
        if cfg["switch"] < offset + Fraction(2 * n + 1, 2) / c < DOMAIN_MAX
    ]
    if [row["left_n"] for row in boundaries] != expected_ns:
        raise SystemExit(f"incomplete or unordered {precision}/J{order} boundaries")
    boundary_fields = {
        "kind",
        "precision",
        "order",
        "left_n",
        "right_n",
        "x_lo_hex",
        "x_hi_hex",
        "left_reduced_lo_hex",
        "left_reduced_hi_hex",
        "right_reduced_lo_hex",
        "right_reduced_hi_hex",
        "both_branches_certified",
    }
    maximum_endpoint = mp.mpf(0)
    for row, n in zip(boundaries, expected_ns, strict=True):
        if (
            set(row) != boundary_fields
            or row["right_n"] != n + 1
            or not row["both_branches_certified"]
        ):
            raise SystemExit(f"malformed range boundary: {row}")
        phase = Fraction(2 * n + 1, 2) / c
        x = offset + phase
        left_reduced = phase - n * split
        right_reduced = phase - (n + 1) * split
        interval_contains(row, "x", mpq(x))
        interval_contains(row, "left_reduced", mpq(left_reduced))
        interval_contains(row, "right_reduced", mpq(right_reduced))
        maximum_endpoint = max(
            maximum_endpoint, abs(mpq(left_reduced)), abs(mpq(right_reduced))
        )
    endpoint_fields = {
        "kind",
        "precision",
        "order",
        "position",
        "x_hex",
        "selected_n",
        "reduced_lo_hex",
        "reduced_hi_hex",
        "reduced_abs_upper_hex",
    }
    endpoint_by_position = {row["position"]: row for row in endpoints}
    if set(endpoint_by_position) != {"switch", "domain_max"}:
        raise SystemExit(f"range endpoints incomplete: {endpoints}")
    for position, x in (("switch", cfg["switch"]), ("domain_max", DOMAIN_MAX)):
        row = endpoint_by_position[position]
        n = nearest_integer((x - offset) * c)
        remainder = x - offset - n * split
        if (
            set(row) != endpoint_fields
            or exact_hex(row["x_hex"]) != x
            or row["selected_n"] != n
        ):
            raise SystemExit(f"malformed range endpoint: {row}")
        interval_contains(row, "reduced", mpq(remainder))
        close_upper(
            row["reduced_abs_upper_hex"],
            abs(mpq(remainder)),
            "endpoint reduced magnitude",
        )
        maximum_endpoint = max(maximum_endpoint, abs(mpq(remainder)))
    partition_fields = {
        "kind",
        "precision",
        "order",
        "domain_abs_x_lo_hex",
        "domain_abs_x_hi_hex",
        "boundary_count",
        "first_boundary_left_n",
        "last_boundary_left_n",
        "partition_endpoint_abs_upper_hex",
        "analytic_reduced_abs_upper_hex",
        "coverage",
    }
    if (
        set(partition) != partition_fields
        or exact_hex(partition["domain_abs_x_lo_hex"]) != cfg["switch"]
        or exact_hex(partition["domain_abs_x_hi_hex"]) != DOMAIN_MAX
        or partition["boundary_count"] != len(expected_ns)
        or partition["first_boundary_left_n"] != expected_ns[0]
        or partition["last_boundary_left_n"] != expected_ns[-1]
        or partition["coverage"]
        != "all_rounding_cells_and_both_tie_branches"
    ):
        raise SystemExit(f"malformed range partition: {partition}")
    close_upper(
        partition["partition_endpoint_abs_upper_hex"],
        maximum_endpoint,
        "partition endpoint maximum",
    )
    close_upper(
        partition["analytic_reduced_abs_upper_hex"],
        radius,
        "analytic reduced radius",
    )
    if recorded(partition["partition_endpoint_abs_upper_hex"]) > recorded(
        partition["analytic_reduced_abs_upper_hex"]
    ):
        raise SystemExit("analytic radius does not cover the exhaustive partition")
    return partition


def generate_summary(raw: bytes) -> dict[str, Any]:
    implementation_sha256 = verify_source_contract()
    try:
        rows = [json.loads(line) for line in raw.decode().splitlines()]
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SystemExit(f"malformed approximation certificate ledger: {error}") from error
    if len(rows) != 2608:
        raise SystemExit(f"expected 2608 approximation certificate rows, got {len(rows)}")
    allowed_kinds = {
        "series_bound",
        "asymptotic_bound",
        "switch_certificate",
        "range_boundary",
        "range_endpoint",
        "range_partition",
    }
    if any(row.get("kind") not in allowed_kinds for row in rows):
        raise SystemExit("unexpected approximation certificate kind")
    bounds: dict[str, dict[str, Any]] = {}
    partitions: dict[str, dict[str, Any]] = {}
    for precision in ("f32", "f64"):
        bounds[precision] = {}
        partitions[precision] = {}
        for order in (0, 1):
            series, asymptotic, switch = verify_bound_rows(
                rows, precision, order
            )
            expected = expected_components(precision, order)
            partition = verify_partition(
                rows, precision, order, expected["radius"]
            )
            name = f"j{order}"
            bounds[precision][name] = {
                "series_absolute_error_upper_hex": series[
                    "absolute_error_upper_hex"
                ],
                "hankel_truncation_absolute_error_upper_hex": asymptotic[
                    "hankel_truncation_abs_upper_hex"
                ],
                "asymptotic_composite_absolute_error_upper_hex": asymptotic[
                    "absolute_error_upper_hex"
                ],
                "switch_active_branch": switch["active_branch"],
                "switch_series_observed_absolute_error_upper_hex": switch[
                    "series_actual_abs_upper_hex"
                ],
                "switch_asymptotic_observed_absolute_error_upper_hex": switch[
                    "asymptotic_actual_abs_upper_hex"
                ],
            }
            partitions[precision][name] = {
                "boundary_count": partition["boundary_count"],
                "first_boundary_left_n": partition["first_boundary_left_n"],
                "last_boundary_left_n": partition["last_boundary_left_n"],
                "reduced_argument_absolute_upper_hex": partition[
                    "analytic_reduced_abs_upper_hex"
                ],
                "tie_policy": "both adjacent quadrants certified",
            }
    return {
        "schema_version": "futhark-bessel.real-approximation-bounds.v1",
        "status": "CERTIFIED_EXACT_REAL_WHOLE_DOMAIN",
        "scope": {
            "input_domain": "real x with |x| <= 1024",
            "semantic_model": (
                "source binary literals are exact dyadic reals and arithmetic "
                "operations are over the reals"
            ),
            "covered": (
                "series and Hankel truncation, phase constants, exhaustive "
                "rounding-cell partition, Taylor truncation, prefactor constant, "
                "switch points, and domain endpoints"
            ),
            "excluded": (
                "backend floating-point rounding, contraction, and reassociation"
            ),
        },
        "authority": {
            "implementation_source": str(IMPLEMENTATION),
            "implementation_sha256": implementation_sha256,
            "certificate_ledger": str(CERTIFICATES),
            "certificate_rows": len(rows),
            "certificate_sha256": hashlib.sha256(raw).hexdigest(),
            "certifier": "FLINT/Arb 3.6.0 at 1024-bit precision",
            "independent_verifier": "mpmath 1.4.1 at 180 decimal digits",
            "theorems": [
                "alternating-series first-omitted-term remainder",
                "DLMF 10.17(iii) real-argument Hankel remainder bounds",
                "Taylor first-omitted-term remainder on |r| < pi/4 + 0.0001",
                "unit-Lipschitz sine and cosine phase propagation",
            ],
        },
        "bounds": bounds,
        "range_reduction_partitions": partitions,
        "release_implications": {
            "real_arithmetic_mathematical_approximation": "CERTIFIED",
            "floating_point_rounding_reassociation": "OPEN",
            "backend_release_envelopes": "OPEN",
            "overall_release_status": "INCOMPLETE",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--write", action="store_true")
    args = parser.parse_args()
    mp.mp.dps = 180
    raw = CERTIFICATES.read_bytes()
    generated = json.dumps(generate_summary(raw), indent=2, sort_keys=True) + "\n"
    if args.write:
        SUMMARY.write_text(generated)
        print(f"wrote {SUMMARY}")
        return
    if not SUMMARY.exists() or SUMMARY.read_text() != generated:
        raise SystemExit(
            "real-arithmetic approximation summary is stale; run "
            "scripts/approximation_proof.py --write"
        )
    summary = json.loads(generated)
    print(
        "OK exact-real whole-domain approximation bounds: "
        f"{summary['authority']['certificate_rows']} Arb certificate rows; "
        "floating-point rounding/reassociation remains OPEN"
    )


if __name__ == "__main__":
    main()
