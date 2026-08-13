# Release gates

No semantic release exists. A `v0.1.0` tag may be cut only when all gates below
have machine-readable evidence at the tagged commit.

- [ ] Independent interval certificates cover `J0` and `J1` on the complete
      finite domain `|x| <= 1024`, including both endpoints and all reduction
      boundaries.
- [ ] Separately accounted mathematical approximation, floating-point
      rounding/reassociation, and observed backend error envelopes exist for
      f32 and f64.
- [ ] The f32 implementation passes C, WASM, and WebGPU conformance with its
      declared ULP/residual envelopes.
- [ ] The f64 implementation passes C and WASM conformance with its declared
      envelopes.
- [ ] Positive `J1` roots `1..256` have independently certified f64 brackets;
      f32 rounded-root ULP and residual envelopes are recorded.
- [ ] Checked evaluation distinguishes `OK`, `OUT_OF_DOMAIN`, and `NONFINITE`;
      parity, signed zero, endpoints, and nonfinite behavior are tested.
- [ ] Every approximation constant is hexadecimal, reproducible from a pinned
      deterministic Remez/interval toolchain, and has a recorded source hash.
- [ ] Generated root and mode tables are demonstrated to be disposable caches.
- [ ] `futhark pkg check`, gitleaks, formatting, all tests, and all release
      evidence pass from the pinned Nix shell.

The current branch is a provenance-clean prototype, not a released numerical
library. `just release-preflight` fails closed until these gates are evidenced.
