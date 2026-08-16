/* SPDX-License-Identifier: ISC
 *
 * Independent interval evidence through FLINT/Arb.  This program calls Arb's
 * certified hypergeometric Bessel implementation; it shares no approximation
 * coefficients or range-reduction code with the Futhark prototype.
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

static uint64_t f64_bits(double value) {
  uint64_t bits;
  memcpy(&bits, &value, sizeof(bits));
  return bits;
}

static uint32_t f32_bits(float value) {
  uint32_t bits;
  memcpy(&bits, &value, sizeof(bits));
  return bits;
}

static void unique_rounding(const arb_t value, double *rounded_f64,
                            float *rounded_f32) {
  mpfr_t lo, hi;
  mpfr_init2(lo, 512);
  mpfr_init2(hi, 512);
  arb_get_interval_mpfr(lo, hi, value);
  const double lo64 = mpfr_get_d(lo, MPFR_RNDN);
  const double hi64 = mpfr_get_d(hi, MPFR_RNDN);
  const float lo32 = mpfr_get_flt(lo, MPFR_RNDN);
  const float hi32 = mpfr_get_flt(hi, MPFR_RNDN);
  if (f64_bits(lo64) != f64_bits(hi64) ||
      f32_bits(lo32) != f32_bits(hi32)) {
    fprintf(stderr, "Arb ball does not certify unique IEEE rounding\n");
    flint_abort();
  }
  *rounded_f64 = lo64;
  *rounded_f32 = lo32;
  mpfr_clear(lo);
  mpfr_clear(hi);
}

static void unique_rounding_between(const arb_t lo_ball, const arb_t hi_ball,
                                    double *rounded_f64,
                                    float *rounded_f32) {
  mpfr_t lo, ignored_lo_hi, ignored_hi_lo, hi;
  mpfr_init2(lo, 512);
  mpfr_init2(ignored_lo_hi, 512);
  mpfr_init2(ignored_hi_lo, 512);
  mpfr_init2(hi, 512);
  arb_get_interval_mpfr(lo, ignored_lo_hi, lo_ball);
  arb_get_interval_mpfr(ignored_hi_lo, hi, hi_ball);
  const double lo64 = mpfr_get_d(lo, MPFR_RNDN);
  const double hi64 = mpfr_get_d(hi, MPFR_RNDN);
  const float lo32 = mpfr_get_flt(lo, MPFR_RNDN);
  const float hi32 = mpfr_get_flt(hi, MPFR_RNDN);
  if (f64_bits(lo64) != f64_bits(hi64) ||
      f32_bits(lo32) != f32_bits(hi32)) {
    fprintf(stderr, "root bracket does not certify unique IEEE rounding\n");
    flint_abort();
  }
  *rounded_f64 = lo64;
  *rounded_f32 = lo32;
  mpfr_clear(lo);
  mpfr_clear(ignored_lo_hi);
  mpfr_clear(ignored_hi_lo);
  mpfr_clear(hi);
}

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

static void bessel_j(arb_t value, const arb_t x, long order) {
  arb_t nu;
  arb_init(nu);
  arb_set_si(nu, order);
  arb_hypgeom_bessel_j(value, nu, x, 384);
  arb_clear(nu);
}

static void emit_conformance_value_f64(long index, double input) {
  arb_t x, j0, j1;
  double j0_reference, j1_reference;
  float ignored32;
  arb_init(x);
  arb_init(j0);
  arb_init(j1);
  arb_set_d(x, input);
  bessel_j(j0, x, 0);
  bessel_j(j1, x, 1);
  unique_rounding(j0, &j0_reference, &ignored32);
  unique_rounding(j1, &j1_reference, &ignored32);
  printf("{\"kind\":\"conformance_value\",\"precision\":\"f64\",");
  printf("\"index\":%ld,\"domain\":\"%s\",", index,
         fabs(input) <= 12.0 ? "series" : "asymptotic");
  printf("\"x_bits\":\"0x%016" PRIx64 "\",", f64_bits(input));
  printf("\"j0_reference_bits\":\"0x%016" PRIx64 "\",",
         f64_bits(j0_reference));
  printf("\"j1_reference_bits\":\"0x%016" PRIx64 "\",",
         f64_bits(j1_reference));
  printf("\"j0_ball\":\"");
  arb_printn(j0, 80, 0);
  printf("\",\"j1_ball\":\"");
  arb_printn(j1, 80, 0);
  printf("\",\"certified_unique_rounding\":true}\n");
  arb_clear(x);
  arb_clear(j0);
  arb_clear(j1);
}

static void emit_conformance_value_f32(long index, float input) {
  arb_t x, j0, j1;
  double ignored64;
  float j0_reference, j1_reference;
  arb_init(x);
  arb_init(j0);
  arb_init(j1);
  arb_set_d(x, (double)input);
  bessel_j(j0, x, 0);
  bessel_j(j1, x, 1);
  unique_rounding(j0, &ignored64, &j0_reference);
  unique_rounding(j1, &ignored64, &j1_reference);
  printf("{\"kind\":\"conformance_value\",\"precision\":\"f32\",");
  printf("\"index\":%ld,\"domain\":\"%s\",", index,
         fabsf(input) <= 6.0f ? "series" : "asymptotic");
  printf("\"x_bits\":\"0x%08" PRIx32 "\",", f32_bits(input));
  printf("\"j0_reference_bits\":\"0x%08" PRIx32 "\",",
         f32_bits(j0_reference));
  printf("\"j1_reference_bits\":\"0x%08" PRIx32 "\",",
         f32_bits(j1_reference));
  printf("\"j0_ball\":\"");
  arb_printn(j0, 80, 0);
  printf("\",\"j1_ball\":\"");
  arb_printn(j1, 80, 0);
  printf("\",\"certified_unique_rounding\":true}\n");
  arb_clear(x);
  arb_clear(j0);
  arb_clear(j1);
}

static void emit_conformance_values(void) {
  const double below12 = nextafter(12.0, 0.0);
  const double above12 = nextafter(12.0, INFINITY);
  const double f64_points[] = {
      -1024.0, -768.0, -512.0, -256.0, -128.0, -64.0, -32.0, -20.0,
      -above12, -12.0, -below12, -6.0, -3.0, -1.0, -0.5,
      -0x1.0p-20, 0.0, 0x1.0p-20, 0.5, 1.0, 3.0, 6.0,
      below12, 12.0, above12, 20.0, 32.0, 64.0, 128.0, 256.0,
      512.0, 768.0, 1024.0,
  };
  const float below6 = nextafterf(6.0f, 0.0f);
  const float above6 = nextafterf(6.0f, INFINITY);
  const float f32_points[] = {
      -1024.0f, -768.0f, -512.0f, -256.0f, -128.0f, -64.0f, -32.0f,
      -20.0f, -12.0f, -above6, -6.0f, -below6, -3.0f, -1.0f, -0.5f,
      -0x1.0p-10f, 0.0f, 0x1.0p-10f, 0.5f, 1.0f, 3.0f, below6,
      6.0f, above6, 12.0f, 20.0f, 32.0f, 64.0f, 128.0f, 256.0f,
      512.0f, 768.0f, 1024.0f,
  };
  const long f64_count =
      (long)(sizeof(f64_points) / sizeof(f64_points[0]));
  const long f32_count =
      (long)(sizeof(f32_points) / sizeof(f32_points[0]));
  for (long index = 0; index < f64_count; ++index) {
    emit_conformance_value_f64(index, f64_points[index]);
  }
  for (long index = 0; index < f32_count; ++index) {
    emit_conformance_value_f32(index, f32_points[index]);
  }
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
  double reference_f64;
  float reference_f32;
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

  unique_rounding_between(lo, hi, &reference_f64, &reference_f32);

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
  printf("\",\"root_f64_reference_bits\":\"0x%016" PRIx64 "\",",
         f64_bits(reference_f64));
  printf("\"root_f32_reference_bits\":\"0x%08" PRIx32 "\",",
         f32_bits(reference_f32));
  printf("\"bisections\":160,\"certified_sign_change\":true,");
  printf("\"certified_unique_rounding\":true}\n");

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
  emit_conformance_values();
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
