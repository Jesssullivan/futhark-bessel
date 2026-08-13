set dotenv-load := false
set export := false
set positional-arguments := true
set shell := ["bash", "-euo", "pipefail", "-c"]

default:
  @just --list

fmt:
  futhark fmt --check lib tests
  nixfmt --check flake.nix
  futhark pkg fmt

package:
  futhark pkg check

check-source:
  python3 scripts/check_provenance.py

typecheck:
  futhark check --Werror tests/f32_tests.fut
  futhark check --Werror tests/f64_tests.fut

test-c:
  futhark test --backend=c --no-terminal tests

compile-webgpu:
  mkdir -p build
  futhark webgpu --library tests/f32_tests.fut -o build/f32_tests

oracle:
  mkdir -p build evidence
  cc -std=c11 -O2 -Wall -Wextra -Werror oracle/arb_oracle.c -lflint -lm -o build/arb_oracle
  build/arb_oracle > evidence/arb-certificates.jsonl
  python3 oracle/mpmath_crosscheck.py evidence/arb-certificates.jsonl

evidence: oracle
  python3 scripts/check_evidence.py evidence/arb-certificates.jsonl

coeff-hash:
  python3 scripts/coefficient_hash.py

check: fmt package check-source typecheck test-c compile-webgpu evidence coeff-hash
  gitleaks dir --no-banner --redact .
  nix flake check --no-build

release-preflight: check
  python3 scripts/release_preflight.py
