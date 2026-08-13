#!/usr/bin/env python3
"""Release remains deliberately fail-closed until certified gates exist."""

import json
from pathlib import Path

release_lines = Path("RELEASE.md").read_text().splitlines()
unchecked = [line for line in release_lines if "- [ ]" in line]
observations = json.loads(Path("evidence/backend-observations.json").read_text())
error_budget = json.loads(Path("evidence/error-budget.json").read_text())
approximation = json.loads(
    Path("evidence/real-approximation-bounds.json").read_text()
)
floating_point = json.loads(
    Path("evidence/floating-point-analysis.json").read_text()
)
adjacent = json.loads(
    Path("evidence/adjacent-composition-proof.json").read_text()
)
observed_envelopes = json.loads(
    Path("evidence/observed-regression-envelopes.json").read_text()
)
root_envelopes = {
    precision: json.loads(
        Path(f"evidence/{precision}-root-envelope.json").read_text()
    )
    for precision in ("f32", "f64")
}
root_correction = json.loads(
    Path("evidence/f64-root-cache-correction.json").read_text()
)

if observations.get("status") != "OBSERVED_BASELINE_NOT_RELEASE_CONFORMANCE":
    raise SystemExit("BLOCKED: backend evidence must remain explicitly non-ratifying")
if observations.get("release_gate") != (
    "BLOCKED_PENDING_DECLARED_ENVELOPES_AND_COMPLETE_CERTIFICATION"
):
    raise SystemExit("BLOCKED: backend evidence release gate is not fail-closed")
if observations.get("webgpu") != {
    "status": "COMPILED_NOT_EXECUTED",
    "release_conformance": False,
    "reason": "The pinned headless CI runner exposes no ratified WebGPU adapter/runtime.",
}:
    raise SystemExit("BLOCKED: WebGPU compilation must not be recorded as conformance")
if error_budget.get("release_status") != "INCOMPLETE":
    raise SystemExit("BLOCKED: error budget cannot claim release completeness")
if error_budget.get("observed_backend_maxima", {}).get("status") != (
    "OBSERVED_BASELINE_AND_SAMPLE_ONLY_ENVELOPES_NOT_RELEASE_CONFORMANCE"
):
    raise SystemExit("BLOCKED: observed maxima are not release envelopes")
if approximation.get("status") != "CERTIFIED_EXACT_REAL_WHOLE_DOMAIN":
    raise SystemExit("BLOCKED: exact-real whole-domain proof is missing")
if approximation.get("release_implications") != {
    "backend_release_envelopes": "OPEN",
    "floating_point_rounding_reassociation": "OPEN",
    "overall_release_status": "INCOMPLETE",
    "real_arithmetic_mathematical_approximation": "CERTIFIED",
}:
    raise SystemExit("BLOCKED: exact-real proof must preserve floating-point gates")
if floating_point.get("status") != "SOURCE_EVALUATION_PROVED_BACKEND_LOWERING_OPEN":
    raise SystemExit("BLOCKED: source proof/backend-lowering boundary drifted")
if floating_point.get("release_conformance") is not False:
    raise SystemExit("BLOCKED: source analysis cannot confer backend conformance")
if adjacent.get("status") != "ADJACENT_REDUCTION_COMPOSITION_PROVED":
    raise SystemExit("BLOCKED: adjacent reduction composition proof is missing")
if adjacent.get("release_implications") != {
    "adjacent_source_reduction_composition": "PROVED",
    "backend_lowering_equivalence": "OPEN",
    "overall_release_status": "INCOMPLETE",
    "root_solver_arithmetic": "OPEN",
}:
    raise SystemExit("BLOCKED: adjacent proof release boundary drifted")
if floating_point.get("closed_obligations") != [
    {
        "id": "FP-ADJACENT-REDUCTION-COMPOSITION",
        "statement": (
            "Every exact-rational floating transition band, both adjacent "
            "selected quadrants, the shadow radius, and the Taylor/phase/Hankel "
            "composition are certified."
        ),
        "status": "PROVED",
    }
]:
    raise SystemExit("BLOCKED: adjacent composition obligation closure drifted")
if {item.get("status") for item in floating_point.get("open_obligations", [])} != {
    "OPEN"
}:
    raise SystemExit("BLOCKED: floating-point obligations were not fail-closed")
if len(floating_point.get("open_obligations", [])) != 4:
    raise SystemExit("BLOCKED: expected four explicit floating-point obligations")
