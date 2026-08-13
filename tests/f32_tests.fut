import "../lib/github.com/Jesssullivan/futhark-bessel/bessel"

-- Prototype identities and first roots.
-- ==
-- entry: identity_bits
-- input {} output { true true true true }
-- entry: first_roots
-- input {} output { true true }
-- entry: status_contract
-- input {} output { true }
-- entry: all_roots_bracketed
-- input {} output { true }

def status_is_ok (status: bessel.f32.status) =
  match status
  case #ok -> true
  case #out_of_domain -> false
  case #nonfinite -> false

def status_is_out_of_domain (status: bessel.f32.status) =
  match status
  case #ok -> false
  case #out_of_domain -> true
  case #nonfinite -> false

def status_is_nonfinite (status: bessel.f32.status) =
  match status
  case #ok -> false
  case #out_of_domain -> false
  case #nonfinite -> true

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

entry status_contract =
  status_is_ok (bessel.f32.j0_checked 1024.0).status &&
  status_is_ok (bessel.f32.j1_checked (-1024.0)).status &&
  status_is_out_of_domain (bessel.f32.j0_checked 1024.1).status &&
  status_is_nonfinite (bessel.f32.j1_checked f32.inf).status &&
  status_is_nonfinite (bessel.f32.j0_checked f32.nan).status

entry all_roots_bracketed =
  reduce (&&) true
    (map (\i ->
      let r = bessel.f32.positive_j1_root (i32.i64 i + 1)
      in r.converged && r.lo <= r.root && r.root <= r.hi &&
         !f32.isnan r.residual && !f32.isinf r.residual)
      (iota 256))
