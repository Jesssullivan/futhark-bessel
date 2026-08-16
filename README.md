# futhark-bessel

Provenance-clean `J0`, `J1`, and positive `J1` root work for Futhark.

This repository is pre-release. No numerical API or accuracy envelope is yet
claimed stable. The implementation covers the intended finite argument and root
index domains, but whole-domain interval certification and backend-specific
error envelopes remain release blockers in [RELEASE.md](RELEASE.md).

The package lives at the official Futhark package path:

```futhark
import "lib/github.com/Jesssullivan/futhark-bessel/bessel"

let checked = f32_bessel.j0_checked 12.0f32
let root = f64_bessel.positive_j1_root 1
```

Use `nix develop --command just check` for the pinned repository gate. The
implementation is generated directly from mathematical definitions; independent
evidence uses FLINT/Arb and mpmath. Exact provenance is structured in
`evidence/provenance.json`.

`just backend-conformance` executes identical Arb-certified value samples and
all 256 certified roots through Futhark's sequential C and WASM runtimes. It
checks the committed machine-readable observation baseline in
`evidence/backend-observations.json`. The recorded maxima are finite-sample
regression evidence, not declared release envelopes or whole-domain proofs.
WebGPU is compile-checked only until a pinned runner with a ratified adapter is
available.

`just approximation-proof` regenerates 2,608 FLINT/Arb certificate rows for
the exact-real interpretation of the current algorithm and independently
verifies them with mpmath. The proof covers the defining-series and Hankel
remainders, every range-reduction cell and tie, both switches and endpoints,
trigonometric Taylor remainders, and the rounded phase/prefactor constants. Its
committed summary is `evidence/real-approximation-bounds.json`. Backend
floating-point rounding, contraction, and reassociation are explicitly outside
that theorem.

`just floating-point-analysis` separately checks exact-rational forward-error
bounds for the written source-operation graph under explicitly declared
round-to-nearest-even primitive semantics. Exact index preservation is
machine-falsified at representable inputs. `just adjacent-composition-proof`
therefore regenerates FLINT/Arb certificates and independently verifies the
complete disjoint transition-band partition, either selected adjacent quadrant,
the shadow-index radius, and Taylor/phase/Hankel composition with mpmath. The
2,584 floating transition bands in
`evidence/adjacent-reduction-bands.json` are deliberately distinct from the
2,584 canonical exact-real cell boundaries in the approximation ledger. They
contain 37,301 representable candidates and a complete census of 1,453
index-mismatching inputs in 1,422 bit spans. The f32 shadow radius exceeds the
older canonical `pi/4 + 0.0001` diagnostic radius, so its certificate uses the
direct Taylor Lagrange remainder at the larger shadow radius.

The resulting source-operation bounds now cover both branches and compose with
their mathematical approximation bounds. No source bound applies to a backend
until that backend's lowering, contraction, and reassociation behavior is bound
to an analyzed graph. `just root-solver-proof` separately replays the written
`positive_j1_root_solved` source graph with exact rationals and explicit IEEE
round-to-nearest-even primitives. For every index `1..256`, separately in f32
and f64, it proves source-evaluation bracketing, bisection progress and stopping,
returned-record construction, and that the reported residual is bit-exact
`abs(j1_finite(root))` under that same graph. The compact all-step transcript
digests are in `evidence/root-solver-arithmetic.json`.

`just solver-root-envelope-proof` turns those source-interpreted returned-root
bits into an ignored, canonical 512-row manifest bound to the complete f32/f64
source transcripts. A new, separate FLINT/Arb oracle evaluates mathematical
`J1` at each exact solver output without consuming the public root cache or the
cached-root residual oracle. The committed compact join in
`evidence/solver-root-envelopes.json` binds every source output to the existing
Arb-certified correctly rounded reference bits and the new residual ball, then
replays both with pinned mpmath. Across indices `1..256`, the maximum root error
is 3 ULP for f32 and 21,203 ULP for f64; the latter is the fixed index-4 witness
`0x402aa5baf3113875` versus reference `0x402aa5baf310e5a2`. The certified
all-index true-residual envelopes are `|J1(root)| <= 0x1.2c3683a1de614p-18`
for f32 and `|J1(root)| <= 0x1.215d7b11c58aap-37` for f64.

That theorem certifies source-graph solver-output mathematical-root ULP and true
`J1` residual envelopes only. It does not claim containment in a mathematical
root-isolating bracket, the accuracy of the implementation-reported approximate
residual, or C/WASM/WebGPU lowering, contraction, reassociation, runtime, or
release conformance. Those backend obligations remain open and release remains
blocked.

`just observed-envelopes` checks C/WASM results on the certified finite sample
ledger against separately declared dyadic regression ceilings in
`evidence/observed-regression-envelopes.json`. Those ceilings are sample-only
tripwires. They are neither inferred whole-domain bounds nor release
conformance envelopes, and WebGPU remains unexecuted.

`just root-envelope-proof` independently recomputes all 256 mathematical `J1`
roots with FLINT/Arb, proves their unique binary32 and binary64 rounding, bounds
the true residual at each exact rounded value, and replays the result with
mpmath. The public cached roots therefore have zero ULP error and
`|J1(r_hat)| <= 0x1p-19` for f32 and `|J1(r_hat)| <= 0x1p-48` for f64. These
source-artifact certificates remain distinct from the recomputing solver's
source-graph and mathematical-root proofs; none certifies a backend-reported
residual. The cache is a non-authoritative derived artifact: the Arb-certified
reference bits generate it, while a separate Arb computation and mpmath replay
verify every emitted f32/f64 literal. The machine-readable historical
correction witness is `evidence/f64-root-cache-correction.json`.

Development is tracked under Wavegen TIN-3715. Licensed under the
[ISC License](LICENSE).
