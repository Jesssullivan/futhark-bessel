-- SPDX-License-Identifier: ISC
-- Stable package facade.  The suffix prevents public module names from
-- shadowing Futhark's scalar prelude modules during whole-program elaboration.

import "bessel_internal"

module f64_bessel = f64_impl
module f32_bessel = f32_impl
