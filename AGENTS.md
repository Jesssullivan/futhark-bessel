# futhark-bessel Agent Contract

This repository is the isolated upstream package track for Wavegen TIN-3715.

- Use `nix develop --command just <recipe>` as the reproducible entrypoint.
- Use `apply_patch` for hand-authored files.
- Do not reuse Numerical Recipes, Hart, or Cephes coefficient arrays as source,
  fitting seeds, oracle data, or tests.
- Generated tables are caches, never numerical authority.
- Do not commit generated compiler artifacts, local notes, secrets, or datasets.
- Do not tag a release until every gate in `RELEASE.md` is evidenced.
- Never weaken an accuracy envelope to make a test pass.
- Never add AI attribution or `Co-Authored-By` trailers.
