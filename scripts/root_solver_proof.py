#!/usr/bin/env python3
# SPDX-License-Identifier: ISC
"""Prove the written positive-J1-root solver source graph on indices 1..256.

This checker is deliberately narrower than a release envelope.  It interprets
the bound Futhark source graph with exact rationals and explicit IEEE-754
roundTiesToEven after every written primitive operation.  It proves bracketing,
progress, stopping, result-record construction, and reported-residual semantics
for f32 and f64.  It does not prove proximity to the mathematical J1 roots and
does not make any claim about backend lowering or runtime behavior.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

IMPLEMENTATION = Path(
    "lib/github.com/Jesssullivan/futhark-bessel/bessel_internal.fut"
)
ANALYZER = Path("scripts/root_solver_proof.py")
OUTPUT = Path("evidence/root-solver-arithmetic.json")

EXPECTED_IMPLEMENTATION_SHA256 = (
    "2b459fb3e24e82a825db5f44cc8b3ebe9c8387d598235f84c4e80996b4e7d9d1"
)
EXPECTED_MODULE_SHA256 = {
    "f32": "9535debcc50d3efebbdbcae34641a712c7406ed5531e06aa431048bc349a9ebe",
    "f64": "8c9170a38e1b51529574d3c098ee1f1e2ac312a2304eff9dcf4c8367f1fe9885",
}
ROOT_COUNT = 256


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@lru_cache(maxsize=None)
def power_of_two(exponent: int) -> Fraction:
    if exponent >= 0:
        return Fraction(1 << exponent)
    return Fraction(1, 1 << -exponent)


def floor_log2(value: Fraction) -> int:
    if value <= 0:
        raise ValueError("floor_log2 requires a positive rational")
    exponent = value.numerator.bit_length() - value.denominator.bit_length()
    if power_of_two(exponent) > value:
        exponent -= 1
    elif power_of_two(exponent + 1) <= value:
        exponent += 1
    return exponent


def round_nonnegative_integer(value: Fraction) -> int:
    """Round a nonnegative rational to the nearest integer, ties to even."""

    if value < 0:
        raise ValueError("nonnegative value required")
    quotient, remainder = divmod(value.numerator, value.denominator)
    twice = 2 * remainder
    if twice < value.denominator:
        return quotient
    if twice > value.denominator:
        return quotient + 1
    return quotient if quotient % 2 == 0 else quotient + 1


@dataclass(frozen=True)
class BinaryFormat:
    name: str
    width: int
    precision: int
    exponent_bits: int
    exponent_bias: int
    minimum_normal_exponent: int
    maximum_normal_exponent: int

    @property
    def fraction_bits(self) -> int:
        return self.precision - 1

    @property
    def sign_mask(self) -> int:
        return 1 << (self.width - 1)

    @property
    def fraction_mask(self) -> int:
        return (1 << self.fraction_bits) - 1

    @property
    def exponent_mask(self) -> int:
        return ((1 << self.exponent_bits) - 1) << self.fraction_bits

    @property
    def infinity_bits(self) -> int:
        return self.exponent_mask

    @property
    def minimum_subnormal_exponent(self) -> int:
        return self.minimum_normal_exponent - self.fraction_bits

    @property
    def maximum_finite(self) -> Fraction:
        significand = Fraction((1 << self.precision) - 1, 1 << self.fraction_bits)
        return significand * power_of_two(self.maximum_normal_exponent)

    def is_finite(self, bits: int) -> bool:
        return bits & self.exponent_mask != self.exponent_mask

    def is_zero(self, bits: int) -> bool:
        return bits & ~self.sign_mask == 0

    @lru_cache(maxsize=None)
    def fraction(self, bits: int) -> Fraction:
        if not self.is_finite(bits):
            raise ValueError(f"nonfinite {self.name} bit pattern")
        negative = bool(bits & self.sign_mask)
        exponent_field = (bits & self.exponent_mask) >> self.fraction_bits
        fraction_field = bits & self.fraction_mask
        if exponent_field == 0:
            magnitude = Fraction(fraction_field) * power_of_two(
                self.minimum_subnormal_exponent
            )
        else:
            significand = Fraction(
                (1 << self.fraction_bits) + fraction_field,
                1 << self.fraction_bits,
            )
            magnitude = significand * power_of_two(
                exponent_field - self.exponent_bias
            )
        return -magnitude if negative else magnitude

    def round_fraction(self, value: Fraction, *, negative_zero: bool = False) -> int:
        """Correctly round a rational to this binary format."""

        if value == 0:
            return self.sign_mask if negative_zero else 0
        negative = value < 0
        magnitude = abs(value)
        if magnitude > self.maximum_finite + power_of_two(
            self.maximum_normal_exponent - self.precision
        ):
            raise OverflowError(f"{self.name} source graph overflowed")

        exponent = floor_log2(magnitude)
        if exponent < self.minimum_normal_exponent:
            step_exponent = self.minimum_subnormal_exponent
            significand = round_nonnegative_integer(
                magnitude / power_of_two(step_exponent)
            )
            if significand == 0:
                return self.sign_mask if negative else 0
            if significand < 1 << self.fraction_bits:
                bits = significand
            else:
                bits = 1 << self.fraction_bits
        else:
            step_exponent = exponent - self.fraction_bits
            significand = round_nonnegative_integer(
                magnitude / power_of_two(step_exponent)
            )
            if significand == 1 << self.precision:
                significand >>= 1
                exponent += 1
            if exponent > self.maximum_normal_exponent:
                raise OverflowError(f"{self.name} source graph overflowed")
            exponent_field = exponent + self.exponent_bias
            bits = (exponent_field << self.fraction_bits) | (
                significand - (1 << self.fraction_bits)
            )
        return bits | (self.sign_mask if negative else 0)

    @lru_cache(maxsize=None)
    def integer(self, value: int) -> int:
        return self.round_fraction(Fraction(value))

    @lru_cache(maxsize=None)
    def rational(self, numerator: int, denominator: int = 1) -> int:
        return self.round_fraction(Fraction(numerator, denominator))

    @lru_cache(maxsize=None)
    def hexadecimal(self, text: str) -> int:
        # All source literals in this theorem have at most binary64 precision;
        # float.fromhex therefore decodes their exact dyadic value before the
        # explicit target-format rounding below.
        return self.round_fraction(Fraction(*float.fromhex(text).as_integer_ratio()))

    def negate(self, value: int) -> int:
        return value ^ self.sign_mask

    def absolute(self, value: int) -> int:
        return value & ~self.sign_mask

    def add(self, left: int, right: int) -> int:
        result = self.fraction(left) + self.fraction(right)
        both_negative_zero = self.is_zero(left) and self.is_zero(right) and (
            bool(left & self.sign_mask) and bool(right & self.sign_mask)
        )
        return self.round_fraction(result, negative_zero=both_negative_zero)

    def subtract(self, left: int, right: int) -> int:
        return self.add(left, self.negate(right))

    def multiply(self, left: int, right: int) -> int:
        negative = bool((left ^ right) & self.sign_mask)
        result = self.fraction(left) * self.fraction(right)
        return self.round_fraction(result, negative_zero=negative and result == 0)

    def divide(self, numerator: int, denominator: int) -> int:
        if self.is_zero(denominator):
            raise ZeroDivisionError(f"{self.name} source graph divided by zero")
        negative = bool((numerator ^ denominator) & self.sign_mask)
        result = self.fraction(numerator) / self.fraction(denominator)
        return self.round_fraction(result, negative_zero=negative and result == 0)

    def sqrt(self, value: int) -> int:
        exact = self.fraction(value)
        if exact < 0:
            raise ValueError(f"{self.name} source graph sqrt received negative input")
        if exact == 0:
            return value

        exponent = floor_log2(exact) // 2
        step_exponent = exponent - self.fraction_bits
        scaled_square = exact / power_of_two(2 * step_exponent)
        lower = math.isqrt(scaled_square.numerator // scaled_square.denominator)
        while Fraction((lower + 1) ** 2) <= scaled_square:
            lower += 1
        while Fraction(lower**2) > scaled_square:
            lower -= 1
        midpoint_square = Fraction((2 * lower + 1) ** 2, 4)
        if scaled_square < midpoint_square:
            significand = lower
        elif scaled_square > midpoint_square:
            significand = lower + 1
        else:
            significand = lower if lower % 2 == 0 else lower + 1
        return self.round_fraction(
            Fraction(significand) * power_of_two(step_exponent)
        )

    def round_integral(self, value: int) -> int:
        rounded = round_nonnegative_integer(abs(self.fraction(value)))
        if self.fraction(value) < 0:
            rounded = -rounded
        return self.integer(rounded)

    def less(self, left: int, right: int) -> bool:
        return self.fraction(left) < self.fraction(right)

    def less_equal(self, left: int, right: int) -> bool:
        return self.fraction(left) <= self.fraction(right)

    def bits_hex(self, value: int) -> str:
        return f"0x{value:0{self.width // 4}x}"

    def value_hex(self, value: int) -> str:
        exact = self.fraction(value)
        if exact == 0:
            return "-0x0p+0" if value & self.sign_mask else "0x0p+0"
        # This is presentation only.  The exact bit pattern is always recorded.
        return float(exact).hex()


FORMATS = {
    "f32": BinaryFormat("f32", 32, 24, 8, 127, -126, 127),
    "f64": BinaryFormat("f64", 64, 53, 11, 1023, -1022, 1023),
}

CONFIGS: dict[str, dict[str, Any]] = {
    "f32": {
        "series_iterations": 48,
        "hankel_iterations": 7,
        "solver_cap": 48,
        "switch": 6,
        "pi": "0x1.921fb6p+1",
        "two_over_pi": "0x1.45f306p-1",
        "pio2": ("0x1.9218p+0", "0x1.ed511p-14", "0x1.68c234p-39"),
        "phase_offset": "0x1.2d97c8p+1",
        "epsilon": "0x1.0p-23",
        "sin_denominators": (6, 120, 5040, 362880),
        "cos_denominators": (2, 24, 720, 40320, 3628800),
    },
    "f64": {
        "series_iterations": 96,
        "hankel_iterations": 12,
        "solver_cap": 96,
        "switch": 12,
        "pi": "0x1.921fb54442d18p+1",
        "two_over_pi": "0x1.45f306dc9c883p-1",
        "pio2": (
            "0x1.921fb54000000p+0",
            "0x1.10b4611a62633p-30",
            "0x1.45c06e0e68948p-86",
        ),
        "phase_offset": "0x1.2d97c7f3321d2p+1",
        "epsilon": "0x1.0p-52",
        "sin_denominators": (6, 120, 5040, 362880, 39916800, 6227020800),
        "cos_denominators": (2, 24, 720, 40320, 3628800, 479001600),
    },
}


def sign_change(fmt: BinaryFormat, left: int, right: int) -> bool:
    zero = fmt.integer(0)
    return (
        fmt.less_equal(left, zero) and fmt.less_equal(zero, right)
    ) or (
        fmt.less_equal(zero, left) and fmt.less_equal(right, zero)
    )


def j1_series(fmt: BinaryFormat, x: int) -> int:
    cfg = CONFIGS[fmt.name]
    z = fmt.divide(fmt.negate(fmt.multiply(x, x)), fmt.integer(4))
    term = fmt.divide(x, fmt.integer(2))
    total = term
    for k in range(cfg["series_iterations"]):
        k1 = fmt.integer(k + 1)
        k2 = fmt.integer(k + 2)
        term = fmt.divide(
            fmt.multiply(term, z),
            fmt.multiply(k1, k2),
        )
        total = fmt.add(total, term)
    return total


def sincos_reduced(fmt: BinaryFormat, phase: int) -> tuple[int, int]:
    cfg = CONFIGS[fmt.name]
    product = fmt.multiply(phase, fmt.hexadecimal(cfg["two_over_pi"]))
    n_float = fmt.round_integral(product)
    n = int(fmt.fraction(n_float))
    nf = fmt.integer(n)
    reduced = phase
    for component in cfg["pio2"]:
        reduced = fmt.subtract(
            reduced,
            fmt.multiply(nf, fmt.hexadecimal(component)),
        )
    z = fmt.multiply(reduced, reduced)

    sin_denominators = cfg["sin_denominators"]
    sin_inner = fmt.divide(z, fmt.integer(sin_denominators[-1]))
    index = len(sin_denominators) - 2
    sin_inner = fmt.add(
        fmt.rational(-1 if index % 2 == 0 else 1, sin_denominators[index]),
        sin_inner,
    )
    for index in range(len(sin_denominators) - 3, -1, -1):
        coefficient = fmt.rational(
            -1 if index % 2 == 0 else 1,
            sin_denominators[index],
        )
        sin_inner = fmt.add(coefficient, fmt.multiply(z, sin_inner))
    sin_r = fmt.multiply(
        reduced,
        fmt.add(fmt.integer(1), fmt.multiply(z, sin_inner)),
    )

    cos_denominators = cfg["cos_denominators"]
    if fmt.name == "f32":
        cos_inner = fmt.multiply(
            z, fmt.rational(-1, cos_denominators[-1])
        )
    else:
        cos_inner = fmt.divide(z, fmt.integer(cos_denominators[-1]))
    index = len(cos_denominators) - 2
    cos_inner = fmt.add(
        fmt.rational(-1 if index % 2 == 0 else 1, cos_denominators[index]),
        cos_inner,
    )
    for index in range(len(cos_denominators) - 3, -1, -1):
        coefficient = fmt.rational(
            -1 if index % 2 == 0 else 1,
            cos_denominators[index],
        )
        cos_inner = fmt.add(coefficient, fmt.multiply(z, cos_inner))
    cos_r = fmt.add(fmt.integer(1), fmt.multiply(z, cos_inner))

    quadrant = ((n % 4) + 4) % 4
    if quadrant == 0:
        return sin_r, cos_r
    if quadrant == 1:
        return cos_r, fmt.negate(sin_r)
    if quadrant == 2:
        return fmt.negate(sin_r), fmt.negate(cos_r)
    return fmt.negate(cos_r), sin_r


def hankel_sums(fmt: BinaryFormat, x: int) -> tuple[int, int]:
    cfg = CONFIGS[fmt.name]
    coefficient = fmt.integer(1)
    inverse_power = fmt.integer(1)
    p = fmt.integer(1)
    q = fmt.integer(0)
    nu = fmt.integer(1)
    for k in range(cfg["hankel_iterations"]):
        m = k + 1
        odd = fmt.integer(2 * m - 1)
        mf = fmt.integer(m)
        nu_term = fmt.multiply(fmt.multiply(fmt.integer(4), nu), nu)
        odd_term = fmt.multiply(odd, odd)
        coefficient = fmt.divide(
            fmt.multiply(coefficient, fmt.subtract(nu_term, odd_term)),
            fmt.multiply(fmt.integer(8), mf),
        )
        inverse_power = fmt.divide(inverse_power, x)
        signed = fmt.integer(1 if (m // 2) % 2 == 0 else -1)
        term = fmt.multiply(
            fmt.multiply(signed, coefficient), inverse_power
        )
        if m % 2 == 0:
            p = fmt.add(p, term)
        else:
            q = fmt.add(q, term)
    return p, q


@lru_cache(maxsize=None)
def j1_finite(fmt: BinaryFormat, x: int) -> int:
    if fmt.is_zero(x):
        return x
    cfg = CONFIGS[fmt.name]
    y = fmt.absolute(x)
    if fmt.less_equal(y, fmt.integer(cfg["switch"])):
        magnitude = j1_series(fmt, y)
    else:
        phase = fmt.subtract(y, fmt.hexadecimal(cfg["phase_offset"]))
        sin_phase, cos_phase = sincos_reduced(fmt, phase)
        p, q = hankel_sums(fmt, y)
        denominator = fmt.multiply(fmt.hexadecimal(cfg["pi"]), y)
        prefactor = fmt.sqrt(fmt.divide(fmt.integer(2), denominator))
        combination = fmt.subtract(
            fmt.multiply(cos_phase, p),
            fmt.multiply(sin_phase, q),
        )
        magnitude = fmt.multiply(prefactor, combination)
    return fmt.negate(magnitude) if fmt.less(x, fmt.integer(0)) else magnitude


@dataclass(frozen=True)
class SolverResult:
    root: int
    lo: int
    hi: int
    residual: int
    tolerance: int
    iterations: int
    transcript_rows: tuple[dict[str, Any], ...]


def trace_row(fmt: BinaryFormat, event: str, **values: Any) -> dict[str, Any]:
    row: dict[str, Any] = {"event": event}
    for key, value in values.items():
        if isinstance(value, bool) or isinstance(value, str):
            row[key] = value
        elif key in {"index", "iteration", "iterations"}:
            row[key] = value
        elif isinstance(value, int):
            row[key] = fmt.bits_hex(value)
        else:
            raise TypeError(f"unsupported transcript value {key}={value!r}")
    return row


def solve(fmt: BinaryFormat, index: int) -> SolverResult:
    cfg = CONFIGS[fmt.name]
    pi = fmt.hexadecimal(cfg["pi"])
    center = fmt.multiply(
        fmt.add(fmt.integer(index), fmt.rational(1, 4)), pi
    )
    quarter_pi = fmt.divide(pi, fmt.integer(4))
    lo = fmt.subtract(center, quarter_pi)
    hi = fmt.add(center, quarter_pi)
    if not (1 <= index <= ROOT_COUNT) or fmt.fraction(hi) > 1024:
        raise AssertionError(f"{fmt.name} index {index} escaped valid source domain")
    flo = j1_finite(fmt, lo)
    fhi = j1_finite(fmt, hi)
    if not sign_change(fmt, flo, fhi):
        raise AssertionError(
            f"{fmt.name} index {index} initial source-evaluation bracket failed"
        )
    tolerance = fmt.multiply(
        fmt.multiply(fmt.integer(4), fmt.hexadecimal(cfg["epsilon"])),
        center if fmt.less(fmt.integer(1), center) else fmt.integer(1),
    )
    rows = [
        trace_row(
            fmt,
            "initial",
            index=index,
            center=center,
            lo=lo,
            hi=hi,
            flo=flo,
            fhi=fhi,
            tolerance=tolerance,
        )
    ]
    iterations = 0
    while (
        iterations < cfg["solver_cap"]
        and fmt.less(tolerance, fmt.subtract(hi, lo))
    ):
        old_lo = lo
        old_hi = hi
        old_width = fmt.subtract(old_hi, old_lo)
        if not sign_change(fmt, flo, fhi):
            raise AssertionError(
                f"{fmt.name} index {index} lost source sign bracket before step"
            )
        mid = fmt.add(lo, fmt.divide(fmt.subtract(hi, lo), fmt.integer(2)))
        if not (fmt.less(lo, mid) and fmt.less(mid, hi)):
            raise AssertionError(
                f"{fmt.name} index {index} midpoint did not strictly split bracket"
            )
        fm = j1_finite(fmt, mid)
        if sign_change(fmt, flo, fm):
            hi = mid
            fhi = fm
            choice = "upper"
        else:
            lo = mid
            flo = fm
            choice = "lower"
        iterations += 1
        new_width = fmt.subtract(hi, lo)
        if not fmt.less(new_width, old_width):
            raise AssertionError(
                f"{fmt.name} index {index} bracket did not strictly shrink"
            )
        if not sign_change(fmt, flo, fhi):
            raise AssertionError(
                f"{fmt.name} index {index} source sign bracket was not preserved"
            )
        rows.append(
            trace_row(
                fmt,
                "iteration",
                iteration=iterations,
                old_lo=old_lo,
                old_hi=old_hi,
                mid=mid,
                fm=fm,
                choice=choice,
                lo=lo,
                hi=hi,
                flo=flo,
                fhi=fhi,
            )
        )

    width = fmt.subtract(hi, lo)
    if iterations >= cfg["solver_cap"]:
        raise AssertionError(
            f"{fmt.name} index {index} exhausted the written iteration cap"
        )
    if not fmt.less_equal(width, tolerance):
        raise AssertionError(
            f"{fmt.name} index {index} stopped above the written tolerance"
        )
    root = fmt.add(lo, fmt.divide(fmt.subtract(hi, lo), fmt.integer(2)))
    if not (fmt.less_equal(lo, root) and fmt.less_equal(root, hi)):
        raise AssertionError(
            f"{fmt.name} index {index} returned midpoint outside final bracket"
        )
    residual = fmt.absolute(j1_finite(fmt, root))
    independently_recomputed = fmt.absolute(j1_finite(fmt, root))
    if residual != independently_recomputed:
        raise AssertionError(
            f"{fmt.name} index {index} reported-residual semantics drifted"
        )
    if not fmt.is_finite(residual) or fmt.fraction(residual) < 0:
        raise AssertionError(
            f"{fmt.name} index {index} reported a nonfinite/negative residual"
        )
    rows.append(
        trace_row(
            fmt,
            "final",
            index=index,
            iterations=iterations,
            lo=lo,
            hi=hi,
            width=width,
            tolerance=tolerance,
            root=root,
            residual=residual,
            recomputed_residual=independently_recomputed,
            converged=True,
        )
    )
    return SolverResult(
        root=root,
        lo=lo,
        hi=hi,
        residual=residual,
        tolerance=tolerance,
        iterations=iterations,
        transcript_rows=tuple(rows),
    )


def extract_module(source: str, precision: str) -> str:
    match = re.search(
        rf"module {precision}_impl = \{{(?P<body>.*?)(?=^\}}(?:\n|$))",
        source,
        flags=re.MULTILINE | re.DOTALL,
    )
    if match is None:
        raise SystemExit(f"cannot locate {precision} implementation module")
    return match.group("body")


def extract_function(module: str, name: str) -> str:
    match = re.search(
        rf"^  def {re.escape(name)}\b.*?(?=^  def \w+\b|\Z)",
        module,
        flags=re.MULTILINE | re.DOTALL,
    )
    if match is None:
        raise SystemExit(f"cannot locate source function {name}")
    return match.group(0)


def require_fragment(text: str, fragment: str, label: str) -> None:
    if fragment not in text:
        raise SystemExit(f"{label} drifted")


def verify_source(source: str) -> tuple[str, dict[str, str], dict[str, dict[str, str]]]:
    modules = {precision: extract_module(source, precision) for precision in FORMATS}
    dependencies = (
        "j1_series",
        "sincos_reduced",
        "hankel_sums",
        "j_asymptotic",
        "j1_finite",
        "sign_change",
        "positive_j1_root_solved",
    )
    function_hashes: dict[str, dict[str, str]] = {}
    for precision, module in modules.items():
        solver = extract_function(module, "positive_j1_root_solved")
        sign = extract_function(module, "sign_change")
        cap = CONFIGS[precision]["solver_cap"]
        epsilon = CONFIGS[precision]["epsilon"]
        require_fragment(
            sign,
            "(a <= 0.0 && b >= 0.0) || (a >= 0.0 && b <= 0.0)",
            f"{precision} sign-change predicate",
        )
        require_fragment(
            solver,
            "let bracketed = valid && sign_change flo0 fhi0",
            f"{precision} initial bracket predicate",
        )
        require_fragment(
            solver,
            f"let tolerance = 4.0 * {epsilon}{'f32' if precision == 'f32' else ''} * "
            f"{precision}.max 1.0 center",
            f"{precision} tolerance expression",
        )
        require_fragment(
            solver,
            f"while bracketed && it < {cap} && hi - lo > tolerance do",
            f"{precision} iteration/stopping predicate",
        )
        require_fragment(
            solver,
            "if sign_change flo fm\n           then (lo, mid, flo, fm, it + 1)\n"
            "           else (mid, hi, fm, fhi, it + 1)",
            f"{precision} bracket update",
        )
        require_fragment(
            solver,
            f"let residual = if bracketed then {precision}.abs (j1_finite root) "
            "else 1.0 / 0.0",
            f"{precision} reported residual",
        )
        require_fragment(
            solver,
            "converged = bracketed && hi - lo <= tolerance",
            f"{precision} convergence result",
        )
        function_hashes[precision] = {
            name: hashlib.sha256(extract_function(module, name).encode()).hexdigest()
            for name in dependencies
        }

    implementation_sha = hashlib.sha256(source.encode()).hexdigest()
    if implementation_sha != EXPECTED_IMPLEMENTATION_SHA256:
        raise SystemExit("implementation source SHA drifted; re-audit solver proof")
    module_hashes = {
        precision: hashlib.sha256(module.encode()).hexdigest()
        for precision, module in modules.items()
    }
    if module_hashes != EXPECTED_MODULE_SHA256:
        raise SystemExit("implementation module SHA drifted; re-audit solver proof")
    return implementation_sha, module_hashes, function_hashes


def canonical_row(row: dict[str, Any]) -> bytes:
    return (
        json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()


def extrema(
    results: list[SolverResult],
    key: Callable[[SolverResult], int],
    fmt: BinaryFormat,
) -> dict[str, Any]:
    selected = max(
        enumerate(results, start=1),
        key=lambda item: fmt.fraction(key(item[1])),
    )
    return {
        "bits": fmt.bits_hex(key(selected[1])),
        "hex": fmt.value_hex(key(selected[1])),
        "index": selected[0],
    }


def analyze_precision(fmt: BinaryFormat) -> dict[str, Any]:
    results = [solve(fmt, index) for index in range(1, ROOT_COUNT + 1)]
    transcript = hashlib.sha256()
    row_count = 0
    for index, result in enumerate(results, start=1):
        for row in result.transcript_rows:
            transcript.update(
                canonical_row({"index": index, "precision": fmt.name, **row})
            )
            row_count += 1
    iterations = [result.iterations for result in results]
    maximum_iteration = max(iterations)
    return {
        "status": "SOURCE_GRAPH_ARITHMETIC_PROVED",
        "index_domain": {"minimum": 1, "maximum": ROOT_COUNT},
        "index_count": len(results),
        "initial_source_evaluation_brackets": ROOT_COUNT,
        "preserved_source_evaluation_brackets": True,
        "strict_midpoint_and_width_progress": True,
        "all_stopped_at_or_below_written_tolerance": True,
        "all_stopped_before_iteration_cap": True,
        "iteration_cap": CONFIGS[fmt.name]["solver_cap"],
        "minimum_iterations": min(iterations),
        "maximum_iterations": maximum_iteration,
        "maximum_iteration_indices": [
            index
            for index, count in enumerate(iterations, start=1)
            if count == maximum_iteration
        ],
        "maximum_final_width": extrema(
            results, lambda result: fmt.subtract(result.hi, result.lo), fmt
        ),
        "maximum_written_tolerance": extrema(
            results, lambda result: result.tolerance, fmt
        ),
        "result_root_inside_final_bracket": True,
        "reported_residual_semantics": (
            "bit-exact abs(j1_finite(returned_root)) under the same source graph"
        ),
        "all_reported_residuals_finite_nonnegative": True,
        "maximum_reported_residual": extrema(
            results, lambda result: result.residual, fmt
        ),
        "transcript": {
            "canonicalization": "UTF-8 JSON Lines, sorted keys, compact separators",
            "events": "initial, every bisection iteration, final",
            "row_count": row_count,
            "sha256": transcript.hexdigest(),
        },
    }


def generate() -> dict[str, Any]:
    source = IMPLEMENTATION.read_text()
    implementation_sha, module_hashes, function_hashes = verify_source(source)
    results = {
        precision: analyze_precision(FORMATS[precision])
        for precision in ("f32", "f64")
    }
    return {
        "schema_version": "futhark-bessel.root-solver-arithmetic.v1",
        "status": "SOURCE_GRAPH_ROOT_SOLVER_ARITHMETIC_PROVED",
        "release_conformance": False,
        "scope": {
            "covered": (
                "positive_j1_root_solved on every valid public cached-root index "
                "1..256, separately for f32 and f64: written initial arithmetic, "
                "source-evaluation sign brackets, every bisection update, strict "
                "progress, stopping, returned midpoint, convergence flag, and "
                "implementation-reported residual construction"
            ),
            "excluded": [
                "cached-root literal certificates and their true mathematical residual envelopes",
                "solver-root ULP error, proximity to the mathematical J1 root, and true mathematical residual envelopes",
                "C/WASM/WebGPU lowering, contraction, reassociation, and runtime conformance",
                "behavior outside the valid root-index domain 1..256",
            ],
        },
        "authority": {
            "implementation_source": str(IMPLEMENTATION),
            "implementation_sha256": implementation_sha,
            "module_body_sha256": module_hashes,
            "source_function_sha256": function_hashes,
            "analyzer": str(ANALYZER),
            "analyzer_sha256": sha256(ANALYZER),
            "arithmetic": (
                "exact fractions with integer roundTiesToEven and integer-square "
                "comparison for correctly rounded sqrt"
            ),
        },
        "declared_primitive_semantics": {
            "inputs_and_binary_literals": "exact IEEE values",
            "add_subtract_multiply_divide": (
                "one IEEE-754 roundTiesToEven operation in the named precision, "
                "gradual underflow, no contraction"
            ),
            "sqrt": "correctly rounded IEEE-754 roundTiesToEven in the named precision",
            "round": "nearest integral value with ties to even",
            "evaluation_order": "strict written source tree without reassociation",
        },
        "proof_obligations": {
            "finite_valid_initial_arithmetic": "PROVED",
            "initial_source_evaluation_sign_bracket": "PROVED",
            "bisection_sign_bracket_invariant": "PROVED",
            "strict_progress_and_stopping_before_cap": "PROVED",
            "returned_midpoint_and_converged_flag": "PROVED",
            "implementation_reported_residual_source_semantics": "PROVED",
        },
        "results": results,
        "release_implications": {
            "root_solver_source_graph_arithmetic": "PROVED",
            "implementation_reported_residual_source_semantics": "PROVED",
            "solver_mathematical_root_ulp_and_true_residual": "OPEN",
            "implementation_reported_residual_backend_conformance": "OPEN",
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
    rendered = json.dumps(generate(), indent=2, sort_keys=True) + "\n"
    if args.write:
        OUTPUT.write_text(rendered)
        print(f"wrote {OUTPUT}")
        return
    if not OUTPUT.exists() or OUTPUT.read_text() != rendered:
        raise SystemExit(
            "root-solver arithmetic evidence is stale; run "
            "scripts/root_solver_proof.py --write"
        )
    print(
        "OK f32/f64 positive_j1_root_solved source arithmetic, stopping, and "
        "reported-residual semantics are proved for indices 1..256; mathematical "
        "root envelopes and backend conformance remain OPEN"
    )


if __name__ == "__main__":
    main()
