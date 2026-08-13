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
root_envelope = json.loads(Path("evidence/f32-root-envelope.json").read_text())

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
if root_envelope.get("status") != "SOURCE_CACHE_ROOT_ENVELOPE_CERTIFIED":
    raise SystemExit("BLOCKED: f32 cached-root envelope certificate is missing")
if root_envelope.get("release_conformance") is not False:
    raise SystemExit("BLOCKED: source root evidence cannot confer backend conformance")
if root_envelope.get("envelopes", {}).get("root_ulp_error_upper") != 0:
    raise SystemExit("BLOCKED: f32 cached roots are not certified correctly rounded")
if root_envelope.get("envelopes", {}).get("true_residual_abs_upper_hex") != (
    "0x1.0000000000000p-19"
):
    raise SystemExit("BLOCKED: f32 true-residual envelope drifted")
if root_envelope.get("release_implications") != {
    "backend_lowering_equivalence": "OPEN",
    "f32_cached_root_ulp_and_mathematical_residual": "CERTIFIED",
    "f32_reported_residual": "BACKEND_CONFORMANCE_OPEN",
    "f64_root_envelope": "OPEN",
    "overall_release_status": "INCOMPLETE",
    "root_solver_arithmetic": "OPEN",
}:
    raise SystemExit("BLOCKED: f32 root-envelope release boundary drifted")
root_budget = error_budget.get("root_evidence", {})
if root_budget.get("f32_release_ulp_envelope", {}).get("maximum_ulp_error") != 0:
    raise SystemExit("BLOCKED: f32 root ULP error budget drifted")
if root_budget.get("f32_release_residual_envelope", {}).get(
    "maximum_true_residual_abs_hex"
) != "0x1.0000000000000p-19":
    raise SystemExit("BLOCKED: f32 root residual error budget drifted")

required_closed_fragments = (
    "Independent FLINT/Arb certificates",
    "Mathematical series, Hankel, phase-reduction",
    "All 256 public cached f32 roots",
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
