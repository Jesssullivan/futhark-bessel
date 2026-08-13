import "../lib/github.com/Jesssullivan/futhark-bessel/bessel"

-- Prototype identities and first roots.
-- ==
-- entry: identity_bits
-- input {} output { true true true true }
-- entry: first_roots
-- input {} output { true true }

entry identity_bits =
  let zp = bessel.f32.j0_checked 0.0
  let z1p = bessel.f32.j1_checked 0.0
  let z1n = bessel.f32.j1_checked (-0.0)
  in (zp.value == 1.0,
      f32.to_bits z1p.value == 0u32,
      f32.to_bits z1n.value == 0x80000000u32,
      (bessel.f32.j0_checked (-3.0)).value ==
        (bessel.f32.j0_checked 3.0).value)

entry first_roots =
  map (\i ->
    let r = bessel.f32.positive_j1_root i
    in r.converged && r.lo <= r.root && r.root <= r.hi && r.residual < 2.0e-5)
    [1, 2]
