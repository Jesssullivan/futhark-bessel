set dotenv-load := false
set export := false
set positional-arguments := true
set shell := ["bash", "-euo", "pipefail", "-c"]

default:
  @just --list

fmt:
  find lib tests -name '*.fut' ! -name 'root_cache.fut' -print0 | xargs -0 futhark fmt --check
  nixfmt --check flake.nix

package:
  futhark pkg check

check-source:
  python3 scripts/check_provenance.py
  python3 scripts/generate_constants.py --check

typecheck:
  futhark check --Werror tests/backend_conformance.fut
  futhark check --Werror tests/f32_tests.fut
  futhark check --Werror tests/f64_tests.fut

test-c:
  futhark test --backend=c --no-terminal tests

compile-webgpu:
  mkdir -p build
  futhark webgpu --library tests/f32_tests.fut -o build/f32_tests

oracle:
  mkdir -p build evidence
  cc -std=c11 -O2 -Wall -Wextra -Werror oracle/arb_oracle.c -lflint -lmpfr -lm -o build/arb_oracle
  build/arb_oracle > evidence/arb-certificates.jsonl
  python3 oracle/mpmath_crosscheck.py evidence/arb-certificates.jsonl

root-cache: oracle
  python3 scripts/render_root_cache.py

evidence: oracle
  python3 scripts/check_evidence.py evidence/arb-certificates.jsonl
  python3 scripts/render_root_cache.py --check

_approximation-ledger:
  mkdir -p build evidence
  cc -std=c11 -O2 -Wall -Wextra -Werror oracle/approximation_bounds.c -lflint -lmpfr -lm -o build/approximation_bounds
  build/approximation_bounds > evidence/real-approximation-certificates.jsonl

approximation-proof: _approximation-ledger
  python3 scripts/approximation_proof.py --check

approximation-proof-write: _approximation-ledger
  python3 scripts/approximation_proof.py --write

_adjacent-composition-ledger:
  mkdir -p build evidence
  python3 scripts/adjacent_reduction_bands.py --check
  cc -std=c11 -O2 -Wall -Wextra -Werror oracle/adjacent_composition.c -lflint -lmpfr -lm -o build/adjacent_composition
  build/adjacent_composition > evidence/adjacent-composition-certificates.jsonl

adjacent-composition-proof: _adjacent-composition-ledger
  python3 scripts/adjacent_composition_proof.py --check

adjacent-composition-proof-write: _adjacent-composition-ledger
  python3 scripts/adjacent_composition_proof.py --write

floating-point-analysis: adjacent-composition-proof
  python3 scripts/floating_point_analysis.py --check
  PYTHONPATH=scripts python3 scripts/test_evidence_fail_closed.py

backend-conformance: evidence
  python3 scripts/backend_conformance.py --check

backend-conformance-write: evidence
  python3 scripts/backend_conformance.py --write

observed-envelopes:
  python3 scripts/check_observed_envelopes.py

coeff-hash:
  python3 scripts/coefficient_hash.py

check: fmt package check-source typecheck test-c compile-webgpu approximation-proof floating-point-analysis backend-conformance observed-envelopes coeff-hash
  gitleaks dir --no-banner --redact .

release-preflight: check
  python3 scripts/release_preflight.py
