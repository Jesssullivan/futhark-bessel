#!/usr/bin/env python3
# SPDX-License-Identifier: ISC
"""Independently verify transition bands and Arb adjacent composition proofs."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import struct
from fractions import Fraction
from pathlib import Path
from typing import Any

import mpmath as mp

BANDS = Path("evidence/adjacent-reduction-bands.json")
CERTIFICATES = Path("evidence/adjacent-composition-certificates.jsonl")
SUMMARY = Path("evidence/adjacent-composition-proof.json")
IMPLEMENTATION = Path(
    "lib/github.com/Jesssullivan/futhark-bessel/bessel_internal.fut"
)
GENERATOR = Path("scripts/adjacent_reduction_bands.py")
ORACLE = Path("oracle/adjacent_composition.c")
VERIFIER = Path("scripts/adjacent_composition_proof.py")
EXACT_REAL = Path("evidence/real-approximation-bounds.json")
EXPECTED_IMPLEMENTATION_SHA256 = (
    "2b459fb3e24e82a825db5f44cc8b3ebe9c8387d598235f84c4e80996b4e7d9d1"
)
EXPECTED_MPMATH_VERSION = "1.4.1"
DOMAIN_MAX = Fraction(1024)
INDEX_ABS_BOUND = 653

CONFIGS: dict[str, dict[str, Any]] = {
    "f32": {
        "precision_bits": 24,
        "switch": Fraction(6),
        "hankel_last": 7,
        "sin_first_omitted": 11,
        "cos_first_omitted": 12,
        "two_over_pi": "0x1.45f306p-1",
        "pio2": ("0x1.9218p+0", "0x1.ed511p-14", "0x1.68c234p-39"),
        "pi_used": "0x1.921fb6p+1",
        "offsets": ("0x1.921fb6p-1", "0x1.2d97c8p+1"),
        "etas": ("0x1.463306a30c131p-14", "0x1.46b306a2dfb66p-14"),
        "bit_width": 8,
    },
    "f64": {
        "precision_bits": 53,
        "switch": Fraction(12),
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
        "etas": ("0x1.463306dc9c884p-43", "0x1.46b306dc9c884p-43"),
        "bit_width": 16,
    },
}


def exact_hex(text: str) -> Fraction:
    value = float.fromhex(text)
    if not math.isfinite(value):
        raise SystemExit(f"nonfinite hexadecimal value: {text}")
    return Fraction(*value.as_integer_ratio())


def mpq(value: Fraction) -> mp.mpf:
    return mp.mpf(value.numerator) / value.denominator


def decode_rational(value: Any, label: str) -> Fraction:
    if not isinstance(value, dict) or set(value) != {"numerator", "denominator"}:
        raise SystemExit(f"malformed exact rational {label}")
    if not all(isinstance(value[key], str) for key in value):
        raise SystemExit(f"non-string exact rational {label}")
    try:
        result = Fraction(int(value["numerator"]), int(value["denominator"]))
    except (ValueError, ZeroDivisionError) as error:
        raise SystemExit(f"invalid exact rational {label}") from error
    if str(result.numerator) != value["numerator"] or str(result.denominator) != value[
        "denominator"
    ]:
        raise SystemExit(f"noncanonical exact rational {label}")
    return result


def nearest_integer(value: Fraction) -> int:
    floor = value.numerator // value.denominator
    remainder = value - floor
    if remainder < Fraction(1, 2):
        return floor
    if remainder > Fraction(1, 2):
        return floor + 1
    return floor if floor % 2 == 0 else floor + 1


def floor_log2(value: Fraction) -> int:
    exponent = value.numerator.bit_length() - value.denominator.bit_length()
    if Fraction(2) ** exponent > value:
        exponent -= 1
    while Fraction(2) ** (exponent + 1) <= value:
        exponent += 1
    return exponent


def round_positive_normal(value: Fraction, precision_bits: int) -> Fraction:
    spacing = Fraction(2) ** (floor_log2(value) - (precision_bits - 1))
    return nearest_integer(value / spacing) * spacing


def bits_fraction(bits: int, precision: str) -> Fraction:
    if precision == "f32":
        value = struct.unpack(">f", struct.pack(">I", bits))[0]
    else:
        value = struct.unpack(">d", struct.pack(">Q", bits))[0]
    return Fraction(*value.as_integer_ratio())


def float_bits(value: Fraction, precision: str, p: int) -> int:
    if precision == "f32":
        bits = struct.unpack(">I", struct.pack(">f", float(value)))[0]
    else:
        bits = struct.unpack(">Q", struct.pack(">d", float(value)))[0]
    if bits_fraction(bits, precision) != round_positive_normal(value, p):
        raise SystemExit(f"host conversion disagrees with exact {precision} RN-even")
    return bits


def first_bits_at_least(
    target: Fraction, lower: int, upper: int, precision: str
) -> int:
    while lower < upper:
        middle = (lower + upper) // 2
        if bits_fraction(middle, precision) < target:
            lower = middle + 1
        else:
            upper = middle
    return lower


def last_bits_at_most(
    target: Fraction, lower: int, upper: int, precision: str
) -> int:
    while lower < upper:
        middle = (lower + upper + 1) // 2
        if bits_fraction(middle, precision) > target:
            upper = middle - 1
        else:
            lower = middle
    return lower


def reduced_index_exact(x: Fraction, offset: Fraction, c: Fraction) -> int:
    return nearest_integer((x - offset) * c)


def reduced_index_floating(
    x: Fraction, offset: Fraction, c: Fraction, p: int
) -> int:
    phase = round_positive_normal(x - offset, p)
    product = round_positive_normal(phase * c, p)
    return nearest_integer(product)


def parse_bits(value: Any, width: int, label: str) -> int:
    if not isinstance(value, str) or re.fullmatch(
        rf"0x[0-9a-f]{{{width}}}", value
    ) is None:
        raise SystemExit(f"malformed bit pattern {label}")
    return int(value, 16)


def verify_band_case(case: dict[str, Any], precision: str, order: int) -> dict[str, int]:
    cfg = CONFIGS[precision]
    p = cfg["precision_bits"]
    width = cfg["bit_width"]
    if case.get("precision") != precision or case.get("order") != order:
        raise SystemExit(f"misidentified transition case {precision}/J{order}")
    c = exact_hex(cfg["two_over_pi"])
    offset = exact_hex(cfg["offsets"][order])
    eta = exact_hex(cfg["etas"][order])
    split = sum((exact_hex(item) for item in cfg["pio2"]), Fraction())
    parameters = case.get("parameters", {})
    if (
        decode_rational(parameters.get("offset"), "offset") != offset
        or decode_rational(parameters.get("two_over_pi"), "two_over_pi") != c
        or decode_rational(parameters.get("accepted_eta"), "accepted_eta") != eta
        or parameters.get("accepted_eta_hex") != cfg["etas"][order]
        or decode_rational(parameters.get("split_pio2"), "split_pio2") != split
        or parameters.get("index_abs_bound") != INDEX_ABS_BOUND
    ):
        raise SystemExit(f"transition parameters drifted for {precision}/J{order}")
    rho = (Fraction(1, 2) + eta) / c + INDEX_ABS_BOUND * abs(
        Fraction(1, 1) / c - split
    )
    if decode_rational(parameters.get("shadow_reduction_radius"), "rho") != rho:
        raise SystemExit(f"shadow radius drifted for {precision}/J{order}")

    domain = case.get("domain", {})
    domain_first_bits = float_bits(cfg["switch"], precision, p) + 1
    domain_last_bits = float_bits(DOMAIN_MAX, precision, p)
    domain_first = bits_fraction(domain_first_bits, precision)
    if (
        parse_bits(domain.get("first_bits"), width, "domain first")
        != domain_first_bits
        or parse_bits(domain.get("last_bits"), width, "domain last")
        != domain_last_bits
        or decode_rational(domain.get("first_value"), "domain first")
        != domain_first
        or decode_rational(domain.get("last_value"), "domain last")
        != DOMAIN_MAX
    ):
        raise SystemExit(f"transition domain drifted for {precision}/J{order}")

    first_index = reduced_index_exact(domain_first, offset, c)
    last_index = reduced_index_exact(DOMAIN_MAX, offset, c)
    partition = case.get("partition", {})
    bands = partition.get("bands")
    if not isinstance(bands, list):
        raise SystemExit(f"transition bands missing for {precision}/J{order}")
    expected_ks = list(range(first_index, last_index))
    if [band.get("k") for band in bands] != expected_ks:
        raise SystemExit(f"transition band index coverage drifted for {precision}/J{order}")
    common_denominator = int(partition.get("common_endpoint_denominator", "0"))
    if common_denominator <= 0:
        raise SystemExit("invalid common band denominator")
    preceding_upper = offset + (
        Fraction(2 * (first_index - 1) + 1, 2) + eta
    ) / c
    following_lower = offset + (Fraction(2 * last_index + 1, 2) - eta) / c
    edge_separation = partition.get("domain_edge_separation", {})
    if edge_separation != {
        "preceding_band_k": first_index - 1,
        "preceding_band_upper": {
            "numerator": str(preceding_upper.numerator),
            "denominator": str(preceding_upper.denominator),
        },
        "lower_gap": {
            "numerator": str((domain_first - preceding_upper).numerator),
            "denominator": str((domain_first - preceding_upper).denominator),
        },
        "following_band_k": last_index,
        "following_band_lower": {
            "numerator": str(following_lower.numerator),
            "denominator": str(following_lower.denominator),
        },
        "upper_gap": {
            "numerator": str((following_lower - DOMAIN_MAX).numerator),
            "denominator": str((following_lower - DOMAIN_MAX).denominator),
        },
    } or not preceding_upper < domain_first or not DOMAIN_MAX < following_lower:
        raise SystemExit(f"domain edge separation drifted for {precision}/J{order}")

    candidate_total = mismatch_total = span_total = 0
    first_witness: dict[str, Any] | None = None
    previous_upper: Fraction | None = None
    for band, k in zip(bands, expected_ks, strict=True):
        expected_fields = {
            "k",
            "lower_numerator",
            "upper_numerator",
            "outward_lower_bits",
            "outward_upper_bits",
            "candidate_first_bits",
            "candidate_last_bits",
            "candidate_count",
            "allowed_indices",
            "mismatch_count",
            "mismatch_spans",
        }
        if set(band) != expected_fields:
            raise SystemExit(f"malformed transition band for {precision}/J{order}")
        lower = offset + (Fraction(2 * k + 1, 2) - eta) / c
        upper = offset + (Fraction(2 * k + 1, 2) + eta) / c
        if (
            Fraction(int(band["lower_numerator"]), common_denominator) != lower
            or Fraction(int(band["upper_numerator"]), common_denominator) != upper
        ):
            raise SystemExit(f"exact transition endpoint drifted for {precision}/J{order}")
        if previous_upper is not None and not previous_upper < lower:
            raise SystemExit(f"transition bands overlap for {precision}/J{order}")
        previous_upper = upper
        candidate_first = first_bits_at_least(
            lower, domain_first_bits, domain_last_bits, precision
        )
        candidate_last = last_bits_at_most(
            upper, domain_first_bits, domain_last_bits, precision
        )
        outward_lower = last_bits_at_most(
            lower, domain_first_bits, domain_last_bits, precision
        )
        outward_upper = first_bits_at_least(
            upper, domain_first_bits, domain_last_bits, precision
        )
        if (
            parse_bits(band["candidate_first_bits"], width, "candidate first")
            != candidate_first
            or parse_bits(band["candidate_last_bits"], width, "candidate last")
            != candidate_last
            or parse_bits(band["outward_lower_bits"], width, "outward lower")
            != outward_lower
            or parse_bits(band["outward_upper_bits"], width, "outward upper")
            != outward_upper
            or band["candidate_count"] != candidate_last - candidate_first + 1
            or band["allowed_indices"] != [k, k + 1]
        ):
            raise SystemExit(f"IEEE band enclosure drifted for {precision}/J{order}")

        expected_spans: list[dict[str, Any]] = []
        active: dict[str, Any] | None = None
        for bits in range(candidate_first, candidate_last + 1):
            x = bits_fraction(bits, precision)
            n = reduced_index_exact(x, offset, c)
            m = reduced_index_floating(x, offset, c, p)
            if n not in (k, k + 1) or m not in (k, k + 1):
                raise SystemExit(f"nonadjacent band selection for {precision}/J{order}")
            if n == m:
                if active is not None:
                    expected_spans.append(active)
                    active = None
                continue
            if (
                active is None
                or bits != active["last"] + 1
                or n != active["exact_index"]
                or m != active["floating_index"]
            ):
                if active is not None:
                    expected_spans.append(active)
                active = {
                    "first": bits,
                    "last": bits,
                    "count": 1,
                    "exact_index": n,
                    "floating_index": m,
                }
            else:
                active["last"] = bits
                active["count"] += 1
        if active is not None:
            expected_spans.append(active)
        observed_spans = band["mismatch_spans"]
        if len(observed_spans) != len(expected_spans):
            raise SystemExit(f"mismatch span count drifted for {precision}/J{order}")
        for observed, expected in zip(observed_spans, expected_spans, strict=True):
            if observed != {
                "first_bits": f"0x{expected['first']:0{width}x}",
                "last_bits": f"0x{expected['last']:0{width}x}",
                "count": expected["count"],
                "exact_index": expected["exact_index"],
                "floating_index": expected["floating_index"],
            }:
                raise SystemExit(f"mismatch span drifted for {precision}/J{order}")
        mismatch_count = sum(item["count"] for item in expected_spans)
        if band["mismatch_count"] != mismatch_count:
            raise SystemExit(f"mismatch census drifted for {precision}/J{order}")
        if first_witness is None and expected_spans:
            first = expected_spans[0]
            first_witness = {
                "x_bits": f"0x{first['first']:0{width}x}",
                "x_hex": float(bits_fraction(first["first"], precision)).hex(),
                "exact_index": first["exact_index"],
                "floating_index": first["floating_index"],
            }
        candidate_total += candidate_last - candidate_first + 1
        mismatch_total += mismatch_count
        span_total += len(expected_spans)
    if partition.get("first_mismatch_witness") != first_witness:
        raise SystemExit(f"first mismatch witness drifted for {precision}/J{order}")
    expected_aggregate = {
        "transition_band_count": len(bands),
        "stable_interior_count": len(bands) + 1,
        "candidate_count": candidate_total,
        "mismatch_count": mismatch_total,
        "mismatch_span_count": span_total,
    }
    if any(partition.get(key) != value for key, value in expected_aggregate.items()):
        raise SystemExit(f"transition aggregate drifted for {precision}/J{order}")
    return expected_aggregate


def parse_ball(text: Any) -> tuple[mp.mpf, mp.mpf]:
    if not isinstance(text, str):
        raise SystemExit("Arb ball is not a string")
    payload = text.removeprefix("[").removesuffix("]")
    exact = re.fullmatch(r"([+-]?[0-9.]+(?:e[+-]?[0-9]+)?)", payload)
    if exact:
        value = mp.mpf(exact.group(1))
        return value, value
    ball = re.fullmatch(
        r"([+-]?[0-9.]+(?:e[+-]?[0-9]+)?) \+/- ([0-9.]+(?:e[+-]?[0-9]+)?)",
        payload,
    )
    if ball is None:
        raise SystemExit(f"unsupported Arb ball: {text}")
    midpoint = mp.mpf(ball.group(1))
    radius = mp.mpf(ball.group(2))
    return midpoint - radius, midpoint + radius


def contains(text: Any, expected: mp.mpf, label: str) -> None:
    lower, upper = parse_ball(text)
    if lower > upper or not lower <= expected <= upper:
        raise SystemExit(f"mpmath value escaped Arb certificate for {label}")
    if upper - lower > max(mp.mpf("1e-75"), abs(expected) * mp.mpf("1e-75")):
        raise SystemExit(f"Arb certificate unexpectedly loose for {label}")


def coefficient(order: int, m: int) -> mp.mpf:
    value = mp.mpf(1)
    for k in range(1, m + 1):
        value *= mp.mpf(4 * order * order - (2 * k - 1) ** 2) / (8 * k)
    return value


def first_after_with_parity(last: int, parity: int) -> int:
    candidate = last + 1
    return candidate if candidate % 2 == parity else candidate + 1


def expected_components(precision: str, order: int) -> dict[str, mp.mpf]:
    cfg = CONFIGS[precision]
    eta = mpq(exact_hex(cfg["etas"][order]))
    c = mpq(exact_hex(cfg["two_over_pi"]))
    split = mp.fsum(mpq(exact_hex(item)) for item in cfg["pio2"])
    offset = mpq(exact_hex(cfg["offsets"][order]))
    rho = (mp.mpf("0.5") + eta) / c + INDEX_ABS_BOUND * abs(1 / c - split)
    delta = abs(offset - (2 * order + 1) * mp.pi / 4) + INDEX_ABS_BOUND * abs(
        split - mp.pi / 2
    )
    sin_tail = rho ** cfg["sin_first_omitted"] / mp.factorial(
        cfg["sin_first_omitted"]
    )
    cos_tail = rho ** cfg["cos_first_omitted"] / mp.factorial(
        cfg["cos_first_omitted"]
    )
    switch = mpq(cfg["switch"])
    p_abs = mp.fsum(
        abs(coefficient(order, m)) / switch**m
        for m in range(0, cfg["hankel_last"] + 1, 2)
    )
    q_abs = mp.fsum(
        abs(coefficient(order, m)) / switch**m
        for m in range(1, cfg["hankel_last"] + 1, 2)
    )
    first_even = first_after_with_parity(cfg["hankel_last"], 0)
    first_odd = first_after_with_parity(cfg["hankel_last"], 1)
    p_remainder = abs(coefficient(order, first_even)) / switch**first_even
    q_remainder = abs(coefficient(order, first_odd)) / switch**first_odd
    prefactor = mp.sqrt(2 / (mp.pi * switch))
    used_prefactor = mp.sqrt(
        2 / (mpq(exact_hex(cfg["pi_used"])) * switch)
    )
    prefactor_error = abs(used_prefactor - prefactor)
    hankel_error = prefactor * (p_remainder + q_remainder)
    return {
        "accepted_eta": eta,
        "shadow_reduction_radius": rho,
        "phase_reconstruction_error": delta,
        "sin_taylor_remainder": sin_tail,
        "cos_taylor_remainder": cos_tail,
        "p_sum_abs": p_abs,
        "q_sum_abs": q_abs,
        "p_remainder": p_remainder,
        "q_remainder": q_remainder,
        "prefactor": prefactor,
        "prefactor_error": prefactor_error,
        "hankel_error": hankel_error,
    }


def upward_hex(value: mp.mpf) -> str:
    candidate = float(value)
    if not math.isfinite(candidate):
        raise SystemExit("composition bound is not finite binary64")
    if mp.mpf(candidate) < value:
        candidate = math.nextafter(candidate, math.inf)
    return candidate.hex()


def verify_certificates(raw: bytes) -> dict[str, dict[str, Any]]:
    try:
        rows = [json.loads(line) for line in raw.decode().splitlines()]
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SystemExit(f"malformed adjacent composition ledger: {error}") from error
    if len(rows) != 36:
        raise SystemExit(f"expected 36 adjacent composition rows, got {len(rows)}")
    summaries: dict[str, dict[str, Any]] = {"f32": {}, "f64": {}}
    for precision in ("f32", "f64"):
        for order in (0, 1):
            components = expected_components(precision, order)
            case_rows = [
                row
                for row in rows
                if row.get("kind") == "shadow_case"
                and row.get("precision") == precision
                and row.get("order") == order
            ]
            if len(case_rows) != 1:
                raise SystemExit(f"missing shadow case {precision}/J{order}")
            case = case_rows[0]
            expected_case_fields = {
                "kind",
                "precision",
                "order",
                *components.keys(),
                "index_abs_bound",
                "p_first_omitted_index",
                "q_first_omitted_index",
                "p_ell",
                "q_ell",
                "dlmf_real_argument_conditions_certified",
                "certifier",
            }
            cfg = CONFIGS[precision]
            first_even = first_after_with_parity(cfg["hankel_last"], 0)
            first_odd = first_after_with_parity(cfg["hankel_last"], 1)
            if (
                set(case) != expected_case_fields
                or case["index_abs_bound"] != INDEX_ABS_BOUND
                or case["p_first_omitted_index"] != first_even
                or case["q_first_omitted_index"] != first_odd
                or case["p_ell"] != first_even // 2
                or case["q_ell"] != (first_odd - 1) // 2
                or not case["dlmf_real_argument_conditions_certified"]
                or case["certifier"] != "FLINT/Arb 3.6.0"
            ):
                raise SystemExit(f"malformed shadow case {precision}/J{order}")
            if case["p_ell"] < max(mp.mpf(order) / 2 - mp.mpf(1) / 4, 1):
                raise SystemExit("DLMF P-remainder condition is not satisfied")
            if case["q_ell"] < max(mp.mpf(order) / 2 - mp.mpf(3) / 4, 1):
                raise SystemExit("DLMF Q-remainder condition is not satisfied")
            for field, value in components.items():
                contains(case[field], value, f"{precision}/J{order}/{field}")

            quadrant_rows = [
                row
                for row in rows
                if row.get("kind") == "adjacent_quadrant"
                and row.get("precision") == precision
                and row.get("order") == order
            ]
            if len(quadrant_rows) != 8:
                raise SystemExit(f"incomplete adjacent quadrants {precision}/J{order}")
            maxima: list[mp.mpf] = []
            observed_keys: set[tuple[int, str]] = set()
            for row in quadrant_rows:
                expected_fields = {
                    "kind",
                    "precision",
                    "order",
                    "boundary_quadrant",
                    "candidate",
                    "selected_quadrant",
                    "sin_error",
                    "cos_error",
                    "shadow_math_absolute_error",
                    "certifier",
                }
                if set(row) != expected_fields or row["certifier"] != "FLINT/Arb 3.6.0":
                    raise SystemExit(f"malformed quadrant row {precision}/J{order}")
                boundary = row["boundary_quadrant"]
                candidate = row["candidate"]
                if boundary not in range(4) or candidate not in ("k", "k+1"):
                    raise SystemExit(f"invalid adjacent quadrant identity {precision}/J{order}")
                key = (boundary, candidate)
                if key in observed_keys:
                    raise SystemExit(f"duplicate adjacent quadrant {precision}/J{order}")
                observed_keys.add(key)
                selected = (boundary + (candidate == "k+1")) % 4
                if row["selected_quadrant"] != selected:
                    raise SystemExit(f"selected quadrant drifted {precision}/J{order}")
                swapped = selected % 2 != 0
                sin_error = components["phase_reconstruction_error"] + components[
                    "cos_taylor_remainder" if swapped else "sin_taylor_remainder"
                ]
                cos_error = components["phase_reconstruction_error"] + components[
                    "sin_taylor_remainder" if swapped else "cos_taylor_remainder"
                ]
                total = (
                    components["hankel_error"]
                    + components["prefactor_error"]
                    * (
                        (1 + cos_error) * components["p_sum_abs"]
                        + (1 + sin_error) * components["q_sum_abs"]
                    )
                    + components["prefactor"]
                    * (
                        cos_error * components["p_sum_abs"]
                        + sin_error * components["q_sum_abs"]
                    )
                )
                contains(row["sin_error"], sin_error, "quadrant sine error")
                contains(row["cos_error"], cos_error, "quadrant cosine error")
                contains(row["shadow_math_absolute_error"], total, "shadow math error")
                maxima.append(total)
            if observed_keys != {(q, side) for q in range(4) for side in ("k", "k+1")}:
                raise SystemExit(f"adjacent quadrant coverage drifted {precision}/J{order}")
            summaries[precision][f"j{order}"] = {
                "accepted_product_error_upper_hex": CONFIGS[precision]["etas"][order],
                "shadow_reduction_radius_upper_hex": upward_hex(
                    components["shadow_reduction_radius"]
                ),
                "phase_reconstruction_absolute_error_upper_hex": upward_hex(
                    components["phase_reconstruction_error"]
                ),
                "sin_taylor_remainder_upper_hex": upward_hex(
                    components["sin_taylor_remainder"]
                ),
                "cos_taylor_remainder_upper_hex": upward_hex(
                    components["cos_taylor_remainder"]
                ),
                "shadow_math_absolute_error_upper_hex": upward_hex(max(maxima)),
                "adjacent_quadrant_certificate_rows": len(quadrant_rows),
            }
    return summaries


def generate_summary() -> dict[str, Any]:
    implementation_sha = hashlib.sha256(IMPLEMENTATION.read_bytes()).hexdigest()
    if implementation_sha != EXPECTED_IMPLEMENTATION_SHA256:
        raise SystemExit("adjacent proof implementation source drifted")
    bands_raw = BANDS.read_bytes()
    bands = json.loads(bands_raw)
    if (
        bands.get("schema_version")
        != "futhark-bessel.adjacent-reduction-bands.v1"
        or bands.get("status") != "EXACT_RATIONAL_TRANSITION_PARTITION_PROVED"
        or bands.get("scope", {}).get("transition_bands") != 2584
    ):
        raise SystemExit("unexpected transition band authority")
    authority = bands.get("authority", {})
    if (
        authority.get("implementation_source") != str(IMPLEMENTATION)
        or authority.get("implementation_sha256") != implementation_sha
        or authority.get("generator") != str(GENERATOR)
        or authority.get("generator_sha256")
        != hashlib.sha256(GENERATOR.read_bytes()).hexdigest()
    ):
        raise SystemExit("transition band authority hash drifted")
    expected_distinction = (
        "These are floating source-reduction transition bands, not the 2,584 "
        "canonical exact-real cell boundaries in the separate approximation ledger."
    )
    if bands.get("scope", {}).get("distinction") != expected_distinction:
        raise SystemExit("floating/canonical partition distinction drifted")
    cases = bands.get("cases")
    if not isinstance(cases, list) or len(cases) != 4:
        raise SystemExit("transition authority does not contain four cases")
    census: dict[str, dict[str, Any]] = {"f32": {}, "f64": {}}
    for case, (precision, order) in zip(
        cases,
        ((precision, order) for precision in ("f32", "f64") for order in (0, 1)),
        strict=True,
    ):
        census[precision][f"j{order}"] = verify_band_case(case, precision, order)
    if sum(item["transition_band_count"] for group in census.values() for item in group.values()) != 2584:
        raise SystemExit("floating transition-band total drifted")

    raw_certificates = CERTIFICATES.read_bytes()
    bounds = verify_certificates(raw_certificates)
    exact_real_raw = EXACT_REAL.read_bytes()
    exact_real = json.loads(exact_real_raw)
    if (
        exact_real.get("status") != "CERTIFIED_EXACT_REAL_WHOLE_DOMAIN"
        or exact_real.get("authority", {}).get("implementation_sha256")
        != implementation_sha
    ):
        raise SystemExit("exact-real authority binding drifted")
    return {
        "schema_version": "futhark-bessel.adjacent-composition-proof.v1",
        "status": "ADJACENT_REDUCTION_COMPOSITION_PROVED",
        "scope": {
            "domain": "representable source inputs with switch < |x| <= 1024",
            "primitive_semantics": (
                "strict written source graph; one IEEE-754 roundTiesToEven per "
                "primitive; gradual underflow; no contraction or reassociation"
            ),
            "covered": (
                "complete floating transition-band partition, both selected "
                "adjacent quadrants, shadow-index reduced radius, Taylor phase "
                "reconstruction, DLMF Hankel remainders, and prefactor discrepancy"
            ),
            "excluded": (
                "C/WASM/WebGPU lowering equivalence, contraction/reassociation, "
                "solver mathematical-root ULP/true-residual envelopes (certified "
                "by separate evidence/solver-root-envelopes.json), and runtime "
                "conformance"
            ),
            "partition_distinction": expected_distinction,
        },
        "theorem": {
            "transition": (
                "For z=(x-delta)c and zhat=RN(RN(x-delta)c), accepted "
                "|zhat-z|<=eta<1/4 gives disjoint B_k; outside all B_k m=n, "
                "and inside B_k both m and n lie in {k,k+1}."
            ),
            "shadow_radius": (
                "rho*=((1/2+eta)/c)+653*abs(1/c-L) bounds "
                "r_m=(x-delta)-mL for either selected adjacent index."
            ),
            "quadrants": (
                "Every Q_m(S,C), m mod 4, is certified against the same true "
                "phase, so every adjacent pair k,k+1 is covered."
            ),
            "composition": (
                "For each representable source input, absolute error is at most "
                "the source-graph forward-rounding bound at rho* plus the "
                "shadow mathematical approximation bound."
            ),
            "taylor": (
                "Direct Lagrange remainder |r|^N/N! at rho*; it does not reuse "
                "the smaller canonical-index radius restriction."
            ),
        },
        "authority": {
            "implementation_source": str(IMPLEMENTATION),
            "implementation_sha256": implementation_sha,
            "transition_bands": str(BANDS),
            "transition_bands_sha256": hashlib.sha256(bands_raw).hexdigest(),
            "transition_generator": str(GENERATOR),
            "transition_generator_sha256": hashlib.sha256(
                GENERATOR.read_bytes()
            ).hexdigest(),
            "certificate_ledger": str(CERTIFICATES),
            "certificate_rows": len(raw_certificates.splitlines()),
            "certificate_sha256": hashlib.sha256(raw_certificates).hexdigest(),
            "certifier_source": str(ORACLE),
            "certifier_source_sha256": hashlib.sha256(ORACLE.read_bytes()).hexdigest(),
            "certifier": "FLINT/Arb 3.6.0 at 1024-bit precision",
            "independent_verifier": str(VERIFIER),
            "independent_verifier_sha256": hashlib.sha256(
                VERIFIER.read_bytes()
            ).hexdigest(),
            "independent_verifier_runtime": "mpmath 1.4.1 at 180 decimal digits",
            "exact_real_evidence": str(EXACT_REAL),
            "exact_real_evidence_sha256": hashlib.sha256(exact_real_raw).hexdigest(),
        },
        "transition_census": census,
        "bounds": bounds,
        "release_implications": {
            "adjacent_source_reduction_composition": "PROVED",
            "backend_lowering_equivalence": "OPEN",
            "solver_mathematical_root_ulp_and_true_residual": "CERTIFIED_SEPARATE_EVIDENCE",
            "overall_release_status": "INCOMPLETE",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--write", action="store_true")
    action.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if mp.__version__ != EXPECTED_MPMATH_VERSION:
        raise SystemExit(f"expected mpmath {EXPECTED_MPMATH_VERSION}, got {mp.__version__}")
    mp.mp.dps = 180
    rendered = json.dumps(generate_summary(), indent=2, sort_keys=True) + "\n"
    if args.write:
        SUMMARY.write_text(rendered)
        print(f"wrote {SUMMARY}")
    elif not SUMMARY.exists() or SUMMARY.read_text() != rendered:
        raise SystemExit(
            "adjacent composition summary is stale; run "
            "scripts/adjacent_composition_proof.py --write"
        )
    else:
        print("OK adjacent reduction composition proved; backend lowering remains OPEN")


if __name__ == "__main__":
    main()
