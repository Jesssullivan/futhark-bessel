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
    "OBSERVED_BASELINE_NOT_RELEASE_CONFORMANCE"
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

required_closed_fragments = (
    "Independent FLINT/Arb certificates",
    "Mathematical series, Hankel, phase-reduction",
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
