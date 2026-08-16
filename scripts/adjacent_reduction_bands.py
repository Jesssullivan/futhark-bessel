#!/usr/bin/env python3
# SPDX-License-Identifier: ISC
"""Generate the exact transition-band partition for source range reduction.

The output is a compact authority: band endpoints use a common exact-rational
denominator per precision/order case, while IEEE bounds and mismatch spans are
encoded as raw positive finite bit patterns.  Stable interiors are covered by
the stated separation theorem rather than by enumerating their (enormous)
representable populations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
from fractions import Fraction
from pathlib import Path
from typing import Any

IMPLEMENTATION = Path(
    "lib/github.com/Jesssullivan/futhark-bessel/bessel_internal.fut"
)
GENERATOR = Path("scripts/adjacent_reduction_bands.py")
OUTPUT = Path("evidence/adjacent-reduction-bands.json")
DOMAIN_MAX = Fraction(1024)

CONFIGS: dict[str, dict[str, Any]] = {
    "f32": {
        "precision_bits": 24,
        "switch": Fraction(6),
        "two_over_pi": "0x1.45f306p-1",
        "pio2": ("0x1.9218p+0", "0x1.ed511p-14", "0x1.68c234p-39"),
        "offsets": ("0x1.921fb6p-1", "0x1.2d97c8p+1"),
        "etas": ("0x1.463306a30c131p-14", "0x1.46b306a2dfb66p-14"),
        "bit_width": 8,
    },
    "f64": {
        "precision_bits": 53,
        "switch": Fraction(12),
        "two_over_pi": "0x1.45f306dc9c883p-1",
        "pio2": (
            "0x1.921fb54000000p+0",
            "0x1.10b4611a62633p-30",
            "0x1.45c06e0e68948p-86",
        ),
        "offsets": ("0x1.921fb54442d18p-1", "0x1.2d97c7f3321d2p+1"),
        "etas": ("0x1.463306dc9c884p-43", "0x1.46b306dc9c884p-43"),
        "bit_width": 16,
    },
}


def exact_hex(text: str) -> Fraction:
    return Fraction(*float.fromhex(text).as_integer_ratio())


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


def float_bits(value: Fraction, precision: str, precision_bits: int) -> int:
    if precision == "f32":
        bits = struct.unpack(">I", struct.pack(">f", float(value)))[0]
    else:
        bits = struct.unpack(">Q", struct.pack(">d", float(value)))[0]
    if bits_fraction(bits, precision) != round_positive_normal(
        value, precision_bits
    ):
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
    x: Fraction,
    offset: Fraction,
    c: Fraction,
    precision_bits: int,
) -> int:
    phase = round_positive_normal(x - offset, precision_bits)
    product = round_positive_normal(phase * c, precision_bits)
    return nearest_integer(product)


def rational(value: Fraction) -> dict[str, str]:
    return {"numerator": str(value.numerator), "denominator": str(value.denominator)}


def encoded(bits: int, width: int) -> str:
    return f"0x{bits:0{width}x}"


def case_partition(precision: str, order: int) -> dict[str, Any]:
    cfg = CONFIGS[precision]
    p = cfg["precision_bits"]
    width = cfg["bit_width"]
    c = exact_hex(cfg["two_over_pi"])
    offset = exact_hex(cfg["offsets"][order])
    eta = exact_hex(cfg["etas"][order])
    split = sum((exact_hex(item) for item in cfg["pio2"]), Fraction())
    if eta >= Fraction(1, 4):
        raise SystemExit(f"{precision}/J{order} transition bands are not disjoint")

    domain_first_bits = float_bits(cfg["switch"], precision, p) + 1
    domain_last_bits = float_bits(DOMAIN_MAX, precision, p)
    domain_first = bits_fraction(domain_first_bits, precision)
    first_index = reduced_index_exact(domain_first, offset, c)
    last_index = reduced_index_exact(DOMAIN_MAX, offset, c)
    if reduced_index_floating(domain_first, offset, c, p) != first_index:
        raise SystemExit(f"{precision}/J{order} domain start index drifted")
    if reduced_index_floating(DOMAIN_MAX, offset, c, p) != last_index:
        raise SystemExit(f"{precision}/J{order} domain end index drifted")
    preceding_upper = offset + (
        Fraction(2 * (first_index - 1) + 1, 2) + eta
    ) / c
    following_lower = offset + (Fraction(2 * last_index + 1, 2) - eta) / c
    if not preceding_upper < domain_first or not DOMAIN_MAX < following_lower:
        raise SystemExit(f"{precision}/J{order} omitted edge band overlaps domain")

    base_lower = offset + (Fraction(1, 2) - eta) / c
    base_upper = offset + (Fraction(1, 2) + eta) / c
    step = Fraction(1, 1) / c
    common_denominator = math.lcm(
        base_lower.denominator, base_upper.denominator, step.denominator
    )

    bands: list[dict[str, Any]] = []
    total_candidates = 0
    total_mismatches = 0
    total_spans = 0
    first_witness: dict[str, Any] | None = None
    previous_upper: Fraction | None = None
    for k in range(first_index, last_index):
        lower = offset + (Fraction(2 * k + 1, 2) - eta) / c
        upper = offset + (Fraction(2 * k + 1, 2) + eta) / c
        center = offset + Fraction(2 * k + 1, 2) / c
        if not domain_first <= center <= DOMAIN_MAX:
            continue
        if previous_upper is not None and not previous_upper < lower:
            raise SystemExit(f"{precision}/J{order} transition bands overlap")
        previous_upper = upper

        candidate_first = first_bits_at_least(
            max(lower, domain_first), domain_first_bits, domain_last_bits, precision
        )
        candidate_last = last_bits_at_most(
            min(upper, DOMAIN_MAX), domain_first_bits, domain_last_bits, precision
        )
        if candidate_first > candidate_last:
            raise SystemExit(f"{precision}/J{order} empty transition band")
        outward_lower = last_bits_at_most(
            max(lower, domain_first), domain_first_bits, domain_last_bits, precision
        )
        outward_upper = first_bits_at_least(
            min(upper, DOMAIN_MAX), domain_first_bits, domain_last_bits, precision
        )

        spans: list[dict[str, Any]] = []
        active: dict[str, Any] | None = None
        for bits in range(candidate_first, candidate_last + 1):
            x = bits_fraction(bits, precision)
            exact_index = reduced_index_exact(x, offset, c)
            floating_index = reduced_index_floating(x, offset, c, p)
            if exact_index not in (k, k + 1) or floating_index not in (k, k + 1):
                raise SystemExit(f"{precision}/J{order} band escaped adjacent indices")
            if exact_index == floating_index:
                if active is not None:
                    spans.append(active)
                    active = None
                continue
            if (
                active is None
                or bits != int(active["last_bits"], 16) + 1
                or exact_index != active["exact_index"]
                or floating_index != active["floating_index"]
            ):
                if active is not None:
                    spans.append(active)
                active = {
                    "first_bits": encoded(bits, width),
                    "last_bits": encoded(bits, width),
                    "count": 1,
                    "exact_index": exact_index,
                    "floating_index": floating_index,
                }
            else:
                active["last_bits"] = encoded(bits, width)
                active["count"] += 1
        if active is not None:
            spans.append(active)

        mismatch_count = sum(span["count"] for span in spans)
        if first_witness is None and spans:
            first = spans[0]
            first_witness = {
                "x_bits": first["first_bits"],
                "x_hex": float(
                    bits_fraction(int(first["first_bits"], 16), precision)
                ).hex(),
                "exact_index": first["exact_index"],
                "floating_index": first["floating_index"],
            }
        candidate_count = candidate_last - candidate_first + 1
        total_candidates += candidate_count
        total_mismatches += mismatch_count
        total_spans += len(spans)
        bands.append(
            {
                "k": k,
                "lower_numerator": str(lower * common_denominator),
                "upper_numerator": str(upper * common_denominator),
                "outward_lower_bits": encoded(outward_lower, width),
                "outward_upper_bits": encoded(outward_upper, width),
                "candidate_first_bits": encoded(candidate_first, width),
                "candidate_last_bits": encoded(candidate_last, width),
                "candidate_count": candidate_count,
                "allowed_indices": [k, k + 1],
                "mismatch_count": mismatch_count,
                "mismatch_spans": spans,
            }
        )
    if first_witness is None:
        raise SystemExit(f"{precision}/J{order} expected mismatch witness missing")

    rho = (Fraction(1, 2) + eta) / c + 653 * abs(Fraction(1, 1) / c - split)
    return {
        "precision": precision,
        "order": order,
        "domain": {
            "first_bits": encoded(domain_first_bits, width),
            "last_bits": encoded(domain_last_bits, width),
            "first_value": rational(domain_first),
            "last_value": rational(DOMAIN_MAX),
        },
        "parameters": {
            "offset": rational(offset),
            "two_over_pi": rational(c),
            "accepted_eta": rational(eta),
            "accepted_eta_hex": cfg["etas"][order],
            "split_pio2": rational(split),
            "index_abs_bound": 653,
            "shadow_reduction_radius": rational(rho),
        },
        "partition": {
            "common_endpoint_denominator": str(common_denominator),
            "transition_band_count": len(bands),
            "stable_interior_count": len(bands) + 1,
            "candidate_count": total_candidates,
            "mismatch_count": total_mismatches,
            "mismatch_span_count": total_spans,
            "first_mismatch_witness": first_witness,
            "domain_edge_separation": {
                "preceding_band_k": first_index - 1,
                "preceding_band_upper": rational(preceding_upper),
                "lower_gap": rational(domain_first - preceding_upper),
                "following_band_k": last_index,
                "following_band_lower": rational(following_lower),
                "upper_gap": rational(following_lower - DOMAIN_MAX),
            },
            "bands": bands,
        },
    }


def generate() -> dict[str, Any]:
    implementation_sha = hashlib.sha256(IMPLEMENTATION.read_bytes()).hexdigest()
    generator_sha = hashlib.sha256(GENERATOR.read_bytes()).hexdigest()
    cases = [
        case_partition(precision, order)
        for precision in ("f32", "f64")
        for order in (0, 1)
    ]
    return {
        "schema_version": "futhark-bessel.adjacent-reduction-bands.v1",
        "status": "EXACT_RATIONAL_TRANSITION_PARTITION_PROVED",
        "scope": {
            "domain": "representable x with switch < x <= 1024",
            "transition_bands": 2584,
            "distinction": (
                "These are floating source-reduction transition bands, not the "
                "2,584 canonical exact-real cell boundaries in the separate "
                "approximation ledger."
            ),
            "stable_interiors": (
                "Because accepted_eta < 1/4, bands about consecutive half-integer "
                "preimages are disjoint. Outside their union, z and zhat lie in "
                "the same roundTiesToEven integer cell, hence m=n."
            ),
            "inside_bands": (
                "For B_k, both n=RNEint(z) and m=RNEint(zhat) belong to {k,k+1}."
            ),
        },
        "authority": {
            "implementation_source": str(IMPLEMENTATION),
            "implementation_sha256": implementation_sha,
            "generator": str(GENERATOR),
            "generator_sha256": generator_sha,
            "arithmetic": "exact Python fractions and exact IEEE bit decoding",
        },
        "cases": cases,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--write", action="store_true")
    action.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = json.dumps(generate(), separators=(",", ":"), sort_keys=True) + "\n"
    if args.write:
        OUTPUT.write_text(rendered)
        print(f"wrote {OUTPUT} ({len(rendered.encode())} bytes)")
    elif not OUTPUT.exists() or OUTPUT.read_text() != rendered:
        raise SystemExit(
            "adjacent reduction band authority is stale; run "
            "scripts/adjacent_reduction_bands.py --write"
        )
    else:
        print("OK 2,584 exact-rational floating transition bands")


if __name__ == "__main__":
    main()