expected_obligations = {
    "FP-ROOT-SOLVER-ARITHMETIC",
    "FP-BACKEND-LOWERING-C",
    "FP-BACKEND-LOWERING-WASM",
    "FP-BACKEND-LOWERING-WEBGPU",
}
if {
    item.get("id") for item in floating_point.get("open_obligations", [])
} != expected_obligations:
    raise SystemExit("BLOCKED: floating-point obligation set drifted")
for precision in ("f32", "f64"):
    for function in ("j0", "j1"):
        reduction = floating_point.get("range_reduction_index_analysis", {}).get(
            precision, {}
        ).get(function, {})
        if reduction.get("status") != "EXACT_INDEX_EQUALITY_FALSIFIED":
            raise SystemExit("BLOCKED: reduction-index counterevidence is missing")
        if reduction.get("index_difference_abs_upper") != 1:
            raise SystemExit("BLOCKED: adjacent-only reduction bound is missing")
        if reduction.get("composition_status") != (
            "ADJACENT_REDUCTION_COMPOSITION_PROVED"
        ):
            raise SystemExit("BLOCKED: adjacent reduction composition is missing")
        if not all(
            isinstance(reduction.get(field), int) and reduction[field] > 0
            for field in (
                "transition_band_count",
                "candidate_count",
                "mismatch_count",
                "mismatch_span_count",
            )
        ):
            raise SystemExit("BLOCKED: complete transition census is missing")
        witness = reduction.get("first_witness", {})
        if witness.get("exact_real_index") == witness.get("floating_index"):
            raise SystemExit("BLOCKED: reduction-index witness is not a counterexample")
if observed_envelopes.get("status") != (
    "OBSERVATION_ONLY_NOT_RELEASE_CONFORMANCE"
):
    raise SystemExit("BLOCKED: observed envelopes must remain sample-only")
if observed_envelopes.get("release_conformance") is not False:
    raise SystemExit("BLOCKED: observed envelopes cannot confer conformance")
f64_observed_root_ceiling = observed_envelopes.get("declared_envelopes", {}).get(
    "f64", {}
).get("roots", {})
if (
    f64_observed_root_ceiling.get("max_ulp_error") != 0
    or f64_observed_root_ceiling.get("max_absolute_error_hex") != "0x0p+0"
    or f64_observed_root_ceiling.get("max_independent_residual_hex") != "0x1p-48"
):
    raise SystemExit("BLOCKED: f64 cache regression ceiling must require exact roots")
expected_root_implications = {
    "backend_lowering_equivalence": "OPEN",
    "f32_cached_root_ulp_and_mathematical_residual": "CERTIFIED",
    "f32_reported_residual": "BACKEND_CONFORMANCE_OPEN",
    "f64_cached_root_ulp_and_mathematical_residual": "CERTIFIED",
    "f64_reported_residual": "BACKEND_CONFORMANCE_OPEN",
    "overall_release_status": "INCOMPLETE",
    "root_solver_arithmetic": "OPEN",
}
expected_root_residuals = {
    "f32": "0x1.0000000000000p-19",
    "f64": "0x1.0000000000000p-48",
}
for precision, root_envelope in root_envelopes.items():
    if root_envelope.get("status") != "SOURCE_CACHE_ROOT_ENVELOPE_CERTIFIED":
        raise SystemExit(
            f"BLOCKED: {precision} cached-root envelope certificate is missing"
        )
    if root_envelope.get("release_conformance") is not False:
        raise SystemExit("BLOCKED: source root evidence cannot confer backend conformance")
    if root_envelope.get("envelopes", {}).get("root_ulp_error_upper") != 0:
        raise SystemExit(
            f"BLOCKED: {precision} cached roots are not certified correctly rounded"
        )
    if root_envelope.get("envelopes", {}).get(
        "true_residual_abs_upper_hex"
    ) != expected_root_residuals[precision]:
        raise SystemExit(f"BLOCKED: {precision} true-residual envelope drifted")
    if root_envelope.get("release_implications") != expected_root_implications:
        raise SystemExit(
            f"BLOCKED: {precision} root-envelope release boundary drifted"
        )
if root_correction.get("status") != "SOURCE_CACHE_GENERATOR_CORRECTED":
    raise SystemExit("BLOCKED: f64 root-cache correction witness is missing")
if root_correction.get("release_conformance") is not False:
    raise SystemExit("BLOCKED: cache correction cannot confer backend conformance")
if root_correction.get("pre_fix", {}).get("first_witness") != {
    "cached_bits": "0x400ea75575af6f08",
    "certified_bits": "0x400ea75575af6f09",
    "index": 1,
    "ulp_error": 1,
}:
    raise SystemExit("BLOCKED: pre-fix f64 root-1 witness drifted")
