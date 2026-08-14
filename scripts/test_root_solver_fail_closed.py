#!/usr/bin/env python3
# SPDX-License-Identifier: ISC
"""Mutation and primitive-arithmetic checks for root_solver_proof.py."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path
from typing import Callable

import root_solver_proof as proof


ROOT = Path(__file__).resolve().parents[1]


def expect_blocked(function: Callable[[], object], fragment: str) -> None:
    try:
        function()
    except SystemExit as error:
        if fragment not in str(error):
            raise SystemExit(
                f"wrong fail-closed reason: expected {fragment!r}, got {error!r}"
            ) from error
        return
    raise SystemExit(f"mutation did not fail closed: expected {fragment!r}")


def mutate_module(source: str, precision: str, old: str, new: str) -> str:
    module = proof.extract_module(source, precision)
    if module.count(old) != 1:
        raise SystemExit(
            f"fixture fragment count drifted for {precision}: {old!r}"
        )
    return source.replace(module, module.replace(old, new, 1), 1)


def test_source_mutations() -> None:
    source = proof.IMPLEMENTATION.read_text()
    for precision in ("f32", "f64"):
        cap = proof.CONFIGS[precision]["solver_cap"]
        epsilon = proof.CONFIGS[precision]["epsilon"]
        suffix = "f32" if precision == "f32" else ""
        tolerance = (
            f"let tolerance = 4.0 * {epsilon}{suffix} * "
            f"{precision}.max 1.0 center"
        )
        mutations = (
            (
                "(a <= 0.0 && b >= 0.0) || (a >= 0.0 && b <= 0.0)",
                "(a < 0.0 && b > 0.0) || (a > 0.0 && b < 0.0)",
                f"{precision} sign-change predicate",
            ),
            (
                "let bracketed = valid && sign_change flo0 fhi0",
                "let bracketed = valid",
                f"{precision} initial bracket predicate",
            ),
            (
                "if sign_change flo fm\n"
                "           then (lo, mid, flo, fm, it + 1)\n"
                "           else (mid, hi, fm, fhi, it + 1)",
                "if sign_change flo fm\n"
                "           then (mid, hi, fm, fhi, it + 1)\n"
                "           else (lo, mid, flo, fm, it + 1)",
                f"{precision} bracket update",
            ),
            (
                f"while bracketed && it < {cap} && hi - lo > tolerance do",
                f"while bracketed && it < {cap - 1} && hi - lo > tolerance do",
                f"{precision} iteration/stopping predicate",
            ),
            (
                tolerance,
                tolerance.replace("4.0", "8.0", 1),
                f"{precision} tolerance expression",
            ),
            (
                f"let residual = if bracketed then {precision}.abs "
                "(j1_finite root) else 1.0 / 0.0",
                "let residual = if bracketed then root else 1.0 / 0.0",
                f"{precision} reported residual",
            ),
            (
                "converged = bracketed && hi - lo <= tolerance",
                "converged = bracketed && hi - lo < tolerance",
                f"{precision} convergence result",
            ),
        )
        for old, new, reason in mutations:
            changed = mutate_module(source, precision, old, new)
            expect_blocked(lambda text=changed: proof.verify_source(text), reason)

    expect_blocked(
        lambda: proof.verify_source(source + "\n-- unaudited source drift\n"),
        "implementation source SHA",
    )


def test_round_ties_to_even() -> None:
    for precision, fmt in proof.FORMATS.items():
        one = Fraction(1)
        ulp = proof.power_of_two(-(fmt.precision - 1))
        if fmt.round_fraction(one + ulp / 2) != fmt.integer(1):
            raise SystemExit(f"{precision} even-lower tie did not round down")
        odd_lower = one + ulp
        expected_upper = fmt.round_fraction(one + 2 * ulp)
        if fmt.round_fraction(odd_lower + ulp / 2) != expected_upper:
            raise SystemExit(f"{precision} odd-lower tie did not round up")


def test_correctly_rounded_sqrt() -> None:
    expected_sqrt_two = {
        "f32": 0x3FB504F3,
        "f64": 0x3FF6A09E667F3BCD,
    }
    for precision, fmt in proof.FORMATS.items():
        if fmt.sqrt(fmt.integer(2)) != expected_sqrt_two[precision]:
            raise SystemExit(f"{precision} correctly rounded sqrt(2) drifted")
        if fmt.sqrt(fmt.integer(4)) != fmt.integer(2):
            raise SystemExit(f"{precision} exact sqrt drifted")


def test_bit_roundtrips() -> None:
    fixtures = {
        "f32": (0x00000001, 0x007FFFFF, 0x00800000, 0x3F800000, 0x7F7FFFFF),
        "f64": (
            0x0000000000000001,
            0x000FFFFFFFFFFFFF,
            0x0010000000000000,
            0x3FF0000000000000,
            0x7FEFFFFFFFFFFFFF,
        ),
    }
    for precision, values in fixtures.items():
        fmt = proof.FORMATS[precision]
        for bits in values:
            if fmt.round_fraction(fmt.fraction(bits)) != bits:
                raise SystemExit(f"{precision} exact bit roundtrip failed at {bits:#x}")


def source_ratio(
    fmt: proof.BinaryFormat, numerator: int, denominator: int
) -> int:
    """Evaluate a written floating source division of exact integer literals."""

    return fmt.divide(fmt.integer(numerator), fmt.integer(denominator))


def direct_source_polynomials(
    fmt: proof.BinaryFormat, reduced: int
) -> tuple[int, int]:
    """Independently spell the written sin/cos Horner operation trees."""

    z = fmt.multiply(reduced, reduced)
    if fmt.name == "f32":
        sin_inner = fmt.add(
            source_ratio(fmt, -1, 5040),
            fmt.divide(z, fmt.integer(362880)),
        )
        sin_inner = fmt.add(
            source_ratio(fmt, 1, 120), fmt.multiply(z, sin_inner)
        )
        sin_inner = fmt.add(
            source_ratio(fmt, -1, 6), fmt.multiply(z, sin_inner)
        )

        cos_inner = fmt.add(
            source_ratio(fmt, 1, 40320),
            fmt.multiply(z, source_ratio(fmt, -1, 3628800)),
        )
        cos_inner = fmt.add(
            source_ratio(fmt, -1, 720), fmt.multiply(z, cos_inner)
        )
        cos_inner = fmt.add(
            source_ratio(fmt, 1, 24), fmt.multiply(z, cos_inner)
        )
        cos_inner = fmt.add(
            source_ratio(fmt, -1, 2), fmt.multiply(z, cos_inner)
        )
    else:
        sin_inner = fmt.add(
            source_ratio(fmt, -1, 39916800),
            fmt.divide(z, fmt.integer(6227020800)),
        )
        for numerator, denominator in (
            (1, 362880),
            (-1, 5040),
            (1, 120),
            (-1, 6),
        ):
            sin_inner = fmt.add(
                source_ratio(fmt, numerator, denominator),
                fmt.multiply(z, sin_inner),
            )

        cos_inner = fmt.add(
            source_ratio(fmt, -1, 3628800),
            fmt.divide(z, fmt.integer(479001600)),
        )
        for numerator, denominator in (
            (1, 40320),
            (-1, 720),
            (1, 24),
            (-1, 2),
        ):
            cos_inner = fmt.add(
                source_ratio(fmt, numerator, denominator),
                fmt.multiply(z, cos_inner),
            )

    sin_result = fmt.multiply(
        reduced,
        fmt.add(fmt.integer(1), fmt.multiply(z, sin_inner)),
    )
    cos_result = fmt.add(fmt.integer(1), fmt.multiply(z, cos_inner))
    return sin_result, cos_result


DIRECT_SOURCE_CONSTANTS = {
    "f32": {
        "pi": "0x1.921fb60000000p+1",
        "phase_offset": "0x1.2d97c80000000p+1",
        "two_over_pi": "0x1.45f3060000000p-1",
        "pio2": (
            "0x1.9218000000000p+0",
            "0x1.ed51100000000p-14",
            "0x1.68c2340000000p-39",
        ),
    },
    "f64": {
        "pi": "0x1.921fb54442d18p+1",
        "phase_offset": "0x1.2d97c7f3321d2p+1",
        "two_over_pi": "0x1.45f306dc9c883p-1",
        "pio2": (
            "0x1.921fb54000000p+0",
            "0x1.10b4611a62633p-30",
            "0x1.45c06e0e68948p-86",
        ),
    },
}


def direct_source_sincos(
    fmt: proof.BinaryFormat, phase: int
) -> tuple[int, int]:
    """Independently spell source reduction, polynomials, and quadrant map."""

    constants = DIRECT_SOURCE_CONSTANTS[fmt.name]
    product = fmt.multiply(phase, fmt.hexadecimal(constants["two_over_pi"]))
    n_float = fmt.round_integral(product)
    n = int(fmt.fraction(n_float))
    nf = fmt.integer(n)
    reduced = phase
    for component in constants["pio2"]:
        reduced = fmt.subtract(
            reduced, fmt.multiply(nf, fmt.hexadecimal(component))
        )
    sin_reduced, cos_reduced = direct_source_polynomials(fmt, reduced)
    quadrant = ((n % 4) + 4) % 4
    if quadrant == 0:
        return sin_reduced, cos_reduced
    if quadrant == 1:
        return cos_reduced, fmt.negate(sin_reduced)
    if quadrant == 2:
        return fmt.negate(sin_reduced), fmt.negate(cos_reduced)
    return fmt.negate(cos_reduced), sin_reduced


def direct_solver_endpoint_phase(
    fmt: proof.BinaryFormat, index: int, endpoint: str
) -> tuple[int, int]:
    """Construct an initial solver endpoint and asymptotic phase from source."""

    constants = DIRECT_SOURCE_CONSTANTS[fmt.name]
    pi = fmt.hexadecimal(constants["pi"])
    center = fmt.multiply(
        fmt.add(fmt.integer(index), source_ratio(fmt, 1, 4)), pi
    )
    quarter_pi = fmt.divide(pi, fmt.integer(4))
    if endpoint == "lo":
        value = fmt.subtract(center, quarter_pi)
    elif endpoint == "hi":
        value = fmt.add(center, quarter_pi)
    else:
        raise ValueError(f"unsupported endpoint {endpoint!r}")
    phase = fmt.subtract(
        value, fmt.hexadecimal(constants["phase_offset"])
    )
    return value, phase


def test_direct_source_expression_parity() -> None:
    # Both real solver endpoints expose the rejected extra-z tree in the final
    # sine and cosine bits.  Fixed bits make this independent spelling a
    # regression oracle rather than another call through the production helper.
    fixtures = (
        {
            "precision": "f32",
            "index": 2,
            "endpoint": "hi",
            "endpoint_bits": 0x40FB53D1,
            "phase_bits": 0x40AFEDDF,
            "result_bits": (0xBF3504F5, 0x3F3504F1),
        },
        {
            "precision": "f64",
            "index": 4,
            "endpoint": "lo",
            "endpoint_bits": 0x402921FB54442D18,
            "phase_bits": 0x40246B9C347764A4,
            "result_bits": (0xBFE6A09E667F497E, 0xBFE6A09E667F3C81),
        },
    )
    for fixture in fixtures:
        precision = fixture["precision"]
        fmt = proof.FORMATS[precision]
        endpoint, phase = direct_solver_endpoint_phase(
            fmt, fixture["index"], fixture["endpoint"]
        )
        if endpoint != fixture["endpoint_bits"] or phase != fixture["phase_bits"]:
            raise SystemExit(f"{precision} solver endpoint fixture drifted")
        expected = tuple(fixture["result_bits"])
        direct = direct_source_sincos(fmt, phase)
        actual = proof.sincos_reduced(fmt, phase)
        if direct != expected:
            raise SystemExit(
                f"{precision} independent source-expression fixture drifted: "
                f"expected {tuple(map(fmt.bits_hex, expected))}, got "
                f"{tuple(map(fmt.bits_hex, direct))}"
            )
        if actual != expected:
            raise SystemExit(
                f"{precision} production source-expression parity failed: "
                f"expected {tuple(map(fmt.bits_hex, expected))}, got "
                f"{tuple(map(fmt.bits_hex, actual))}"
            )

    # Exhaust both initial solver endpoints as an independently spelled parity
    # surface.  This covers every quadrant in both precisions, rather than
    # relying only on the fixed q=3 regression witnesses above.
    for precision, fmt in proof.FORMATS.items():
        quadrants: set[int] = set()
        constants = DIRECT_SOURCE_CONSTANTS[precision]
        two_over_pi = fmt.hexadecimal(constants["two_over_pi"])
        for index in range(1, proof.ROOT_COUNT + 1):
            for endpoint_name in ("lo", "hi"):
                _, phase = direct_solver_endpoint_phase(
                    fmt, index, endpoint_name
                )
                product = fmt.multiply(phase, two_over_pi)
                quadrant = int(fmt.fraction(fmt.round_integral(product))) % 4
                quadrants.add(quadrant)
                direct = direct_source_sincos(fmt, phase)
                actual = proof.sincos_reduced(fmt, phase)
                if actual != direct:
                    raise SystemExit(
                        f"{precision} independent endpoint parity failed at "
                        f"index {index} {endpoint_name}"
                    )
        if quadrants != {0, 1, 2, 3}:
            raise SystemExit(
                f"{precision} endpoint parity missed quadrants: {quadrants}"
            )


def test_terminal_operation_forms_are_distinct() -> None:
    cases = (
        ("f32", 0x3C8BAEDC, 362880, "division"),
        ("f32", 0x3B453319, 3628800, "reciprocal_multiply"),
        ("f64", 0x3F506EECBE029155, 6227020800, "division"),
        ("f64", 0x3F506EECBE029155, 479001600, "division"),
    )
    for precision, phase, denominator, written_form in cases:
        fmt = proof.FORMATS[precision]
        z = fmt.multiply(phase, phase)
        if written_form == "division":
            written = fmt.divide(z, fmt.integer(denominator))
            alternate = fmt.multiply(z, source_ratio(fmt, 1, denominator))
        else:
            written = fmt.multiply(z, source_ratio(fmt, -1, denominator))
            alternate = fmt.divide(z, fmt.integer(-denominator))
        if written == alternate:
            raise SystemExit(
                f"{precision} terminal-operation fixture no longer distinguishes "
                f"{written_form} at denominator {denominator}"
            )


def test_evidence_write_and_stale_paths() -> None:
    original_generate = proof.generate
    original_output = proof.OUTPUT
    original_argv = sys.argv
    canonical = {"schema_version": "fixture.v1", "status": "PROVED"}
    try:
        with tempfile.TemporaryDirectory() as directory:
            proof.generate = lambda: canonical
            proof.OUTPUT = Path(directory) / "root-solver.json"

            sys.argv = ["root_solver_proof.py", "--write"]
            proof.main()
            expected = json.dumps(canonical, indent=2, sort_keys=True) + "\n"
            if proof.OUTPUT.read_text() != expected:
                raise SystemExit("root-solver --write did not emit canonical JSON")

            sys.argv = ["root_solver_proof.py", "--check"]
            proof.main()
            proof.OUTPUT.write_text("{}\n")
            expect_blocked(proof.main, "evidence is stale")

            proof.OUTPUT = Path(directory) / "missing.json"
            expect_blocked(proof.main, "evidence is stale")
    finally:
        proof.generate = original_generate
        proof.OUTPUT = original_output
        sys.argv = original_argv


def run_preflight(directory: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts/release_preflight.py")],
        cwd=directory,
        check=False,
        capture_output=True,
        text=True,
    )


def require_preflight_reason(directory: Path, fragment: str) -> None:
    completed = run_preflight(directory)
    output = completed.stdout + completed.stderr
    if completed.returncode != 1 or fragment not in output:
        raise SystemExit(
            f"wrong release-preflight result: expected {fragment!r}, got "
            f"exit {completed.returncode}: {output!r}"
        )


def test_release_preflight_root_boundaries() -> None:
    with tempfile.TemporaryDirectory() as directory:
        fixture = Path(directory)
        shutil.copy(ROOT / "RELEASE.md", fixture / "RELEASE.md")
        shutil.copytree(ROOT / "evidence", fixture / "evidence")
        implementation = fixture / "lib/github.com/Jesssullivan/futhark-bessel"
        implementation.mkdir(parents=True)
        shutil.copy(
            proof.IMPLEMENTATION,
            implementation / proof.IMPLEMENTATION.name,
        )
        scripts = fixture / "scripts"
        scripts.mkdir()
        shutil.copy(ROOT / "scripts/root_solver_proof.py", scripts)

        require_preflight_reason(fixture, "5 release gates remain unchecked")

        solver_path = fixture / "evidence/root-solver-arithmetic.json"
        solver = json.loads(solver_path.read_text())
        solver["release_implications"][
            "solver_mathematical_root_ulp_and_true_residual"
        ] = "PROVED"
        solver_path.write_text(json.dumps(solver))
        require_preflight_reason(fixture, "root-solver release boundary drifted")
        shutil.copy(ROOT / "evidence/root-solver-arithmetic.json", solver_path)

        budget_path = fixture / "evidence/error-budget.json"
        budget = json.loads(budget_path.read_text())
        budget["root_evidence"]["root_solver_source_graph"]["status"] = "OPEN"
        budget_path.write_text(json.dumps(budget))
        require_preflight_reason(fixture, "root-solver error-budget entry drifted")
        shutil.copy(ROOT / "evidence/error-budget.json", budget_path)

        floating_path = fixture / "evidence/floating-point-analysis.json"
        floating = json.loads(floating_path.read_text())
        floating["open_obligations"][0]["id"] = "FP-ROOT-SOLVER-ARITHMETIC"
        floating_path.write_text(json.dumps(floating))
        require_preflight_reason(fixture, "floating-point obligation set drifted")


def run_source_bundle(directory: Path) -> str:
    completed = subprocess.run(
        [sys.executable, "scripts/coefficient_hash.py"],
        cwd=directory,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def test_source_bundle_membership_and_sensitivity() -> None:
    source = (ROOT / "scripts/coefficient_hash.py").read_text()
    bound_paths = tuple(re.findall(r'Path\("([^"]+)"\)', source))
    root_solver_paths = (
        "scripts/root_solver_proof.py",
        "scripts/test_root_solver_fail_closed.py",
        "evidence/root-solver-arithmetic.json",
    )
    for path in root_solver_paths:
        if source.count(f'Path("{path}")') != 1:
            raise SystemExit(f"numerical source bundle does not bind {path}")

    with tempfile.TemporaryDirectory() as directory:
        fixture = Path(directory)
        for relative in bound_paths:
            destination = fixture / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / relative, destination)
        baseline = run_source_bundle(fixture)
        for relative in root_solver_paths:
            target = fixture / relative
            original = target.read_bytes()
            target.write_bytes(original + b"\n")
            mutated = run_source_bundle(fixture)
            target.write_bytes(original)
            if mutated == baseline:
                raise SystemExit(
                    f"numerical source bundle is insensitive to {relative}"
                )


def main() -> None:
    test_source_mutations()
    test_round_ties_to_even()
    test_correctly_rounded_sqrt()
    test_bit_roundtrips()
    test_direct_source_expression_parity()
    test_terminal_operation_forms_are_distinct()
    test_evidence_write_and_stale_paths()
    test_release_preflight_root_boundaries()
    test_source_bundle_membership_and_sensitivity()
    print(
        "OK root-solver proof fails closed on sign/bracket/iteration/residual/"
        "source-hash drift; IEEE primitives and direct source-expression "
        "parity pass"
    )


if __name__ == "__main__":
    main()
