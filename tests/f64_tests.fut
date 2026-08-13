import "../lib/github.com/Jesssullivan/futhark-bessel/bessel"

-- Prototype identities and first roots.
-- ==
-- entry: identity_bits
-- input {} output { true true true true }
-- entry: first_roots
-- input {} output { true true true }

entry identity_bits =
  let zp = bessel.f64.j0_checked 0.0
  let z1p = bessel.f64.j1_checked 0.0
  let z1n = bessel.f64.j1_checked (-0.0)
  in (zp.value == 1.0,
      f64.to_bits z1p.value == 0u64,
      f64.to_bits z1n.value == 0x8000000000000000u64,
      (bessel.f64.j0_checked (-3.0)).value ==
        (bessel.f64.j0_checked 3.0).value)

entry first_roots =
  map (\i ->
    let r = bessel.f64.positive_j1_root i
    in r.converged && r.lo <= r.root && r.root <= r.hi && r.residual < 1.0e-12)
    [1, 2, 3]
