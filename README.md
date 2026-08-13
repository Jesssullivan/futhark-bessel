# futhark-bessel

Provenance-clean `J0`, `J1`, and positive `J1` root work for Futhark.

This repository is pre-release. No numerical API or accuracy envelope is yet
claimed stable. The implementation covers the intended finite argument and root
index domains, but whole-domain interval certification and backend-specific
error envelopes remain release blockers in [RELEASE.md](RELEASE.md).

The package lives at the official Futhark package path:

```futhark
import "lib/github.com/Jesssullivan/futhark-bessel/bessel"

let checked = bessel.f32.j0_checked 12.0f32
let root = bessel.f64.positive_j1_root 1
```

Use `nix develop --command just check` for the pinned repository gate. The
implementation is generated directly from mathematical definitions; independent
evidence uses FLINT/Arb and mpmath. Exact provenance is structured in
`evidence/provenance.json`.

Development is tracked under Wavegen TIN-3715. Licensed under the
[ISC License](LICENSE).
