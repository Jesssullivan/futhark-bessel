#!/usr/bin/env python3
# SPDX-License-Identifier: ISC
"""Check source-graph floating-point error bounds.

This is deliberately not a backend proof.  It analyzes the written Futhark
operation order under the primitive semantics declared in the emitted record.
The adjacent reduction-cell theorem is independently certified and composed
here.  Backend lowering equivalence and root arithmetic remain separate,
fail-closed obligations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

IMPLEMENTATION = Path(
    "lib/github.com/Jesssullivan/futhark-bessel/bessel_internal.fut"
)
ANALYZER = Path("scripts/floating_point_analysis.py")
EXACT_REAL = Path("evidence/real-approximation-bounds.json")
ADJACENT_PROOF = Path("evidence/adjacent-composition-proof.json")
TRANSITION_BANDS = Path("evidence/adjacent-reduction-bands.json")
OUTPUT = Path("evidence/floating-point-analysis.json")
EXPECTED_IMPLEMENTATION_SHA256 = (
    "2b459fb3e24e82a825db5f44cc8b3ebe9c8387d598235f84c4e80996b4e7d9d1"
)


@dataclass(frozen=True)
class State:
    """Magnitude and absolute-error bounds against the exact source graph."""

    real: Fraction
    floating: Fraction
    error: Fraction


@dataclass(frozen=True)
class Format:
    name: str
    precision: int
    min_subnormal_exponent: int
    maximum_finite_hex: str

    @property
    def unit_roundoff(self) -> Fraction:
        return Fraction(1, 1 << self.precision)

    @property
    def half_min_subnormal(self) -> Fraction:
        return Fraction(1, 1 << (-self.min_subnormal_exponent + 1))


FORMATS = {
    "f32": Format("f32", 24, -149, "0x1.fffffep+127"),
    "f64": Format("f64", 53, -1074, "0x1.fffffffffffffp+1023"),
}

CONFIGS: dict[str, dict[str, Any]] = {
    "f32": {
        "switch": Fraction(6),
        "series_iterations": 48,
        "hankel_iterations": 7,
        "two_over_pi": "0x1.45f306p-1",
        "pio2": ("0x1.9218p+0", "0x1.ed511p-14", "0x1.68c234p-39"),
        "pi": "0x1.921fb6p+1",
        "offsets": ("0x1.921fb6p-1", "0x1.2d97c8p+1"),
        "sin_denominators": (6, 120, 5040, 362880),
        "cos_denominators": (2, 24, 720, 40320, 3628800),
        "reduced_bounds": (
            "0x1.922522d077670p-1",
            "0x1.922522d077670p-1",
        ),
    },
    "f64": {
        "switch": Fraction(12),
        "series_iterations": 96,
        "hankel_iterations": 12,
        "two_over_pi": "0x1.45f306dc9c883p-1",
        "pio2": (
            "0x1.921fb54000000p+0",
            "0x1.10b4611a62633p-30",
            "0x1.45c06e0e68948p-86",
        ),
        "pi": "0x1.921fb54442d18p+1",
        "offsets": ("0x1.921fb54442d18p-1", "0x1.2d97c7f3321d2p+1"),
        "sin_denominators": (6, 120, 5040, 362880, 39916800, 6227020800),
        "cos_denominators": (2, 24, 720, 40320, 3628800, 479001600),
        "reduced_bounds": (
            "0x1.921fb54442f54p-1",
            "0x1.921fb54442f54p-1",
        ),
    },
}


def exact_hex(text: str) -> Fraction:
    return Fraction(*float.fromhex(text).as_integer_ratio())


def exact(value: int | Fraction) -> State:
    magnitude = abs(Fraction(value))
    return State(magnitude, magnitude, Fraction(0))


def rounded_error(fmt: Format, magnitude: Fraction) -> Fraction:
    # This covers normal and gradual-underflow results under RN-even.  Overflow
    # is ruled out independently from the recorded maximum-intermediate bound.
    return fmt.unit_roundoff * magnitude + fmt.half_min_subnormal


def add(fmt: Format, left: State, right: State) -> State:
    real = left.real + right.real
    pre = left.floating + right.floating
    rounding = rounded_error(fmt, pre)
    return State(real, pre + rounding, left.error + right.error + rounding)


def mul(fmt: Format, left: State, right: State) -> State:
    real = left.real * right.real
    pre = left.floating * right.floating
    propagated = left.error * right.real + left.floating * right.error
    rounding = rounded_error(fmt, pre)
    return State(real, pre + rounding, propagated + rounding)


def div_exact(fmt: Format, numerator: State, denominator: Fraction) -> State:
    if denominator <= 0:
        raise ValueError("positive exact denominator required")
    real = numerator.real / denominator
    pre = numerator.floating / denominator
    rounding = rounded_error(fmt, pre)
    return State(real, pre + rounding, numerator.error / denominator + rounding)


def constant_fraction(fmt: Format, numerator: int, denominator: int) -> State:
    return div_exact(fmt, exact(numerator), Fraction(denominator))


def upward_float_hex(value: Fraction) -> str:
    candidate = float(value)
    if not math.isfinite(candidate):
        raise SystemExit("analysis bound cannot be represented as finite binary64")
    if Fraction(*candidate.as_integer_ratio()) < value:
        candidate = math.nextafter(candidate, math.inf)
    return candidate.hex()


def power_of_two_sqrt_upper(value: Fraction) -> Fraction:
    """Return an exact power-of-two upper bound on sqrt(value)."""

    if value == 0:
        return Fraction(0)
    exponent = value.numerator.bit_length() - value.denominator.bit_length()
    while Fraction(2) ** (2 * exponent) < value:
        exponent += 1
    while Fraction(2) ** (2 * (exponent - 1)) >= value:
        exponent -= 1
    return Fraction(2) ** exponent


def series_bound(fmt: Format, order: int) -> tuple[State, Fraction]:
    cfg = CONFIGS[fmt.name]
    x = exact(cfg["switch"])
    squared = mul(fmt, x, x)
    z = div_exact(fmt, squared, Fraction(4))
    maximum = max(squared.floating, z.floating)
    if order == 0:
        term = exact(1)
        total = exact(1)
    else:
        term = div_exact(fmt, x, Fraction(2))
        total = term
        maximum = max(maximum, term.floating)
    for k in range(cfg["series_iterations"]):
        first = k + 1
        second = k + 1 + order
        product = mul(fmt, term, z)
        term = div_exact(fmt, product, Fraction(first * second))
        total = add(fmt, total, term)
        maximum = max(maximum, product.floating, term.floating, total.floating)
    return total, maximum


def taylor_bound(fmt: Format, r: State, sine: bool) -> tuple[State, Fraction]:
    """Mirror the source Horner graph, including its final z/division forms."""

    z = mul(fmt, r, r)
    denoms = CONFIGS[fmt.name]["sin_denominators" if sine else "cos_denominators"]
    signs = [(-1 if index % 2 == 0 else 1) for index in range(len(denoms))]

    # The source normally writes the final term as z/denominator.  f32 cosine
    # instead writes z*(-1/denominator), so preserve that distinct graph.
    if fmt.name == "f32" and not sine:
        final_term = mul(
            fmt, z, constant_fraction(fmt, signs[-1], denoms[-1])
        )
    else:
        final_term = div_exact(fmt, z, Fraction(denoms[-1]))
    inner = add(
        fmt,
        constant_fraction(fmt, signs[-2], denoms[-2]),
        final_term,
    )
    maximum = max(z.floating, inner.floating)
    for sign, denominator in reversed(list(zip(signs[:-2], denoms[:-2], strict=True))):
        product = mul(fmt, z, inner)
        inner = add(fmt, constant_fraction(fmt, sign, denominator), product)
        maximum = max(maximum, product.floating, inner.floating)
    product = mul(fmt, z, inner)
    polynomial = add(fmt, exact(1), product)
    result = mul(fmt, r, polynomial) if sine else polynomial
    maximum = max(maximum, product.floating, polynomial.floating, result.floating)
    return result, maximum


def reduction_bound(
    fmt: Format, order: int, shadow_radius: Fraction
) -> tuple[State, Fraction, Fraction]:
    """Bound rounding against the exact shadow graph for either adjacent index."""

    cfg = CONFIGS[fmt.name]
    x = exact(Fraction(1024))
    offset_value = exact_hex(cfg["offsets"][order])
    offset = exact(offset_value)
    exact_index_upper = math.ceil(
        (Fraction(1024) - offset_value) * exact_hex(cfg["two_over_pi"])
        + Fraction(1, 2)
    )
    if exact_index_upper > 653:
        raise SystemExit(f"{fmt.name}/J{order} range-reduction index bound drifted")
    phase = add(fmt, x, offset)  # subtraction has the same magnitude/error law
    product = mul(fmt, phase, exact(exact_hex(cfg["two_over_pi"])))
    maximum = max(phase.floating, product.floating)

    # Exact index equality is false.  The adjacent theorem independently proves
    # that the source-selected shadow index has |n| <= 653 and that its exact
    # reduced argument is bounded by shadow_radius.
    n = exact(653)
    current = phase
    for component in cfg["pio2"]:
        n_component = mul(fmt, n, exact(exact_hex(component)))
        current = add(fmt, current, n_component)
        maximum = max(maximum, n_component.floating, current.floating)

    r = State(
        shadow_radius,
        shadow_radius + current.error,
        current.error,
    )
    return r, max(maximum, r.floating), product.error


def hankel_bound(fmt: Format, order: int) -> tuple[State, State, Fraction]:
    cfg = CONFIGS[fmt.name]
    x_min = cfg["switch"]
    coefficient = exact(1)
    invpow = exact(1)
    p = exact(1)
    q = exact(0)
    maximum = Fraction(1)
    for m in range(1, cfg["hankel_iterations"] + 1):
        numerator = 4 * order * order - (2 * m - 1) ** 2
        coefficient_product = mul(fmt, coefficient, exact(abs(numerator)))
        coefficient = div_exact(fmt, coefficient_product, Fraction(8 * m))
        invpow = div_exact(fmt, invpow, x_min)
        term = mul(fmt, coefficient, invpow)
        if m % 2 == 0:
            p = add(fmt, p, term)
        else:
            q = add(fmt, q, term)
        maximum = max(
            maximum,
            coefficient_product.floating,
            coefficient.floating,
            invpow.floating,
            term.floating,
            p.floating,
            q.floating,
        )
    return p, q, maximum


def prefactor_bound(fmt: Format) -> tuple[State, Fraction]:
    cfg = CONFIGS[fmt.name]
    pi = exact_hex(cfg["pi"])
    x_min = cfg["switch"]
    x_max = Fraction(1024)

    # t = fl(pi*x).  Its error is bounded at x_max; its positive lower bound
    # controls the reciprocal sensitivity for every x in the branch.
    t_real_max = pi * x_max
    t_round = rounded_error(fmt, t_real_max)
    t_fp_max = t_real_max + t_round
    t_real_min = pi * x_min
    t_fp_min = t_real_min - t_round
    if t_fp_min <= 0:
        raise SystemExit(f"{fmt.name} prefactor denominator lost positivity")

    reciprocal_real_max = Fraction(2) / t_real_min
    reciprocal_pre_max = Fraction(2) / t_fp_min
    reciprocal_round = rounded_error(fmt, reciprocal_pre_max)
    reciprocal_fp_max = reciprocal_pre_max + reciprocal_round
    reciprocal_error = (
        Fraction(2) * t_round / (t_fp_min * t_real_min) + reciprocal_round
    )

    # Correctly rounded sqrt contributes one primitive rounding.  The
    # sqrt-Hoelder inequality avoids importing a transcendental interval tool:
    # |sqrt(a)-sqrt(b)| <= sqrt(|a-b|).
    propagated = power_of_two_sqrt_upper(reciprocal_error)
    sqrt_fp_upper = power_of_two_sqrt_upper(reciprocal_fp_max)
    sqrt_round = rounded_error(fmt, sqrt_fp_upper)
    state = State(
        power_of_two_sqrt_upper(reciprocal_real_max),
        sqrt_fp_upper + sqrt_round,
        propagated + sqrt_round,
    )
    return state, max(t_fp_max, reciprocal_fp_max, state.floating)


def asymptotic_bound(
    fmt: Format, order: int, shadow_radius: Fraction
) -> tuple[State, Fraction, Fraction]:
    r, reduction_max, reduction_product_error = reduction_bound(
        fmt, order, shadow_radius
    )
    sine, sine_max = taylor_bound(fmt, r, True)
    cosine, cosine_max = taylor_bound(fmt, r, False)
    # Quadrant selection can exchange sine/cosine.  Use a shared component
    # bound so all four exact-sign permutations are covered.
    trig = State(
        max(sine.real, cosine.real),
        max(sine.floating, cosine.floating),
        max(sine.error, cosine.error),
    )
    p, q, hankel_max = hankel_bound(fmt, order)
    cp = mul(fmt, trig, p)
    sq = mul(fmt, trig, q)
    combination = add(fmt, cp, sq)  # subtraction has the same bound
    prefactor, prefactor_max = prefactor_bound(fmt)
    result = mul(fmt, prefactor, combination)
    maximum = max(
        reduction_max,
        sine_max,
        cosine_max,
        hankel_max,
        cp.floating,
        sq.floating,
        combination.floating,
        prefactor_max,
        result.floating,
    )
    return result, maximum, reduction_product_error


def verify_source() -> tuple[str, dict[str, str]]:
    source = IMPLEMENTATION.read_text()
    digest = hashlib.sha256(source.encode()).hexdigest()
    if digest != EXPECTED_IMPLEMENTATION_SHA256:
        raise SystemExit(
            "floating-point source graph changed; re-review the analysis before "
            "updating EXPECTED_IMPLEMENTATION_SHA256"
        )
    required = {
        "f32": (
            "for k < 48 do",
            "for k < 7 do",
            "if y <= 6.0",
            "let r = ((phase - nf * pio2_hi) - nf * pio2_lo) - nf * pio2_tail",
        ),
        "f64": (
            "for k < 96 do",
            "for k < 12 do",
            "if y <= 12.0",
            "let r = ((phase - nf * pio2_hi) - nf * pio2_lo) - nf * pio2_tail",
        ),
    }
    module_hashes: dict[str, str] = {}
    for precision in ("f32", "f64"):
        match = re.search(
            rf"module {precision}_impl = \{{(?P<body>.*?)(?=^\}}(?:\n|$))",
            source,
            flags=re.MULTILINE | re.DOTALL,
        )
        if match is None:
            raise SystemExit(f"cannot locate {precision} source graph")
        body = match.group("body")
        for fragment in required[precision]:
            if fragment not in body:
                raise SystemExit(f"{precision} source graph drifted: {fragment}")
        module_hashes[precision] = hashlib.sha256(body.encode()).hexdigest()
    return digest, module_hashes


def load_adjacent_proof(implementation_sha: str) -> dict[str, Any]:
    proof_raw = ADJACENT_PROOF.read_bytes()
    proof = json.loads(proof_raw)
    if proof.get("schema_version") != (
        "futhark-bessel.adjacent-composition-proof.v1"
    ):
        raise SystemExit("unexpected adjacent composition proof schema")
    if proof.get("status") != "ADJACENT_REDUCTION_COMPOSITION_PROVED":
        raise SystemExit("adjacent reduction composition is not proved")
    if proof.get("release_implications") != {
        "adjacent_source_reduction_composition": "PROVED",
        "backend_lowering_equivalence": "OPEN",
        "overall_release_status": "INCOMPLETE",
        "solver_mathematical_root_ulp_and_true_residual": "OPEN",
    }:
        raise SystemExit("adjacent proof release implications drifted")
    authority = proof.get("authority", {})
    expected_files = {
        "transition_bands": TRANSITION_BANDS,
        "transition_generator": Path("scripts/adjacent_reduction_bands.py"),
        "certifier_source": Path("oracle/adjacent_composition.c"),
        "independent_verifier": Path("scripts/adjacent_composition_proof.py"),
        "exact_real_evidence": Path("evidence/real-approximation-bounds.json"),
    }
    if (
        authority.get("implementation_source") != str(IMPLEMENTATION)
        or authority.get("implementation_sha256") != implementation_sha
    ):
        raise SystemExit("adjacent proof implementation authority drifted")
    for field, path in expected_files.items():
        if authority.get(field) != str(path):
            raise SystemExit(f"adjacent proof {field} path drifted")
        if authority.get(f"{field}_sha256") != hashlib.sha256(
            path.read_bytes()
        ).hexdigest():
            raise SystemExit(f"adjacent proof {field} hash drifted")
    if (
        authority.get("certificate_rows") != 36
        or authority.get("certifier") != "FLINT/Arb 3.6.0 at 1024-bit precision"
        or authority.get("independent_verifier_runtime")
        != "mpmath 1.4.1 at 180 decimal digits"
    ):
        raise SystemExit("adjacent proof certificate authority drifted")
    census = proof.get("transition_census", {})
    if sum(
        census.get(precision, {}).get(f"j{order}", {}).get(
            "transition_band_count", 0
        )
        for precision in ("f32", "f64")
        for order in (0, 1)
    ) != 2584:
        raise SystemExit("adjacent proof floating transition-band census drifted")
    return proof


def validate_exact_real(
    exact_real: dict[str, Any], implementation_sha: str
) -> None:
    expected_scope = {
        "covered": (
            "series and Hankel truncation, phase constants, exhaustive "
            "rounding-cell partition, Taylor truncation, prefactor constant, "
            "switch points, and domain endpoints"
        ),
        "excluded": (
            "backend floating-point rounding, contraction, and reassociation"
        ),
        "input_domain": "real x with |x| <= 1024",
        "semantic_model": (
            "source binary literals are exact dyadic reals and arithmetic "
            "operations are over the reals"
        ),
    }
    if exact_real.get("schema_version") != (
        "futhark-bessel.real-approximation-bounds.v1"
    ):
        raise SystemExit("unexpected exact-real evidence schema")
    if exact_real.get("status") != "CERTIFIED_EXACT_REAL_WHOLE_DOMAIN":
        raise SystemExit("exact-real authority is not certified")
    if exact_real.get("scope") != expected_scope:
        raise SystemExit("exact-real evidence scope drifted")
    authority = exact_real.get("authority", {})
    if authority.get("implementation_source") != str(IMPLEMENTATION):
        raise SystemExit("exact-real implementation source is not bound")
    if authority.get("implementation_sha256") != implementation_sha:
        raise SystemExit("exact-real implementation SHA is not bound")
    partitions = exact_real.get("range_reduction_partitions", {})
    for precision in ("f32", "f64"):
        for order in (0, 1):
            partition = partitions.get(precision, {}).get(f"j{order}", {})
            if partition.get("reduced_argument_absolute_upper_hex") != (
                CONFIGS[precision]["reduced_bounds"][order]
            ):
                raise SystemExit(
                    f"{precision}/J{order} reduced-argument authority drifted"
                )
            if partition.get("tie_policy") != (
                "both adjacent quadrants certified"
            ):
                raise SystemExit(f"{precision}/J{order} tie policy drifted")


def generate() -> dict[str, Any]:
    implementation_sha, module_hashes = verify_source()
    exact_real = json.loads(EXACT_REAL.read_text())
    validate_exact_real(exact_real, implementation_sha)
    adjacent_proof = load_adjacent_proof(implementation_sha)
    results: dict[str, Any] = {}
    reduction_evidence: dict[str, Any] = {}
    transition_document = json.loads(TRANSITION_BANDS.read_text())
    transition_cases = {
        (case.get("precision"), case.get("order")): case
        for case in transition_document.get("cases", [])
    }
    if set(transition_cases) != {
        (precision, order)
        for precision in ("f32", "f64")
        for order in (0, 1)
    }:
        raise SystemExit("floating transition-band cases drifted")
    maximum_intermediate = Fraction(0)
    for precision, fmt in FORMATS.items():
        results[precision] = {}
        reduction_evidence[precision] = {}
        cfg = CONFIGS[precision]
        source_scalar_maximum = Fraction(
            max(
                1024,
                *cfg["sin_denominators"],
                *cfg["cos_denominators"],
                cfg["series_iterations"]
                * (cfg["series_iterations"] + 1),
                8 * cfg["hankel_iterations"],
            )
        )
        for order in (0, 1):
            name = f"j{order}"
            adjacent_bound = adjacent_proof.get("bounds", {}).get(
                precision, {}
            ).get(name, {})
            shadow_radius = exact_hex(
                adjacent_bound.get("shadow_reduction_radius_upper_hex", "nan")
            )
            series, series_max = series_bound(fmt, order)
            asymptotic, asymptotic_max, reduction_product_error = asymptotic_bound(
                fmt, order, shadow_radius
            )
            accepted_product_error = adjacent_bound.get(
                "accepted_product_error_upper_hex"
            )
            if (
                accepted_product_error != upward_float_hex(reduction_product_error)
                or exact_hex(accepted_product_error) >= Fraction(1, 4)
            ):
                raise SystemExit(
                    f"{precision}/J{order} accepted transition-band eta drifted"
                )
            census = adjacent_proof.get("transition_census", {}).get(
                precision, {}
            ).get(name, {})
            transition_case = transition_cases[(precision, order)]
            first = transition_case.get("partition", {}).get(
                "first_mismatch_witness", {}
            )
            if first.get("exact_index") == first.get("floating_index"):
                raise SystemExit(f"{precision}/J{order} mismatch witness drifted")
            reduction_evidence[precision][name] = {
                "status": "EXACT_INDEX_EQUALITY_FALSIFIED",
                "composition_status": "ADJACENT_REDUCTION_COMPOSITION_PROVED",
                "method": (
                    "complete exact-rational disjoint transition-band partition; "
                    "all in-band IEEE candidates and complete mismatch bit spans"
                ),
                "accepted_product_error_upper_hex": accepted_product_error,
                "index_difference_abs_upper": 1,
                "transition_band_count": census.get("transition_band_count"),
                "stable_interior_count": census.get("stable_interior_count"),
                "candidate_count": census.get("candidate_count"),
                "mismatch_count": census.get("mismatch_count"),
                "mismatch_span_count": census.get("mismatch_span_count"),
                "first_witness": {
                    "x_bits": first.get("x_bits"),
                    "x_hex": first.get("x_hex"),
                    "exact_real_index": first.get("exact_index"),
                    "floating_index": first.get("floating_index"),
                },
                "shadow_reduction_radius_upper_hex": adjacent_bound.get(
                    "shadow_reduction_radius_upper_hex"
                ),
                "transition_band_authority_sha256": adjacent_proof.get(
                    "authority", {}
                ).get("transition_bands_sha256"),
                "adjacent_only_proof": (
                    "accepted eta is less than 1/4; outside the disjoint bands "
                    "m=n, and inside B_k both indices lie in {k,k+1}."
                ),
                "stable_interior_proof": (
                    "Every point outside the closed transition bands lies in "
                    "one common roundTiesToEven integer cell for z and zhat."
                ),
            }
            maximum = max(series_max, asymptotic_max, source_scalar_maximum)
            maximum_intermediate = max(maximum_intermediate, maximum)
            if maximum >= exact_hex(fmt.maximum_finite_hex):
                raise SystemExit(f"{precision}/J{order} finite-intermediate proof failed")
            exact_real_bound = exact_real.get("bounds", {}).get(
                precision, {}
            ).get(name, {})
            series_math = exact_hex(
                exact_real_bound.get("series_absolute_error_upper_hex", "nan")
            )
            shadow_math = exact_hex(
                adjacent_bound.get("shadow_math_absolute_error_upper_hex", "nan")
            )
            results[precision][name] = {
                "series": {
                    "status": "PROVED_UNDER_DECLARED_PRIMITIVE_SEMANTICS",
                    "domain": (
                        f"finite IEEE {precision} inputs with |x| <= "
                        f"{CONFIGS[precision]['switch']}"
                    ),
                    "absolute_rounding_error_upper_hex": upward_float_hex(series.error),
                    "mathematical_approximation_error_upper_hex": (
                        exact_real_bound.get("series_absolute_error_upper_hex")
                    ),
                    "absolute_source_error_upper_hex": upward_float_hex(
                        series.error + series_math
                    ),
                },
                "asymptotic": {
                    "status": "PROVED_UNDER_DECLARED_PRIMITIVE_SEMANTICS",
                    "domain": (
                        f"finite IEEE {precision} inputs with "
                        f"{CONFIGS[precision]['switch']} < |x| <= 1024"
                    ),
                    "absolute_rounding_error_upper_hex": upward_float_hex(asymptotic.error),
                    "shadow_math_approximation_error_upper_hex": adjacent_bound.get(
                        "shadow_math_absolute_error_upper_hex"
                    ),
                    "absolute_source_error_upper_hex": upward_float_hex(
                        asymptotic.error + shadow_math
                    ),
                    "shadow_reduction_radius_upper_hex": adjacent_bound.get(
                        "shadow_reduction_radius_upper_hex"
                    ),
                    "adjacent_quadrant_certificate_rows": adjacent_bound.get(
                        "adjacent_quadrant_certificate_rows"
                    ),
                },
                "maximum_intermediate_magnitude_upper_hex": upward_float_hex(maximum),
            }
    analyzer_sha = hashlib.sha256(ANALYZER.read_bytes()).hexdigest()
    exact_real_sha = hashlib.sha256(EXACT_REAL.read_bytes()).hexdigest()
    return {
        "schema_version": "futhark-bessel.floating-point-analysis.v2",
        "status": "SOURCE_EVALUATION_PROVED_BACKEND_LOWERING_OPEN",
        "release_conformance": False,
        "scope": {
            "covered": (
                "written Futhark J0/J1 source-operation order, including "
                "gradual-underflow absolute error terms, finite intermediates, "
                "the complete adjacent reduction partition, all quadrant maps, "
                "and composition with mathematical approximation bounds"
            ),
            "excluded": (
                "backend lowering equivalence, contraction/reassociation, root "
                "solver mathematical-root ULP/true-residual envelopes, and "
                "runtime conformance"
            ),
            "composition_with_exact_real_bound": (
                "PROVED_VIA_SHADOW_INDEX_ADJACENT_QUADRANT_COMPOSITION"
            ),
        },
        "authority": {
            "implementation_source": str(IMPLEMENTATION),
            "implementation_sha256": implementation_sha,
            "module_body_sha256": module_hashes,
            "analyzer": str(ANALYZER),
            "analyzer_sha256": analyzer_sha,
            "exact_real_evidence": str(EXACT_REAL),
            "exact_real_evidence_sha256": exact_real_sha,
            "adjacent_composition_proof": str(ADJACENT_PROOF),
            "adjacent_composition_proof_sha256": hashlib.sha256(
                ADJACENT_PROOF.read_bytes()
            ).hexdigest(),
            "transition_band_authority": str(TRANSITION_BANDS),
            "transition_band_authority_sha256": hashlib.sha256(
                TRANSITION_BANDS.read_bytes()
            ).hexdigest(),
            "arithmetic": (
                "exact Python fractions; binary64 is used only to encode outward "
                "summary bounds"
            ),
        },
        "declared_primitive_semantics": {
            "inputs_and_binary_literals": "exact IEEE values",
            "add_subtract_multiply_divide": (
                "one IEEE-754 roundTiesToEven operation in the named precision, "
                "gradual underflow, no contraction"
            ),
            "sqrt": "correctly rounded IEEE-754 roundTiesToEven in the named precision",
            "round": (
                "nearest integral value with ties to even; conversion to i32 is "
                "exact for the proven index range"
            ),
            "evaluation_order": (
                "strict written source tree; no reassociation or "
                "common-subexpression rewrite"
            ),
            "per_operation_error_model": "|fl(y)-y| <= u*|y| + half_min_subnormal",
        },
        "source_graph_results": results,
        "range_reduction_index_analysis": reduction_evidence,
        "proved_auxiliary_bounds": {
            "range_reduction_index_abs_upper": 653,
            "finite_intermediates": True,
        },
        "maximum_intermediate_magnitude_upper_hex": upward_float_hex(maximum_intermediate),
        "closed_obligations": [
            {
                "id": "FP-ADJACENT-REDUCTION-COMPOSITION",
                "status": "PROVED",
                "statement": (
                    "Every exact-rational floating transition band, both "
                    "adjacent selected quadrants, the shadow radius, and the "
                    "Taylor/phase/Hankel composition are certified."
                ),
            }
        ],
        "open_obligations": [
            {
                "id": "FP-ROOT-SOLVER-MATHEMATICAL-ROOT-ENVELOPES",
                "status": "OPEN",
                "statement": (
                    "Bind the separately proved bracketed root-solver source "
                    "graph to solver-output mathematical-root ULP and true-"
                    "residual envelopes."
                ),
            },
            {
                "id": "FP-BACKEND-LOWERING-C",
                "status": "OPEN",
                "statement": (
                    "Pinned Futhark C lowering and compiler flags implement one "
                    "analyzed operation graph and the declared primitive semantics."
                ),
            },
            {
                "id": "FP-BACKEND-LOWERING-WASM",
                "status": "OPEN",
                "statement": (
                    "Pinned Futhark/Emscripten WASM lowering implements one analyzed "
                    "operation graph and the declared primitive semantics."
                ),
            },
            {
                "id": "FP-BACKEND-LOWERING-WEBGPU",
                "status": "OPEN",
                "statement": (
                    "Pinned WebGPU lowering, shader compiler, adapter, and runtime "
                    "implement one analyzed f32 operation graph and primitive semantics."
                ),
            },
        ],
        "release_implication": (
            "BLOCKED; source-graph evaluation proofs are not backend-lowering "
            "proofs or release envelopes, and solver mathematical-root "
            "envelopes remain open"
        ),
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
            "floating-point analysis is stale; run "
            "scripts/floating_point_analysis.py --write"
        )
    print(
        "OK source evaluation and adjacent composition bounds; release remains "
        "BLOCKED on backend lowering and solver mathematical-root envelopes"
    )


if __name__ == "__main__":
    main()
