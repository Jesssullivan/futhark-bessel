-- SPDX-License-Identifier: ISC
--
-- Provenance: mathematical defining series and Hankel expansion, DLMF
-- 10.2.2 and 10.17.3.  This prototype intentionally contains no imported
-- minimax coefficient array.  Its entire-domain error envelope is not yet
-- certified, so this module is pre-release.

module f64 = {
  type status = #ok | #out_of_domain | #nonfinite
  type checked = {value: f64, status: status}
  type root_result = {
    root: f64,
    lo: f64,
    hi: f64,
    residual: f64,
    iterations: i32,
    converged: bool,
  }

  def nan : f64 = f64.from_bits 0x7ff8000000000000u64

  -- Fixed-term defining series, stable on the deliberately conservative
  -- prototype interval |x| <= 20.  A future certified reduction replaces
  -- this at larger arguments.
  def j0_series (x: f64) : f64 =
    let z = -(x * x) / 4.0
    let (_, s) = loop (term, acc) = (1.0, 1.0) for k < 96 do
      let d = f64.i32 (k + 1)
      let next = term * z / (d * d)
      in (next, acc + next)
    in s

  def j1_series (x: f64) : f64 =
    let z = -(x * x) / 4.0
    let (_, s) = loop (term, acc) = (x / 2.0, x / 2.0) for k < 96 do
      let k1 = f64.i32 (k + 1)
      let k2 = f64.i32 (k + 2)
      let next = term * z / (k1 * k2)
      in (next, acc + next)
    in s

  def j0_checked (x: f64) : checked =
    if f64.isnan x || f64.isinf x then {value = nan, status = #nonfinite}
    else if f64.abs x > 1024.0 then {value = nan, status = #out_of_domain}
    else if f64.abs x > 20.0 then {value = nan, status = #out_of_domain}
    else {value = j0_series x, status = #ok}

  def j1_checked (x: f64) : checked =
    if f64.isnan x || f64.isinf x then {value = nan, status = #nonfinite}
    else if f64.abs x > 1024.0 then {value = nan, status = #out_of_domain}
    else if f64.abs x > 20.0 then {value = nan, status = #out_of_domain}
    else {value = j1_series x, status = #ok}

  def sign_change (a: f64) (b: f64) =
    (a <= 0.0 && b >= 0.0) || (a >= 0.0 && b <= 0.0)

  -- Bracketed bisection over asymptotic half-period brackets.  Only roots
  -- whose complete bracket is inside the prototype evaluator are enabled.
  def positive_j1_root (index: i32) : root_result =
    let pi = 3.141592653589793238462643383279502884
    let center = (f64.i32 index + 0.25) * pi
    let lo0 = center - pi / 4.0
    let hi0 = center + pi / 4.0
    let valid = index >= 1 && hi0 <= 20.0
    let flo0 = if valid then j1_series lo0 else 1.0
    let fhi0 = if valid then j1_series hi0 else 1.0
    let bracketed = valid && sign_change flo0 fhi0
    let (lo, hi, flo, fhi, iterations) =
      loop (lo, hi, flo, fhi, it) = (lo0, hi0, flo0, fhi0, 0) while
        bracketed && it < 96 && hi - lo > 2.0e-15 do
        let mid = lo + (hi - lo) / 2.0
        let fm = j1_series mid
        in if sign_change flo fm
           then (lo, mid, flo, fm, it + 1)
           else (mid, hi, fm, fhi, it + 1)
    let root = lo + (hi - lo) / 2.0
    let residual = if bracketed then f64.abs (j1_series root) else 1.0 / 0.0
    in {
      root = if bracketed then root else nan,
      lo = if bracketed then lo else nan,
      hi = if bracketed then hi else nan,
      residual,
      iterations,
      converged = bracketed && hi - lo <= 2.0e-15,
    }
}

module f32 = {
  type status = #ok | #out_of_domain | #nonfinite
  type checked = {value: f32, status: status}
  type root_result = {
    root: f32,
    lo: f32,
    hi: f32,
    residual: f32,
    iterations: i32,
    converged: bool,
  }

  def nan : f32 = f32.from_bits 0x7fc00000u32

  def j0_series (x: f32) : f32 =
    let z = -(x * x) / 4.0
    let (_, s) = loop (term, acc) = (1.0, 1.0) for k < 48 do
      let d = f32.i32 (k + 1)
      let next = term * z / (d * d)
      in (next, acc + next)
    in s

  def j1_series (x: f32) : f32 =
    let z = -(x * x) / 4.0
    let (_, s) = loop (term, acc) = (x / 2.0, x / 2.0) for k < 48 do
      let k1 = f32.i32 (k + 1)
      let k2 = f32.i32 (k + 2)
      let next = term * z / (k1 * k2)
      in (next, acc + next)
    in s

  def j0_checked (x: f32) : checked =
    if f32.isnan x || f32.isinf x then {value = nan, status = #nonfinite}
    else if f32.abs x > 1024.0 then {value = nan, status = #out_of_domain}
    else if f32.abs x > 12.0 then {value = nan, status = #out_of_domain}
    else {value = j0_series x, status = #ok}

  def j1_checked (x: f32) : checked =
    if f32.isnan x || f32.isinf x then {value = nan, status = #nonfinite}
    else if f32.abs x > 1024.0 then {value = nan, status = #out_of_domain}
    else if f32.abs x > 12.0 then {value = nan, status = #out_of_domain}
    else {value = j1_series x, status = #ok}

  def sign_change (a: f32) (b: f32) =
    (a <= 0.0 && b >= 0.0) || (a >= 0.0 && b <= 0.0)

  def positive_j1_root (index: i32) : root_result =
    let pi = 3.1415927410125732421875
    let center = (f32.i32 index + 0.25) * pi
    let lo0 = center - pi / 4.0
    let hi0 = center + pi / 4.0
    let valid = index >= 1 && hi0 <= 12.0
    let flo0 = if valid then j1_series lo0 else 1.0
    let fhi0 = if valid then j1_series hi0 else 1.0
    let bracketed = valid && sign_change flo0 fhi0
    let (lo, hi, flo, fhi, iterations) =
      loop (lo, hi, flo, fhi, it) = (lo0, hi0, flo0, fhi0, 0) while
        bracketed && it < 48 && hi - lo > 2.0e-6 do
        let mid = lo + (hi - lo) / 2.0
        let fm = j1_series mid
        in if sign_change flo fm
           then (lo, mid, flo, fm, it + 1)
           else (mid, hi, fm, fhi, it + 1)
    let root = lo + (hi - lo) / 2.0
    let residual = if bracketed then f32.abs (j1_series root) else 1.0 / 0.0
    in {
      root = if bracketed then root else nan,
      lo = if bracketed then lo else nan,
      hi = if bracketed then hi else nan,
      residual,
      iterations,
      converged = bracketed && hi - lo <= 2.0e-6,
    }
}
