#!/usr/bin/env python3
# SPDX-License-Identifier: ISC
"""Check declared, sample-only backend regression envelopes."""

from __future__ import annotations

import hashlib
import json
import math
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

OBSERVATIONS = Path("evidence/backend-observations.json")
ENVELOPES = Path("evidence/observed-regression-envelopes.json")
EXPECTED_SCHEMA = "futhark-bessel.observed-regression-envelopes.v1"


CANONICAL_NONNEGATIVE_HEX = re.compile(
    r"(?:0x0p\+0|0x1(?:\.[0-9a-f]*[1-9a-f])?p"
    r"(?:\+0|-[1-9][0-9]*|\+[1-9][0-9]*))"
)


def hexadecimal(text: Any) -> float:
    if not isinstance(text, str) or not CANONICAL_NONNEGATIVE_HEX.fullmatch(text):
        raise SystemExit(f"noncanonical hexadecimal envelope: {text!r}")
    try:
        value = float.fromhex(text)
    except (OverflowError, ValueError) as error:
        raise SystemExit(f"invalid hexadecimal envelope: {text!r}") from error
    mantissa, exponent = value.hex().split("p", maxsplit=1)
    integer, fraction = mantissa.split(".", maxsplit=1)
    fraction = fraction.rstrip("0")
    canonical = integer + (f".{fraction}" if fraction else "") + "p" + exponent
    if not math.isfinite(value) or value < 0 or canonical != text:
        raise SystemExit(f"invalid hexadecimal envelope: {text!r}")
    return value


def observed_hexadecimal(text: Any, label: str) -> float:
    if not isinstance(text, str):
        raise SystemExit(f"invalid observed hexadecimal value: {label}: {text!r}")
    try:
        value = float.fromhex(text)
    except ValueError as error:
        raise SystemExit(
            f"invalid observed hexadecimal value: {label}: {text!r}"
        ) from error
    if (
        not math.isfinite(value)
        or value < 0
        or text.startswith("-")
        or value.hex() != text
    ):
        raise SystemExit(f"invalid observed hexadecimal value: {label}: {text!r}")
    return value


def nonnegative_integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SystemExit(f"invalid nonnegative integer: {label}: {value!r}")
    return value


def ulp_ceiling(value: Any, label: str) -> int:
    try:
        return nonnegative_integer(value, label)
    except SystemExit as error:
        raise SystemExit(f"invalid ULP envelope: {label}: {value!r}") from error


def observed_decimal(text: Any, label: str) -> Decimal:
    if not isinstance(text, str):
        raise SystemExit(f"invalid observed decimal value: {label}: {text!r}")
    try:
        value = Decimal(text)
    except InvalidOperation as error:
        raise SystemExit(
            f"invalid observed decimal value: {label}: {text!r}"
        ) from error
    if not value.is_finite() or value < 0 or text.startswith("-"):
        raise SystemExit(f"invalid observed decimal value: {label}: {text!r}")
    return value


def check_parity(observations: dict[str, Any]) -> None:
    expected = {
        precision: {field: 0 for field in ("j0", "j1", "roots", "residuals")}
        for precision in ("f32", "f64")
    }
    if observations.get("backend_bit_parity") != expected:
        raise SystemExit("C/WASM bit parity drifted")


def check_metric(
    observed: dict[str, Any], envelope: dict[str, Any], label: str
) -> None:
    if set(envelope) != {"max_absolute_error_hex", "max_ulp_error"}:
        raise SystemExit(f"malformed value envelope: {label}")
    absolute = observed_hexadecimal(
        observed["max_absolute_error_against_rounded_reference_hex"], label
    )
    absolute_limit = hexadecimal(envelope["max_absolute_error_hex"])
    ulp_limit = ulp_ceiling(envelope["max_ulp_error"], label)
    observed_ulp = nonnegative_integer(observed["max_ulp_error"], label)
    if absolute > absolute_limit:
        raise SystemExit(
            f"observed absolute error escaped declared envelope: {label}: "
            f"{absolute.hex()} > {absolute_limit.hex()}"
        )
    if observed_ulp > ulp_limit:
        raise SystemExit(
            f"observed ULP error escaped declared envelope: {label}: "
            f"{observed_ulp} > {ulp_limit}"
        )


