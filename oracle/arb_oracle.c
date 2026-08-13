/* SPDX-License-Identifier: ISC
 *
 * Independent interval evidence through FLINT/Arb.  This program calls Arb's
 * certified hypergeometric Bessel implementation; it shares no approximation
 * coefficients or range-reduction code with the Futhark prototype.
 */
#include <flint/arb.h>
#include <flint/arb_hypgeom.h>
#include <flint/arf.h>
#include <flint/flint.h>
#include <math.h>
#include <stdio.h>

static void print_ball(const char *kind, long index, const arb_t x,
                       const arb_t value) {
  printf("{\"kind\":\"%s\",\"index\":%ld,\"x\":\"", kind, index);
  arb_printn(x, 80, ARB_STR_NO_RADIUS);
  printf("\",\"value\":\"");
  arb_printn(value, 80, 0);
  printf("\"}\n");
}

static void emit_value(const char *kind, long index, const char *x_text,
                       long order) {
  arb_t x, nu, value;
  arb_init(x);
  arb_init(nu);
  arb_init(value);
  if (arb_set_str(x, x_text, 384) != 0) {
    flint_abort();
  }
  arb_set_si(nu, order);
  arb_hypgeom_bessel_j(value, nu, x, 384);
  print_ball(kind, index, x, value);
  arb_clear(x);
  arb_clear(nu);
  arb_clear(value);
}

static void bessel_j1(arb_t value, const arb_t x) {
  arb_t nu;
  arb_init(nu);
  arb_one(nu);
  arb_hypgeom_bessel_j(value, nu, x, 384);
  arb_clear(nu);
}

static int strict_sign(const arb_t x) {
  if (arb_is_positive(x)) {
    return 1;
  }
  if (arb_is_negative(x)) {
    return -1;
  }
  return 0;
}

static void emit_root_bracket(long index, const arb_t pi) {
  arb_t lo, hi, mid, flo, fhi, fmid, exact_lo, exact_hi;
  arf_t endpoint;
  double lo_d, hi_d;
  arb_init(lo);
  arb_init(hi);
  arb_init(mid);
  arb_init(flo);
  arb_init(fhi);
  arb_init(fmid);
  arb_init(exact_lo);
  arb_init(exact_hi);
  arf_init(endpoint);

  /* Classical half-period bracket [n*pi, (n+1/2)*pi]. */
  arb_mul_si(lo, pi, index, 384);
  arb_mul_si(hi, pi, 2 * index + 1, 384);
  arb_mul_2exp_si(hi, hi, -1);
  bessel_j1(flo, lo);
  bessel_j1(fhi, hi);
  int sign_lo = strict_sign(flo);
  int sign_hi = strict_sign(fhi);
  if (sign_lo == 0 || sign_hi == 0 || sign_lo == sign_hi) {
    fprintf(stderr, "uncertified initial bracket at root %ld: signs %d %d\n",
            index, sign_lo, sign_hi);
    flint_abort();
  }

  for (long iteration = 0; iteration < 160; ++iteration) {
    arb_add(mid, lo, hi, 384);
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

  arb_get_lbound_arf(endpoint, lo, 384);
  lo_d = arf_get_d(endpoint, ARF_RND_FLOOR);
  arb_get_ubound_arf(endpoint, hi, 384);
  hi_d = arf_get_d(endpoint, ARF_RND_CEIL);
  arb_set_d(exact_lo, lo_d);
  arb_set_d(exact_hi, hi_d);
  bessel_j1(flo, exact_lo);
  bessel_j1(fhi, exact_hi);
  sign_lo = strict_sign(flo);
  sign_hi = strict_sign(fhi);
  if (!(lo_d < hi_d) || sign_lo == 0 || sign_hi == 0 || sign_lo == sign_hi) {
    fprintf(stderr,
            "uncertified binary64 bracket at root %ld: %a %a signs %d %d\n",
            index, lo_d, hi_d, sign_lo, sign_hi);
    flint_abort();
  }

  printf("{\"kind\":\"j1_root_bracket\",\"index\":%ld,", index);
  printf("\"lo_hex\":\"%a\",\"hi_hex\":\"%a\",", lo_d, hi_d);
  printf("\"j1_lo\":\"");
  arb_printn(flo, 40, 0);
  printf("\",\"j1_hi\":\"");
  arb_printn(fhi, 40, 0);
  printf("\",\"bisections\":160,\"certified_sign_change\":true}\n");

  arf_clear(endpoint);
  arb_clear(lo);
  arb_clear(hi);
  arb_clear(mid);
  arb_clear(flo);
  arb_clear(fhi);
  arb_clear(fmid);
  arb_clear(exact_lo);
  arb_clear(exact_hi);
}

int main(void) {
  const char *points[] = {
      "-20", "-12", "-8", "-1", "-0", "0", "1", "8", "12", "20",
  };
  const long npoints = (long)(sizeof(points) / sizeof(points[0]));
  for (long i = 0; i < npoints; ++i) {
    emit_value("j0", i, points[i], 0);
    emit_value("j1", i, points[i], 1);
  }
  arb_t pi;
  arb_init(pi);
  arb_const_pi(pi, 384);
  for (long index = 1; index <= 256; ++index) {
    emit_root_bracket(index, pi);
  }
  arb_clear(pi);
  flint_cleanup();
  return 0;
}
