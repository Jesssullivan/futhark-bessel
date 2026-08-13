/* SPDX-License-Identifier: ISC
 *
 * Independent f32 cached-root envelope certificates through FLINT/Arb.
 * This program recomputes each mathematical J1 root without consuming the
 * Futhark implementation or generated cache, proves unique IEEE binary32
 * rounding, and bounds |J1(r_hat)| at that exact rounded value.
 */
#include <mpfr.h>
#include <flint/arb.h>
#include <flint/arb_hypgeom.h>
#include <flint/arf.h>
#include <flint/flint.h>
#include <inttypes.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

enum { PRECISION_BITS = 512, BISECTIONS = 192 };

static uint32_t f32_bits(float value) {
  uint32_t bits;
  memcpy(&bits, &value, sizeof(bits));
  return bits;
}

static void bessel_j1(arb_t value, const arb_t x) {
  arb_t order;
  arb_init(order);
  arb_one(order);
  arb_hypgeom_bessel_j(value, order, x, PRECISION_BITS);
  arb_clear(order);
}

static int strict_sign(const arb_t value) {
  if (arb_is_positive(value)) {
    return 1;
  }
  if (arb_is_negative(value)) {
    return -1;
  }
  return 0;
}

static float unique_f32_rounding_between(const arb_t lo_ball,
                                         const arb_t hi_ball) {
  mpfr_t lo, ignored_lo_hi, ignored_hi_lo, hi;
  mpfr_init2(lo, PRECISION_BITS);
  mpfr_init2(ignored_lo_hi, PRECISION_BITS);
  mpfr_init2(ignored_hi_lo, PRECISION_BITS);
  mpfr_init2(hi, PRECISION_BITS);
  arb_get_interval_mpfr(lo, ignored_lo_hi, lo_ball);
  arb_get_interval_mpfr(ignored_hi_lo, hi, hi_ball);
  const float rounded_lo = mpfr_get_flt(lo, MPFR_RNDN);
  const float rounded_hi = mpfr_get_flt(hi, MPFR_RNDN);
  if (f32_bits(rounded_lo) != f32_bits(rounded_hi)) {
    fprintf(stderr, "root bracket does not certify unique f32 rounding\n");
    flint_abort();
  }
  mpfr_clear(lo);
  mpfr_clear(ignored_lo_hi);
  mpfr_clear(ignored_hi_lo);
  mpfr_clear(hi);
  return rounded_lo;
}

static void emit_root_envelope(long index, const arb_t pi) {
  arb_t lo, hi, mid, flo, fhi, fmid, rounded_x, residual;
  arf_t residual_upper;
  arb_init(lo);
  arb_init(hi);
  arb_init(mid);
  arb_init(flo);
  arb_init(fhi);
  arb_init(fmid);
  arb_init(rounded_x);
  arb_init(residual);
  arf_init(residual_upper);

  /* Classical isolating interval [n*pi, (n+1/2)*pi]. */
  arb_mul_si(lo, pi, index, PRECISION_BITS);
  arb_mul_si(hi, pi, 2 * index + 1, PRECISION_BITS);
  arb_mul_2exp_si(hi, hi, -1);
  bessel_j1(flo, lo);
  bessel_j1(fhi, hi);
  int sign_lo = strict_sign(flo);
  const int sign_hi = strict_sign(fhi);
  if (sign_lo == 0 || sign_hi == 0 || sign_lo == sign_hi) {
    fprintf(stderr, "uncertified initial bracket at root %ld\n", index);
    flint_abort();
  }

  for (long iteration = 0; iteration < BISECTIONS; ++iteration) {
    arb_add(mid, lo, hi, PRECISION_BITS);
    arb_mul_2exp_si(mid, mid, -1);
    bessel_j1(fmid, mid);
    const int sign_mid = strict_sign(fmid);
    if (sign_mid == 0) {
      fprintf(stderr, "uncertified midpoint at root %ld iteration %ld\n", index,
              iteration);
      flint_abort();
    }
    if (sign_mid == sign_lo) {
      arb_set(lo, mid);
      arb_set(flo, fmid);
    } else {
      arb_set(hi, mid);
      arb_set(fhi, fmid);
    }
  }

  const float rounded = unique_f32_rounding_between(lo, hi);
  arb_set_d(rounded_x, (double)rounded);
  bessel_j1(residual, rounded_x);
  arb_abs(residual, residual);
  arb_get_ubound_arf(residual_upper, residual, PRECISION_BITS);
  const double upper = arf_get_d(residual_upper, ARF_RND_CEIL);
  if (!(upper >= 0.0) || !isfinite(upper)) {
    fprintf(stderr, "invalid residual bound at root %ld\n", index);
    flint_abort();
  }

  printf("{\"kind\":\"f32_cached_j1_root_envelope\",\"index\":%ld,", index);
  printf("\"root_f32_bits\":\"0x%08" PRIx32 "\",", f32_bits(rounded));
  printf("\"root_f32_hex\":\"%a\",", (double)rounded);
  printf("\"true_residual_ball\":\"");
  arb_printn(residual, 80, 0);
  printf("\",\"true_residual_upper_hex\":\"%a\",", upper);
  printf("\"bisections\":%d,\"certified_unique_f32_rounding\":true,",
         BISECTIONS);
  printf("\"certified_true_residual\":true}\n");

  arf_clear(residual_upper);
  arb_clear(lo);
  arb_clear(hi);
  arb_clear(mid);
  arb_clear(flo);
  arb_clear(fhi);
  arb_clear(fmid);
  arb_clear(rounded_x);
  arb_clear(residual);
}

int main(void) {
  arb_t pi;
  arb_init(pi);
  arb_const_pi(pi, PRECISION_BITS);
  for (long index = 1; index <= 256; ++index) {
    emit_root_envelope(index, pi);
  }
  arb_clear(pi);
  flint_cleanup();
  return 0;
}