if root_correction.get("pre_fix", {}).get("f64_mismatched_root_count") != 111:
    raise SystemExit("BLOCKED: pre-fix f64 cache mismatch census drifted")
if root_correction.get("pre_fix", {}).get("f64_maximum_ulp_error") != 1:
    raise SystemExit("BLOCKED: pre-fix f64 maximum ULP witness drifted")
if root_correction.get("pre_fix", {}).get("f32_mismatched_root_count") != 0:
    raise SystemExit("BLOCKED: pre-fix f32 cache mismatch census drifted")
root_mismatch_indices = root_correction.get("pre_fix", {}).get(
    "f64_mismatched_root_indices", []
)
if (
    len(root_mismatch_indices) != 111
    or root_mismatch_indices != sorted(set(root_mismatch_indices))
    or any(
        not isinstance(index, int) or index < 1 or index > 256
        for index in root_mismatch_indices
    )
):
    raise SystemExit("BLOCKED: pre-fix f64 mismatch index census drifted")
historical_corrections = root_correction.get("pre_fix", {}).get(
    "f64_corrections", []
)
if (
    not isinstance(historical_corrections, list)
    or len(historical_corrections) != 111
    or [item.get("index") for item in historical_corrections]
    != root_mismatch_indices
    or any(
        set(item) != {"cached_bits", "certified_bits", "index", "ulp_error"}
        or item.get("ulp_error") != 1
        or not isinstance(item.get("cached_bits"), str)
        or not isinstance(item.get("certified_bits"), str)
        or abs(
            int(item["cached_bits"], 16) - int(item["certified_bits"], 16)
        ) != 1
        for item in historical_corrections
    )
):
    raise SystemExit("BLOCKED: historical f64 1-ULP corrections drifted")
correction_authority = root_correction.get("authority", {})
if correction_authority.get("certificate_relationship") != (
    "the reference oracle's uniquely rounded bits feed the renderer; "
    "the separate envelope oracle recomputes roots and residuals "
    "without consuming the cache; mpmath independently replays both"
):
    raise SystemExit("BLOCKED: f64 cache authority relationship drifted")
if root_correction.get("correction", {}).get("f32_changed_root_count") != 0:
    raise SystemExit("BLOCKED: f32 cached roots changed during f64 correction")
if root_correction.get("correction", {}).get("f64_changed_root_count") != 111:
    raise SystemExit("BLOCKED: f64 corrected-root census drifted")
if root_correction.get("correction", {}).get(
    "f64_every_change_exactly_one_ulp"
) is not True:
    raise SystemExit("BLOCKED: f64 cache correction is not entirely 1 ULP")
if root_correction.get("correction", {}).get(
    "f32_remaining_ulp_mismatches"
) != 0 or root_correction.get("correction", {}).get(
    "f64_remaining_ulp_mismatches"
) != 0:
    raise SystemExit("BLOCKED: corrected cache still has root ULP mismatches")
root_budget = error_budget.get("root_evidence", {})
for precision in ("f32", "f64"):
    if root_budget.get(f"{precision}_release_ulp_envelope", {}).get(
        "maximum_ulp_error"
    ) != 0:
        raise SystemExit(f"BLOCKED: {precision} root ULP error budget drifted")
    if root_budget.get(f"{precision}_release_residual_envelope", {}).get(
        "maximum_true_residual_abs_hex"
    ) != expected_root_residuals[precision]:
        raise SystemExit(
            f"BLOCKED: {precision} root residual error budget drifted"
        )

required_closed_fragments = (
    "Independent FLINT/Arb certificates",
    "Mathematical series, Hankel, phase-reduction",
    "All 256 public cached f32 roots",
    "All 256 public cached f64 roots",
)
for fragment in required_closed_fragments:
    matching = [line for line in release_lines if fragment in line]
    if len(matching) != 1 or "- [x]" not in matching[0]:
        raise SystemExit(f"BLOCKED: evidenced mathematical gate is open: {fragment}")

required_open_fragments = (
    "Floating-point rounding/reassociation bounds",
    "The f32 implementation passes C, WASM, and WebGPU conformance",
    "The f64 implementation passes C and WASM conformance",
)
for fragment in required_open_fragments:
    matching = [line for line in release_lines if fragment in line]
    if len(matching) != 1 or "- [ ]" not in matching[0]:
        raise SystemExit(f"BLOCKED: release gate must remain open: {fragment}")

if unchecked:
    raise SystemExit(f"BLOCKED: {len(unchecked)} release gates remain unchecked")
print("OK all release gates recorded")
