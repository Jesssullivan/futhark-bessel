import "../lib/github.com/Jesssullivan/futhark-bessel/bessel"

def status_is_ok (status: f32_bessel.status) =
  match status
  case #ok -> true
  case #out_of_domain -> false
  case #nonfinite -> false

def status_is_out_of_domain (status: f32_bessel.status) =
  match status
  case #ok -> false
  case #out_of_domain -> true
  case #nonfinite -> false

def status_is_nonfinite (status: f32_bessel.status) =
  match status
  case #ok -> false
  case #out_of_domain -> false
  case #nonfinite -> true

-- Prototype identities.
-- ==
-- entry: identity_bits
-- input { 0x80000000u32 } output { true true true true true true }
entry identity_bits (negative_zero_bits: u32) =
  let zp = f32_bessel.j0_checked 0.0
  let zn = f32_bessel.j0_checked (f32.from_bits negative_zero_bits)
  let z1p = f32_bessel.j1_checked 0.0
  let z1n = f32_bessel.j1_checked (f32.from_bits negative_zero_bits)
  in ( zp.value == 1.0
     , f32.to_bits zn.value == f32.to_bits 1.0
     , f32.to_bits z1p.value == 0u32
     , f32.to_bits z1n.value == 0x80000000u32
     , (f32_bessel.j0_checked (-3.0)).value
       == (f32_bessel.j0_checked 3.0).value
     , (f32_bessel.j1_checked (-3.0)).value
       == -(f32_bessel.j1_checked 3.0).value
     )

-- First roots satisfy cache bounds and residual smoke checks.
-- ==
-- entry: first_roots
-- input {} output { [true, true] }
entry first_roots =
  map (\i ->
         let r = f32_bessel.positive_j1_root i
         in r.converged && r.lo <= r.root && r.root <= r.hi && r.residual < 2.0e-5)
      [1, 2]

-- Checked statuses and index bounds.
-- ==
-- entry: status_contract
-- input {} output { true }
entry status_contract =
  let j0_positive_endpoint = f32_bessel.j0_checked 1024.0
  let j0_negative_endpoint = f32_bessel.j0_checked (-1024.0)
  let j1_positive_endpoint = f32_bessel.j1_checked 1024.0
  let j1_negative_endpoint = f32_bessel.j1_checked (-1024.0)
  let j0_infinite = f32_bessel.j0_checked f32.inf
  let j1_infinite = f32_bessel.j1_checked f32.inf
  let j0_nan = f32_bessel.j0_checked f32.nan
  let j1_nan = f32_bessel.j1_checked f32.nan
  in status_is_ok j0_positive_endpoint.status
     && status_is_ok j0_negative_endpoint.status
     && status_is_ok j1_positive_endpoint.status
     && status_is_ok j1_negative_endpoint.status
     && !f32.isnan j0_positive_endpoint.value
     && !f32.isnan j0_negative_endpoint.value
     && !f32.isnan j1_positive_endpoint.value
     && !f32.isnan j1_negative_endpoint.value
     && status_is_out_of_domain (f32_bessel.j0_checked 1024.1).status
     && status_is_out_of_domain (f32_bessel.j1_checked (-1024.1)).status
     && status_is_nonfinite j0_infinite.status
     && status_is_nonfinite j1_infinite.status
     && status_is_nonfinite j0_nan.status
     && status_is_nonfinite j1_nan.status
     && f32.isnan j0_infinite.value
     && f32.isnan j1_infinite.value
     && f32.isnan j0_nan.value
     && f32.isnan j1_nan.value
     && !(f32_bessel.positive_j1_root 0).converged
     && f32.isnan (f32_bessel.positive_j1_root 257).root

-- Complete cached root index domain.
-- ==
-- entry: all_roots_bracketed
-- input {} output { true }
entry all_roots_bracketed =
  reduce (&&)
         true
         (map (\i ->
                 let r = f32_bessel.positive_j1_root (i32.i64 i + 1)
                 in r.converged && r.lo <= r.root && r.root <= r.hi
                    && !f32.isnan r.residual
                    && !f32.isinf r.residual)
              (iota 256))
