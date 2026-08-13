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
round-to-nearest-even primitive semantics. The series bounds cover their source
branches. Exact index preservation is machine-falsified at representable inputs;
the asymptotic bounds therefore remain conditional on a proof that composes the
two adjacent reduction cells. No source bound applies to a backend until that
backend's lowering, contraction, and reassociation behavior is bound to an
analyzed graph. The counterexamples and open obligations are machine-readable in
`evidence/floating-point-analysis.json`; release remains blocked.

`just observed-envelopes` checks C/WASM results on the certified finite sample
ledger against separately declared dyadic regression ceilings in
`evidence/observed-regression-envelopes.json`. Those ceilings are sample-only
tripwires. They are neither inferred whole-domain bounds nor release
conformance envelopes, and WebGPU remains unexecuted.

Development is tracked under Wavegen TIN-3715. Licensed under the
[ISC License](LICENSE).
