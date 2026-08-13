-- SPDX-License-Identifier: ISC
--
-- Provenance: mathematical defining series and Hankel expansion, DLMF
-- 10.2.2 and 10.17.3.  This prototype intentionally contains no imported
-- minimax coefficient array.  Its entire-domain error envelope is not yet
-- certified, so this module is pre-release.

import "root_cache"

module f64_impl = {
  type status = #ok | #out_of_domain | #nonfinite
  type checked = {value: f64, status: status}

  type root_result =
    { root: f64
    , lo: f64
    , hi: f64
    , residual: f64
    , iterations: i32
    , converged: bool
    }

  def nan : f64 = 0.0 / 0.0

  -- Fixed-term defining series on the reduced small-argument interval.
  def j0_series (x: f64) : f64 =
    let z = -(x * x) / 4.0
    let (_, s) =
      loop (term, acc) = (1.0, 1.0)
      for k < 96 do
        let d = f64.i32 (k + 1)
        let next = term * z / (d * d)
        in (next, acc + next)
    in s

  def j1_series (x: f64) : f64 =
    let z = -(x * x) / 4.0
    let (_, s) =
      loop (term, acc) = (x / 2.0, x / 2.0)
      for k < 96 do
        let k1 = f64.i32 (k + 1)
        let k2 = f64.i32 (k + 2)
        let next = term * z / (k1 * k2)
        in (next, acc + next)
    in s

  -- Deterministic reduction modulo pi/2.  Constants are independently
  -- generated from the Chudnovsky definition of pi; the leading part has
  -- enough trailing zero bits that n*pio2_hi is exact for this domain.
  def sincos_reduced (phase: f64) : (f64, f64) =
    let two_over_pi = 0x1.45f306dc9c883p-1
    let pio2_hi = 0x1.921fb54000000p+0
    let pio2_lo = 0x1.10b4611a62633p-30
    let pio2_tail = 0x1.45c06e0e68948p-86
    let n = i32.f64 (f64.round (phase * two_over_pi))
    let nf = f64.i32 n
    let r = ((phase - nf * pio2_hi) - nf * pio2_lo) - nf * pio2_tail
    let z = r * r
    let sin_r =
      r
      * (1.0
         + z
           * (-1.0 / 6.0
              + z
                * (1.0 / 120.0
                   + z
                     * (-1.0 / 5040.0
                        + z
                          * (1.0 / 362880.0
                             + z
                               * (-1.0 / 39916800.0 + z / 6227020800.0))))))
    let cos_r =
      1.0
      + z
        * (-1.0 / 2.0
           + z
             * (1.0 / 24.0
                + z
                  * (-1.0 / 720.0
                     + z
                       * (1.0 / 40320.0
                          + z
                            * (-1.0 / 3628800.0 + z / 479001600.0)))))
    let q = ((n % 4) + 4) % 4
    in if q == 0
       then (sin_r, cos_r)
       else if q == 1
       then (cos_r, -sin_r)
       else if q == 2
       then (-sin_r, -cos_r)
       else (-cos_r, sin_r)

  -- Definition-generated Hankel coefficients:
  -- a_m(nu)=product_{k=1}^m (4*nu^2-(2*k-1)^2)/(m!*8^m).
  -- No coefficient table is embedded or imported.
  def hankel_sums (nu: f64) (x: f64) : (f64, f64) =
    let (_, _, p, q) =
      loop (a, invpow, p, q) = (1.0, 1.0, 1.0, 0.0)
      for k < 12 do
        let m = k + 1
        let odd = f64.i32 (2 * m - 1)
        let mf = f64.i32 m
        let next_a = a * (4.0 * nu * nu - odd * odd) / (8.0 * mf)
        let next_invpow = invpow / x
        let signed_term =
          (if (m / 2) % 2 == 0 then 1.0 else -1.0) * next_a * next_invpow
        in if m % 2 == 0
           then (next_a, next_invpow, p + signed_term, q)
           else (next_a, next_invpow, p, q + signed_term)
    in (p, q)

  def j_asymptotic (nu: f64) (phase_offset: f64) (x: f64) : f64 =
    let (sin_phase, cos_phase) = sincos_reduced (x - phase_offset)
    let (p, q) = hankel_sums nu x
    let pi = 0x1.921fb54442d18p+1
    in f64.sqrt (2.0 / (pi * x)) * (cos_phase * p - sin_phase * q)

  def j0_finite (x: f64) : f64 =
    let y = f64.abs x
    in if y <= 12.0
       then j0_series y
       else j_asymptotic 0.0 0x1.921fb54442d18p-1 y

  def j1_finite (x: f64) : f64 =
    if x == 0.0
    then f64.from_bits (f64.to_bits x & 0x8000000000000000u64)
    else let y = f64.abs x
         let magnitude =
           if y <= 12.0
           then j1_series y
           else j_asymptotic 1.0 0x1.2d97c7f3321d2p+1 y
         in if x < 0.0 then -magnitude else magnitude