def check_roots(
    observed: dict[str, Any], envelope: dict[str, Any], label: str
) -> None:
    required = {
        "max_absolute_error_hex",
        "max_ulp_error",
        "max_reported_residual_hex",
        "max_independent_residual_hex",
    }
    if set(envelope) != required:
        raise SystemExit(f"malformed root envelope: {label}")
    check_metric(
        observed,
        {
            "max_absolute_error_hex": envelope["max_absolute_error_hex"],
            "max_ulp_error": envelope["max_ulp_error"],
        },
        label,
    )
    reported = observed_hexadecimal(observed["max_reported_residual_hex"], label)
    reported_limit = hexadecimal(envelope["max_reported_residual_hex"])
    if reported > reported_limit:
        raise SystemExit(
            f"reported residual escaped declared envelope: {label}: "
            f"{reported.hex()} > {reported_limit.hex()}"
        )
    independent = observed_decimal(
        observed["max_independent_residual_decimal"], label
    )
    independent_limit = Decimal.from_float(
        hexadecimal(envelope["max_independent_residual_hex"])
    )
    if independent > independent_limit:
        raise SystemExit(
            f"independent residual escaped declared envelope: {label}: "
            f"{independent} > {independent_limit}"
        )


def main() -> None:
    observations = json.loads(OBSERVATIONS.read_text())
    envelopes = json.loads(ENVELOPES.read_text())
    if envelopes.get("schema_version") != EXPECTED_SCHEMA:
        raise SystemExit("unexpected observed-envelope schema")
    if envelopes.get("status") != "OBSERVATION_ONLY_NOT_RELEASE_CONFORMANCE":
        raise SystemExit("observed envelopes must remain explicitly non-ratifying")
    if envelopes.get("release_conformance") is not False:
        raise SystemExit("observed envelopes cannot confer release conformance")
    expected_sha = hashlib.sha256(OBSERVATIONS.read_bytes()).hexdigest()
    if envelopes.get("observation_authority", {}).get("sha256") != expected_sha:
        raise SystemExit("observed envelopes are not bound to the observation ledger")
    if envelopes.get("observation_authority", {}).get("source") != str(OBSERVATIONS):
        raise SystemExit("unexpected observation authority source")
    if observations.get("status") != "OBSERVED_BASELINE_NOT_RELEASE_CONFORMANCE":
        raise SystemExit("backend baseline is not explicitly observational")
    if envelopes.get("policy", {}).get("backends") != ["c", "wasm"]:
        raise SystemExit("observed envelope backend scope drifted")
    if envelopes.get("policy", {}).get("webgpu") != "NOT_EXECUTED_NO_ENVELOPE":
        raise SystemExit("WebGPU cannot acquire an envelope without execution")
    if envelopes.get("policy", {}).get("whole_domain_claim") is not False:
        raise SystemExit("sample-only envelopes cannot make a whole-domain claim")

    declared = envelopes.get("declared_envelopes", {})
    for precision in ("f32", "f64"):
        precision_envelope = declared.get(precision)
        if not isinstance(precision_envelope, dict):
            raise SystemExit(f"missing {precision} declared envelope")
        for backend in ("c", "wasm"):
            observed = observations["observations"][precision][backend]
            if observed.get("status") != "OBSERVED_SAMPLES_NOT_RELEASE_CONFORMANCE":
                raise SystemExit(f"unexpected observation status: {precision}/{backend}")
            for domain in ("series", "asymptotic"):
                for function in ("j0", "j1"):
                    check_metric(
                        observed["values"][domain][function],
                        precision_envelope["values"][domain][function],
                        f"{precision}/{backend}/{domain}/{function}",
                    )
            check_roots(
                observed["roots"],
                precision_envelope["roots"],
                f"{precision}/{backend}/roots",
            )
    check_parity(observations)
    print(
        "OK C/WASM certified-sample observations remain inside the declared "
        "regression envelopes; no release conformance inferred"
    )


if __name__ == "__main__":
    main()
