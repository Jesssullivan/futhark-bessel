-- SPDX-License-Identifier: ISC

import "../lib/github.com/Jesssullivan/futhark-bessel/bessel"

-- Runtime observation surface shared by the sequential C and WASM backends.
-- Inputs are raw IEEE bits from the independent Arb-generated sample ledger.
-- Outputs remain raw bits so the Python harness observes every backend bit.

entry observe_f32 (x_bits: []u32) (root_indices: []i32) : []u32 =
  let xs = map f32.from_bits x_bits
  let j0_bits = map (\x -> f32.to_bits (f32_bessel.j0_checked x).value) xs
  let j1_bits = map (\x -> f32.to_bits (f32_bessel.j1_checked x).value) xs
  let roots = map f32_bessel.positive_j1_root root_indices
  let root_bits = map (\root -> f32.to_bits root.root) roots
  let residual_bits = map (\root -> f32.to_bits root.residual) roots
  in j0_bits ++ j1_bits ++ root_bits ++ residual_bits

entry observe_f64 (x_bits: []u64) (root_indices: []i32) : []u64 =
  let xs = map f64.from_bits x_bits
  let j0_bits = map (\x -> f64.to_bits (f64_bessel.j0_checked x).value) xs
  let j1_bits = map (\x -> f64.to_bits (f64_bessel.j1_checked x).value) xs
  let roots = map f64_bessel.positive_j1_root root_indices
  let root_bits = map (\root -> f64.to_bits root.root) roots
  let residual_bits = map (\root -> f64.to_bits root.residual) roots
  in j0_bits ++ j1_bits ++ root_bits ++ residual_bits