  def j0_checked (x: f64) : checked =
    if f64.isnan x || f64.isinf x
    then {value = nan, status = #nonfinite}
    else if f64.abs x > 1024.0
    then {value = nan, status = #out_of_domain}
    else {value = j0_finite x, status = #ok}

  def j1_checked (x: f64) : checked =
    if f64.isnan x || f64.isinf x
    then {value = nan, status = #nonfinite}
    else if f64.abs x > 1024.0
    then {value = nan, status = #out_of_domain}
    else {value = j1_finite x, status = #ok}

  def sign_change (a: f64) (b: f64) =
    (a <= 0.0 && b >= 0.0) || (a >= 0.0 && b <= 0.0)

  -- Bracketed bisection over asymptotic half-period brackets.  The public
  -- index contract remains explicit even though certified brackets are a
  -- separate, still-open release gate.
  def positive_j1_root_solved (index: i32) : root_result =
    let pi = 0x1.921fb54442d18p+1
    let center = (f64.i32 index + 0.25) * pi
    let lo0 = center - pi / 4.0
    let hi0 = center + pi / 4.0
    let valid = index >= 1 && index <= 256 && hi0 <= 1024.0
    let flo0 = if valid then j1_finite lo0 else 1.0
    let fhi0 = if valid then j1_finite hi0 else 1.0
    let bracketed = valid && sign_change flo0 fhi0
    let tolerance = 4.0 * 0x1.0p-52 * f64.max 1.0 center
    let (lo, hi, _, _, iterations) =
      loop (lo, hi, flo, fhi, it) = (lo0, hi0, flo0, fhi0, 0)
      while bracketed && it < 96 && hi - lo > tolerance do
        let mid = lo + (hi - lo) / 2.0
        let fm = j1_finite mid
        in if sign_change flo fm
           then (lo, mid, flo, fm, it + 1)
           else (mid, hi, fm, fhi, it + 1)
    let root = lo + (hi - lo) / 2.0
    let residual = if bracketed then f64.abs (j1_finite root) else 1.0 / 0.0
    in { root = if bracketed then root else nan
       , lo = if bracketed then lo else nan
       , hi = if bracketed then hi else nan
       , residual
       , iterations
       , converged = bracketed && hi - lo <= tolerance
       }

  -- Public roots consume an independently Arb-certified, disposable cache.
  -- `positive_j1_root_solved` remains available to test recomputability; the
  -- cache generator and its certificates, never this array, are authority.
  def positive_j1_root (index: i32) : root_result =
    if index < 1 || index > 256
    then { root = nan
         , lo = nan
         , hi = nan
         , residual = nan
         , iterations = 0
         , converged = false
         }
    else let i = i64.i32 (index - 1)
         let root = f64_cache.root[i]
         in { root
            , lo = f64_cache.lo[i]
            , hi = f64_cache.hi[i]
            , residual = f64.abs (j1_finite root)
            , iterations = 0
            , converged = true
            }
}

module f32_impl = {
  type status = #ok | #out_of_domain | #nonfinite
  type checked = {value: f32, status: status}

  type root_result =
    { root: f32
    , lo: f32
    , hi: f32
    , residual: f32
    , iterations: i32
    , converged: bool
    }

  def nan : f32 = 0.0 / 0.0

  def j0_series (x: f32) : f32 =
    let z = -(x * x) / 4.0
    let (_, s) =
      loop (term, acc) = (1.0, 1.0)
      for k < 48 do
        let d = f32.i32 (k + 1)
        let next = term * z / (d * d)
        in (next, acc + next)
    in s

  def j1_series (x: f32) : f32 =
    let z = -(x * x) / 4.0
    let (_, s) =
      loop (term, acc) = (x / 2.0, x / 2.0)
      for k < 48 do
        let k1 = f32.i32 (k + 1)
        let k2 = f32.i32 (k + 2)
        let next = term * z / (k1 * k2)
        in (next, acc + next)
    in s

  def sincos_reduced (phase: f32) : (f32, f32) =
    let two_over_pi = 0x1.45f3060000000p-1f32
    let pio2_hi = 0x1.9218000000000p+0f32
    let pio2_lo = 0x1.ed51100000000p-14f32
    let pio2_tail = 0x1.68c2340000000p-39f32
    let n = i32.f32 (f32.round (phase * two_over_pi))
    let nf = f32.i32 n
    let r = ((phase - nf * pio2_hi) - nf * pio2_lo) - nf * pio2_tail
    let z = r * r
    let sin_r =
      r
      * (1.0
         + z
           * (-1.0 / 6.0
              + z
                * (1.0 / 120.0
                   + z
                     * (-1.0 / 5040.0 + z / 362880.0))))
    let cos_r =
      1.0
      + z
        * (-1.0 / 2.0
           + z
             * (1.0 / 24.0
                + z
                  * (-1.0 / 720.0
                     + z
                       * (1.0 / 40320.0 + z * (-1.0 / 3628800.0)))))
    let q = ((n % 4) + 4) % 4
    in if q == 0
       then (sin_r, cos_r)
       else if q == 1
       then (cos_r, -sin_r)
       else if q == 2
       then (-sin_r, -cos_r)
       else (-cos_r, sin_r)

  def hankel_sums (nu: f32) (x: f32) : (f32, f32) =
    let (_, _, p, q) =
      loop (a, invpow, p, q) = (1.0, 1.0, 1.0, 0.0)
      for k < 7 do
        let m = k + 1
        let odd = f32.i32 (2 * m - 1)
        let mf = f32.i32 m
        let next_a = a * (4.0 * nu * nu - odd * odd) / (8.0 * mf)
        let next_invpow = invpow / x
        let signed_term =
          (if (m / 2) % 2 == 0 then 1.0 else -1.0) * next_a * next_invpow
        in if m % 2 == 0
           then (next_a, next_invpow, p + signed_term, q)
           else (next_a, next_invpow, p, q + signed_term)
    in (p, q)

  def j_asymptotic (nu: f32) (phase_offset: f32) (x: f32) : f32 =
    let (sin_phase, cos_phase) = sincos_reduced (x - phase_offset)
    let (p, q) = hankel_sums nu x
    let pi = 0x1.921fb60000000p+1f32
    in f32.sqrt (2.0 / (pi * x)) * (cos_phase * p - sin_phase * q)

  def j0_finite (x: f32) : f32 =
    let y = f32.abs x
    in if y <= 6.0
       then j0_series y
       else j_asymptotic 0.0 0x1.921fb60000000p-1f32 y

  def j1_finite (x: f32) : f32 =
    if x == 0.0
    then f32.from_bits (f32.to_bits x & 0x80000000u32)
    else let y = f32.abs x
         let magnitude =
           if y <= 6.0
           then j1_series y
           else j_asymptotic 1.0 0x1.2d97c80000000p+1f32 y
         in if x < 0.0 then -magnitude else magnitude

  def j0_checked (x: f32) : checked =
    if f32.isnan x || f32.isinf x
    then {value = nan, status = #nonfinite}
    else if f32.abs x > 1024.0
    then {value = nan, status = #out_of_domain}
    else {value = j0_finite x, status = #ok}

  def j1_checked (x: f32) : checked =
    if f32.isnan x || f32.isinf x
    then {value = nan, status = #nonfinite}
    else if f32.abs x > 1024.0
    then {value = nan, status = #out_of_domain}
    else {value = j1_finite x, status = #ok}

  def sign_change (a: f32) (b: f32) =
    (a <= 0.0 && b >= 0.0) || (a >= 0.0 && b <= 0.0)

  def positive_j1_root_solved (index: i32) : root_result =
    let pi = 0x1.921fb60000000p+1f32
    let center = (f32.i32 index + 0.25) * pi
    let lo0 = center - pi / 4.0
    let hi0 = center + pi / 4.0
    let valid = index >= 1 && index <= 256 && hi0 <= 1024.0
    let flo0 = if valid then j1_finite lo0 else 1.0
    let fhi0 = if valid then j1_finite hi0 else 1.0
    let bracketed = valid && sign_change flo0 fhi0
    let tolerance = 4.0 * 0x1.0p-23f32 * f32.max 1.0 center
    let (lo, hi, _, _, iterations) =
      loop (lo, hi, flo, fhi, it) = (lo0, hi0, flo0, fhi0, 0)
      while bracketed && it < 48 && hi - lo > tolerance do
        let mid = lo + (hi - lo) / 2.0
        let fm = j1_finite mid
        in if sign_change flo fm
           then (lo, mid, flo, fm, it + 1)
           else (mid, hi, fm, fhi, it + 1)
    let root = lo + (hi - lo) / 2.0
    let residual = if bracketed then f32.abs (j1_finite root) else 1.0 / 0.0
    in { root = if bracketed then root else nan
       , lo = if bracketed then lo else nan
       , hi = if bracketed then hi else nan
       , residual
       , iterations
       , converged = bracketed && hi - lo <= tolerance
       }

  def positive_j1_root (index: i32) : root_result =
    if index < 1 || index > 256
    then { root = nan
         , lo = nan
         , hi = nan
         , residual = nan
         , iterations = 0
         , converged = false
         }
    else let i = i64.i32 (index - 1)
         let root = f32_cache.root[i]
         in { root
            , lo = f32_cache.lo[i]
            , hi = f32_cache.hi[i]
            , residual = f32.abs (j1_finite root)
            , iterations = 0
            , converged = true
            }
}
