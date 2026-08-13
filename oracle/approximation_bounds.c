/* SPDX-License-Identifier: ISC
 *
 * Whole-domain real-arithmetic approximation certificates for the current
 * definition-derived Futhark algorithm.  Every binary floating-point literal
 * is interpreted as its exact dyadic real value here.  This program does not
 * model the rounding or reassociation of Futhark backends; that is a separate,
 * deliberately open release gate.
 *
 * The proof combines:
 *   - the alternating-series remainder after terms are monotonically decreasing;
 *   - DLMF 10.17(iii)'s first-neglected-term bounds for the P and Q Hankel sums;
 *   - an exhaustive partition at every round((x-offset)*(2/pi)) boundary;
 *   - Taylor remainders on the certified reduced-argument interval; and
 *   - Lipschitz phase propagation plus the rounded-prefactor discrepancy.
 */
#include <flint/arb.h>
#include <flint/arb_hypgeom.h>
#include <flint/arf.h>
#include <flint/flint.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

#if __FLINT_VERSION != 3 || __FLINT_VERSION_MINOR != 6 ||                      \
    __FLINT_VERSION_PATCHLEVEL != 0
#error "approximation certificates require FLINT/Arb 3.6.0"
#endif

#define PREC 1024
#define DOMAIN_MAX 1024.0
#define N_ABS_BOUND 653L

typedef struct {
  const char *precision;
  double switch_x;
  long series_last;
  long hankel_last;
  long sin_first_omitted;
  long cos_first_omitted;
  double two_over_pi;
  double pio2_hi;
  double pio2_lo;
  double pio2_tail;
  double pi_used;
  double offsets[2];
} config_t;

static const config_t CONFIGS[] = {
    {.precision = "f32",
     .switch_x = 6.0,
     .series_last = 48,
     .hankel_last = 7,
     .sin_first_omitted = 11,
     .cos_first_omitted = 12,
     .two_over_pi = (double)0x1.45f306p-1f,
     .pio2_hi = (double)0x1.9218p+0f,
     .pio2_lo = (double)0x1.ed511p-14f,
     .pio2_tail = (double)0x1.68c234p-39f,
     .pi_used = (double)0x1.921fb6p+1f,
     .offsets = {(double)0x1.921fb6p-1f, (double)0x1.2d97c8p+1f}},
    {.precision = "f64",
     .switch_x = 12.0,
     .series_last = 96,
     .hankel_last = 12,
     .sin_first_omitted = 15,
     .cos_first_omitted = 14,
     .two_over_pi = 0x1.45f306dc9c883p-1,
     .pio2_hi = 0x1.921fb54000000p+0,
     .pio2_lo = 0x1.10b4611a62633p-30,
     .pio2_tail = 0x1.45c06e0e68948p-86,
     .pi_used = 0x1.921fb54442d18p+1,
     .offsets = {0x1.921fb54442d18p-1, 0x1.2d97c7f3321d2p+1}},
};

static double upper_abs(const arb_t value) {
  arb_t magnitude;
  arf_t upper;
  double result;
  arb_init(magnitude);
  arf_init(upper);
  arb_abs(magnitude, value);
  arb_get_ubound_arf(upper, magnitude, PREC);
  result = arf_get_d(upper, ARF_RND_CEIL);
  arf_clear(upper);
  arb_clear(magnitude);
  return result;
}

static void interval_f64(const arb_t value, double *lo, double *hi) {
  arf_t endpoint;
  arf_init(endpoint);
  arb_get_lbound_arf(endpoint, value, PREC);
  *lo = arf_get_d(endpoint, ARF_RND_FLOOR);
  arb_get_ubound_arf(endpoint, value, PREC);
  *hi = arf_get_d(endpoint, ARF_RND_CEIL);
  arf_clear(endpoint);
}

static void set_half(arb_t value) {
  arb_one(value);
  arb_mul_2exp_si(value, value, -1);
}

static void hankel_coefficient(arb_t result, long order, long m) {
  arb_t factor;
  arb_init(factor);
  arb_one(result);
  for (long k = 1; k <= m; ++k) {
    const long odd = 2 * k - 1;
    arb_set_si(factor, 4 * order * order - odd * odd);
    arb_mul(result, result, factor, PREC);
    arb_div_ui(result, result, (unsigned long)(8 * k), PREC);
  }
  arb_clear(factor);
}

static long first_after_with_parity(long last, long parity) {
  long value = last + 1;
  if (value % 2 != parity) {
    ++value;
  }
  return value;
}

static void series_components(arb_t bound, arb_t ratio, const config_t *cfg,
                              long order) {
  const unsigned long omitted = (unsigned long)(cfg->series_last + 1);
  arb_t x, z, power, first_factorial, second_factorial, denominator;
  arb_init(x);
  arb_init(z);
  arb_init(power);
  arb_init(first_factorial);
  arb_init(second_factorial);
  arb_init(denominator);
  arb_set_d(x, cfg->switch_x);
  arb_mul(z, x, x, PREC);
  arb_div_ui(z, z, 4, PREC);
  arb_pow_ui(power, z, omitted, PREC);
  arb_fac_ui(first_factorial, omitted, PREC);
  arb_fac_ui(second_factorial, omitted + (unsigned long)order, PREC);
  arb_mul(denominator, first_factorial, second_factorial, PREC);
  arb_div(bound, power, denominator, PREC);
  if (order == 1) {
    arb_mul(bound, bound, x, PREC);
    arb_div_ui(bound, bound, 2, PREC);
  }

  arb_set(ratio, z);
  if (order == 0) {
    arb_div_ui(ratio, ratio, (omitted + 1) * (omitted + 1), PREC);
  } else {
    arb_div_ui(ratio, ratio, (omitted + 1) * (omitted + 2), PREC);
  }
  arb_clear(x);
  arb_clear(z);
  arb_clear(power);
  arb_clear(first_factorial);
  arb_clear(second_factorial);
  arb_clear(denominator);
}

static void hankel_components(arb_t p_abs, arb_t q_abs, arb_t p_remainder,
                              arb_t q_remainder, const config_t *cfg,
                              long order) {
  const long first_even = first_after_with_parity(cfg->hankel_last, 0);
  const long first_odd = first_after_with_parity(cfg->hankel_last, 1);
  arb_t x, coefficient, magnitude, power;
  arb_init(x);
  arb_init(coefficient);
  arb_init(magnitude);
  arb_init(power);
  arb_set_d(x, cfg->switch_x);
  arb_zero(p_abs);
  arb_zero(q_abs);
  for (long m = 0; m <= cfg->hankel_last; ++m) {
    hankel_coefficient(coefficient, order, m);
    arb_abs(magnitude, coefficient);
    arb_pow_ui(power, x, (unsigned long)m, PREC);
    arb_div(magnitude, magnitude, power, PREC);
    if (m % 2 == 0) {
      arb_add(p_abs, p_abs, magnitude, PREC);
    } else {
      arb_add(q_abs, q_abs, magnitude, PREC);
    }
  }
  hankel_coefficient(coefficient, order, first_even);
  arb_abs(magnitude, coefficient);
  arb_pow_ui(power, x, (unsigned long)first_even, PREC);
  arb_div(p_remainder, magnitude, power, PREC);
  hankel_coefficient(coefficient, order, first_odd);
  arb_abs(magnitude, coefficient);
  arb_pow_ui(power, x, (unsigned long)first_odd, PREC);
  arb_div(q_remainder, magnitude, power, PREC);
  arb_clear(x);
  arb_clear(coefficient);
  arb_clear(magnitude);
  arb_clear(power);
}

static void split_sum(arb_t result, const config_t *cfg) {
  arb_t part;
  arb_init(part);
  arb_set_d(result, cfg->pio2_hi);
  arb_set_d(part, cfg->pio2_lo);
  arb_add(result, result, part, PREC);
  arb_set_d(part, cfg->pio2_tail);
  arb_add(result, result, part, PREC);
  arb_clear(part);
}

static void taylor_remainder(arb_t result, const arb_t radius,
                             long first_omitted) {
  arb_t factorial;
  arb_init(factorial);
  arb_pow_ui(result, radius, (unsigned long)first_omitted, PREC);
  arb_fac_ui(factorial, (unsigned long)first_omitted, PREC);
  arb_div(result, result, factorial, PREC);
  arb_clear(factorial);
}

static void phase_components(arb_t phase_error, arb_t reduced_radius,
                             arb_t sin_error, arb_t cos_error,
                             arb_t prefactor_true, arb_t prefactor_error,
                             arb_t n_expression, const config_t *cfg,
                             long order, const arb_t pi) {
  arb_t offset, true_offset, split, split_error, reciprocal, reciprocal_error;
  arb_t half, n_bound, max_x, phase_max, c, pi_used, temporary;
  arb_t sin_remainder, cos_remainder;
  arb_init(offset);
  arb_init(true_offset);
  arb_init(split);
  arb_init(split_error);
  arb_init(reciprocal);
  arb_init(reciprocal_error);
  arb_init(half);
  arb_init(n_bound);
  arb_init(max_x);
  arb_init(phase_max);
  arb_init(c);
  arb_init(pi_used);
  arb_init(temporary);
  arb_init(sin_remainder);
  arb_init(cos_remainder);
  arb_set_d(offset, cfg->offsets[order]);
  arb_mul_ui(true_offset, pi, (unsigned long)(2 * order + 1), PREC);
  arb_div_ui(true_offset, true_offset, 4, PREC);
  arb_sub(phase_error, true_offset, offset, PREC);
  arb_abs(phase_error, phase_error);
  split_sum(split, cfg);
  arb_mul_2exp_si(temporary, pi, -1);
  arb_sub(split_error, temporary, split, PREC);
  arb_abs(split_error, split_error);
  arb_set_si(n_bound, N_ABS_BOUND);
  arb_mul(temporary, n_bound, split_error, PREC);
  arb_add(phase_error, phase_error, temporary, PREC);

  arb_set_d(c, cfg->two_over_pi);
  arb_inv(reciprocal, c, PREC);
  arb_sub(reciprocal_error, reciprocal, split, PREC);
  arb_abs(reciprocal_error, reciprocal_error);
  set_half(half);
  arb_mul(reduced_radius, half, reciprocal, PREC);
  arb_mul(temporary, n_bound, reciprocal_error, PREC);
  arb_add(reduced_radius, reduced_radius, temporary, PREC);

  taylor_remainder(sin_remainder, reduced_radius,
                   cfg->sin_first_omitted);
  taylor_remainder(cos_remainder, reduced_radius,
                   cfg->cos_first_omitted);
  /* Quadrants 1 and 3 swap the sine and cosine polynomials.  Use one
   * conservative bound for both reconstructed outputs so every quadrant is
   * covered without assuming which Taylor tail is larger. */
  arb_add(temporary, sin_remainder, cos_remainder, PREC);
  arb_add(sin_error, phase_error, temporary, PREC);
  arb_set(cos_error, sin_error);

  arb_set_d(max_x, DOMAIN_MAX);
  arb_sub(phase_max, max_x, offset, PREC);
  arb_mul(n_expression, phase_max, c, PREC);
  arb_add(n_expression, n_expression, half, PREC);

  arb_set_d(temporary, cfg->switch_x);
  arb_mul(temporary, temporary, pi, PREC);
  arb_ui_div(prefactor_true, 2, temporary, PREC);
  arb_sqrt(prefactor_true, prefactor_true, PREC);
  arb_set_d(pi_used, cfg->pi_used);
  arb_set_d(temporary, cfg->switch_x);
  arb_mul(temporary, temporary, pi_used, PREC);
  arb_ui_div(prefactor_error, 2, temporary, PREC);
  arb_sqrt(prefactor_error, prefactor_error, PREC);
  arb_sub(prefactor_error, prefactor_error, prefactor_true, PREC);
  arb_abs(prefactor_error, prefactor_error);

  arb_clear(offset);
  arb_clear(true_offset);
  arb_clear(split);
  arb_clear(split_error);
  arb_clear(reciprocal);
  arb_clear(reciprocal_error);
  arb_clear(half);
  arb_clear(n_bound);
  arb_clear(max_x);
  arb_clear(phase_max);
  arb_clear(c);
  arb_clear(pi_used);
  arb_clear(temporary);
  arb_clear(sin_remainder);
  arb_clear(cos_remainder);
}

static void exact_series_value(arb_t result, const arb_t x, long order,
                               long last) {
  arb_t z, term, denominator, temporary;
  arb_init(z);
  arb_init(term);
  arb_init(denominator);
  arb_init(temporary);
  arb_mul(z, x, x, PREC);
  arb_neg(z, z);
  arb_div_ui(z, z, 4, PREC);
  if (order == 0) {
    arb_one(term);
  } else {
    arb_set(term, x);
    arb_mul_2exp_si(term, term, -1);
  }
  arb_set(result, term);
  for (long k = 0; k < last; ++k) {
    arb_set_ui(denominator, (unsigned long)(k + 1));
    arb_mul_ui(denominator, denominator,
               (unsigned long)(k + 1 + order), PREC);
    arb_mul(temporary, term, z, PREC);
    arb_div(term, temporary, denominator, PREC);
    arb_add(result, result, term, PREC);
  }
  arb_clear(z);
  arb_clear(term);
  arb_clear(denominator);
  arb_clear(temporary);
}

static void exact_taylor(arb_t result, const arb_t x, int sine,
                         long first_omitted) {
  arb_t power, factorial, term;
  arb_init(power);
  arb_init(factorial);
  arb_init(term);
  arb_zero(result);
  const long start = sine ? 1 : 0;
  for (long degree = start; degree < first_omitted; degree += 2) {
    arb_pow_ui(power, x, (unsigned long)degree, PREC);
    arb_fac_ui(factorial, (unsigned long)degree, PREC);
    arb_div(term, power, factorial, PREC);
    if (((degree - start) / 2) % 2 != 0) {
      arb_neg(term, term);
    }
    arb_add(result, result, term, PREC);
  }
  arb_clear(power);
  arb_clear(factorial);
  arb_clear(term);
}

static long unambiguous_nearest_integer(const arb_t value) {
  const double midpoint = arf_get_d(arb_midref(value), ARF_RND_NEAR);
  const long candidate = (long)nearbyint(midpoint);
  arb_t lower, upper, half;
  arb_init(lower);
  arb_init(upper);
  arb_init(half);
  set_half(half);
  arb_set_si(lower, candidate);
  arb_sub(lower, lower, half, PREC);
  arb_set_si(upper, candidate);
  arb_add(upper, upper, half, PREC);
  if (!arb_gt(value, lower) || !arb_lt(value, upper)) {
    fprintf(stderr, "nearest integer was not uniquely certified\n");
    flint_abort();
  }
  arb_clear(lower);
  arb_clear(upper);
  arb_clear(half);
  return candidate;
}

static void exact_asymptotic_value(arb_t result, const arb_t x,
                                   const config_t *cfg, long order) {
  arb_t offset, phase, c, rounded_argument, split, n_value, reduced;
  arb_t sin_reduced, cos_reduced, sine, cosine, p, q, coefficient;
  arb_t inverse_power, signed_term, pi_used, prefactor, temporary;
  arb_init(offset);
  arb_init(phase);
  arb_init(c);
  arb_init(rounded_argument);
  arb_init(split);
  arb_init(n_value);
  arb_init(reduced);
  arb_init(sin_reduced);
  arb_init(cos_reduced);
  arb_init(sine);
  arb_init(cosine);
  arb_init(p);
  arb_init(q);
  arb_init(coefficient);
  arb_init(inverse_power);
  arb_init(signed_term);
  arb_init(pi_used);
  arb_init(prefactor);
  arb_init(temporary);
  arb_set_d(offset, cfg->offsets[order]);
  arb_sub(phase, x, offset, PREC);
  arb_set_d(c, cfg->two_over_pi);
  arb_mul(rounded_argument, phase, c, PREC);
  const long n = unambiguous_nearest_integer(rounded_argument);
  split_sum(split, cfg);
  arb_set_si(n_value, n);
  arb_mul(temporary, n_value, split, PREC);
  arb_sub(reduced, phase, temporary, PREC);
  exact_taylor(sin_reduced, reduced, 1, cfg->sin_first_omitted);
  exact_taylor(cos_reduced, reduced, 0, cfg->cos_first_omitted);
  switch (((n % 4) + 4) % 4) {
  case 0:
    arb_set(sine, sin_reduced);
    arb_set(cosine, cos_reduced);
    break;
  case 1:
    arb_set(sine, cos_reduced);
    arb_neg(cosine, sin_reduced);
    break;
  case 2:
    arb_neg(sine, sin_reduced);
    arb_neg(cosine, cos_reduced);
    break;
  default:
    arb_neg(sine, cos_reduced);
    arb_set(cosine, sin_reduced);
    break;
  }
  arb_one(p);
  arb_zero(q);
  arb_one(inverse_power);
  for (long m = 1; m <= cfg->hankel_last; ++m) {
    hankel_coefficient(coefficient, order, m);
    arb_div(inverse_power, inverse_power, x, PREC);
    arb_mul(signed_term, coefficient, inverse_power, PREC);
    if ((m / 2) % 2 != 0) {
      arb_neg(signed_term, signed_term);
    }
    if (m % 2 == 0) {
      arb_add(p, p, signed_term, PREC);
    } else {
      arb_add(q, q, signed_term, PREC);
    }
  }
  arb_mul(result, cosine, p, PREC);
  arb_mul(temporary, sine, q, PREC);
  arb_sub(result, result, temporary, PREC);
  arb_set_d(pi_used, cfg->pi_used);
  arb_mul(temporary, pi_used, x, PREC);
  arb_ui_div(prefactor, 2, temporary, PREC);
  arb_sqrt(prefactor, prefactor, PREC);
  arb_mul(result, result, prefactor, PREC);

  arb_clear(offset);
  arb_clear(phase);
  arb_clear(c);
  arb_clear(rounded_argument);
  arb_clear(split);
  arb_clear(n_value);
  arb_clear(reduced);
  arb_clear(sin_reduced);
  arb_clear(cos_reduced);
  arb_clear(sine);
  arb_clear(cosine);
  arb_clear(p);
  arb_clear(q);
  arb_clear(coefficient);
  arb_clear(inverse_power);
  arb_clear(signed_term);
  arb_clear(pi_used);
  arb_clear(prefactor);
  arb_clear(temporary);
}

static void emit_interval_fields(const char *prefix, const arb_t value) {
  double lo, hi;
  interval_f64(value, &lo, &hi);
  printf("\"%s_lo_hex\":\"%a\",\"%s_hi_hex\":\"%a\"", prefix,
         lo, prefix, hi);
}

static void emit_switch_certificate(const config_t *cfg, long order,
                                    const arb_t series_bound,
                                    const arb_t asymptotic_bound) {
  arb_t x, nu, reference, series_value, asymptotic_value, difference, gap;
  arb_init(x);
  arb_init(nu);
  arb_init(reference);
  arb_init(series_value);
  arb_init(asymptotic_value);
  arb_init(difference);
  arb_init(gap);
  arb_set_d(x, cfg->switch_x);
  arb_set_si(nu, order);
  arb_hypgeom_bessel_j(reference, nu, x, PREC);
  exact_series_value(series_value, x, order, cfg->series_last);
  exact_asymptotic_value(asymptotic_value, x, cfg, order);
  arb_sub(difference, series_value, reference, PREC);
  const double series_actual = upper_abs(difference);
  arb_sub(difference, asymptotic_value, reference, PREC);
  const double asymptotic_actual = upper_abs(difference);
  arb_sub(gap, series_value, asymptotic_value, PREC);
  printf("{\"kind\":\"switch_certificate\",\"precision\":\"%s\",",
         cfg->precision);
  printf("\"order\":%ld,\"x_hex\":\"%a\",\"active_branch\":\"series\",",
         order, cfg->switch_x);
  printf("\"series_actual_abs_upper_hex\":\"%a\",", series_actual);
  printf("\"series_theorem_abs_upper_hex\":\"%a\",",
         upper_abs(series_bound));
  printf("\"asymptotic_actual_abs_upper_hex\":\"%a\",",
         asymptotic_actual);
  printf("\"asymptotic_theorem_abs_upper_hex\":\"%a\",",
         upper_abs(asymptotic_bound));
  printf("\"branch_gap_abs_upper_hex\":\"%a\",", upper_abs(gap));
  printf("\"certifier\":\"FLINT/Arb 3.6.0\"}\n");
  arb_clear(x);
  arb_clear(nu);
  arb_clear(reference);
  arb_clear(series_value);
  arb_clear(asymptotic_value);
  arb_clear(difference);
  arb_clear(gap);
}

static void emit_bounds(const config_t *cfg, long order, const arb_t pi) {
  arb_t series_bound, ratio, p_abs, q_abs, p_remainder, q_remainder;
  arb_t phase_error, radius, sin_error, cos_error, prefactor, prefactor_error;
  arb_t n_expression, hankel_error, total_error, temporary, one;
  arb_init(series_bound);
  arb_init(ratio);
  arb_init(p_abs);
  arb_init(q_abs);
  arb_init(p_remainder);
  arb_init(q_remainder);
  arb_init(phase_error);
  arb_init(radius);
  arb_init(sin_error);
  arb_init(cos_error);
  arb_init(prefactor);
  arb_init(prefactor_error);
  arb_init(n_expression);
  arb_init(hankel_error);
  arb_init(total_error);
  arb_init(temporary);
  arb_init(one);
  arb_one(one);
  series_components(series_bound, ratio, cfg, order);
  hankel_components(p_abs, q_abs, p_remainder, q_remainder, cfg, order);
  phase_components(phase_error, radius, sin_error, cos_error, prefactor,
                   prefactor_error, n_expression, cfg, order, pi);
  arb_add(hankel_error, p_remainder, q_remainder, PREC);
  arb_mul(hankel_error, hankel_error, prefactor, PREC);
  arb_set(total_error, hankel_error);

  /* |K_used-K| ((1+E_cos)|P| + (1+E_sin)|Q|). */
  arb_add(temporary, one, cos_error, PREC);
  arb_mul(temporary, temporary, p_abs, PREC);
  arb_t second;
  arb_init(second);
  arb_add(second, one, sin_error, PREC);
  arb_mul(second, second, q_abs, PREC);
  arb_add(temporary, temporary, second, PREC);
  arb_mul(temporary, temporary, prefactor_error, PREC);
  arb_add(total_error, total_error, temporary, PREC);

  /* K (E_cos |P| + E_sin |Q|). */
  arb_mul(temporary, cos_error, p_abs, PREC);
  arb_mul(second, sin_error, q_abs, PREC);
  arb_add(temporary, temporary, second, PREC);
  arb_mul(temporary, temporary, prefactor, PREC);
  arb_add(total_error, total_error, temporary, PREC);

  const long first_even = first_after_with_parity(cfg->hankel_last, 0);
  const long first_odd = first_after_with_parity(cfg->hankel_last, 1);
  printf("{\"kind\":\"series_bound\",\"precision\":\"%s\",",
         cfg->precision);
  printf("\"order\":%ld,\"domain_abs_x_lo_hex\":\"0x0p+0\",", order);
  printf("\"domain_abs_x_hi_hex\":\"%a\",", cfg->switch_x);
  printf("\"last_retained_index\":%ld,\"first_omitted_index\":%ld,",
         cfg->series_last, cfg->series_last + 1);
  printf("\"tail_ratio_abs_upper_hex\":\"%a\",", upper_abs(ratio));
  printf("\"absolute_error_upper_hex\":\"%a\",",
         upper_abs(series_bound));
  printf("\"theorem\":\"alternating_first_omitted_term\"}\n");

  printf("{\"kind\":\"asymptotic_bound\",\"precision\":\"%s\",",
         cfg->precision);
  printf("\"order\":%ld,\"domain_abs_x_lo_hex\":\"%a\",", order,
         cfg->switch_x);
  printf("\"domain_abs_x_hi_hex\":\"%a\",", DOMAIN_MAX);
  printf("\"p_first_omitted_index\":%ld,\"q_first_omitted_index\":%ld,",
         first_even, first_odd);
  printf("\"p_ell\":%ld,\"q_ell\":%ld,",
         first_even / 2, (first_odd - 1) / 2);
  printf("\"dlmf_real_argument_conditions_certified\":true,");
  printf("\"p_remainder_abs_upper_hex\":\"%a\",",
         upper_abs(p_remainder));
  printf("\"q_remainder_abs_upper_hex\":\"%a\",",
         upper_abs(q_remainder));
  printf("\"hankel_truncation_abs_upper_hex\":\"%a\",",
         upper_abs(hankel_error));
  printf("\"phase_reconstruction_abs_upper_hex\":\"%a\",",
         upper_abs(phase_error));
  printf("\"reduced_argument_abs_upper_hex\":\"%a\",",
         upper_abs(radius));
  printf("\"sin_total_abs_upper_hex\":\"%a\",", upper_abs(sin_error));
  printf("\"cos_total_abs_upper_hex\":\"%a\",", upper_abs(cos_error));
  printf("\"prefactor_abs_error_upper_hex\":\"%a\",",
         upper_abs(prefactor_error));
  printf("\"p_sum_abs_upper_hex\":\"%a\",", upper_abs(p_abs));
  printf("\"q_sum_abs_upper_hex\":\"%a\",", upper_abs(q_abs));
  printf("\"n_magnitude_expression_upper_hex\":\"%a\",",
         upper_abs(n_expression));
  printf("\"n_abs_bound\":%ld,", N_ABS_BOUND);
  printf("\"absolute_error_upper_hex\":\"%a\",", upper_abs(total_error));
  printf("\"theorem\":\"DLMF_10.17.iii_plus_compositional_phase_bound\"}\n");
  emit_switch_certificate(cfg, order, series_bound, total_error);

  arb_clear(series_bound);
  arb_clear(ratio);
  arb_clear(p_abs);
  arb_clear(q_abs);
  arb_clear(p_remainder);
  arb_clear(q_remainder);
  arb_clear(phase_error);
  arb_clear(radius);
  arb_clear(sin_error);
  arb_clear(cos_error);
  arb_clear(prefactor);
  arb_clear(prefactor_error);
  arb_clear(n_expression);
  arb_clear(hankel_error);
  arb_clear(total_error);
  arb_clear(temporary);
  arb_clear(one);
  arb_clear(second);
}

static void emit_endpoint(const config_t *cfg, long order, const char *position,
                          double x_value, const arb_t split, const arb_t c,
                          double *partition_max) {
  arb_t x, offset, phase, rounded, n_value, remainder;
  arb_init(x);
  arb_init(offset);
  arb_init(phase);
  arb_init(rounded);
  arb_init(n_value);
  arb_init(remainder);
  arb_set_d(x, x_value);
  arb_set_d(offset, cfg->offsets[order]);
  arb_sub(phase, x, offset, PREC);
  arb_mul(rounded, phase, c, PREC);
  const long n = unambiguous_nearest_integer(rounded);
  arb_set_si(n_value, n);
  arb_mul(remainder, n_value, split, PREC);
  arb_sub(remainder, phase, remainder, PREC);
  const double remainder_abs = upper_abs(remainder);
  if (remainder_abs > *partition_max) {
    *partition_max = remainder_abs;
  }
  printf("{\"kind\":\"range_endpoint\",\"precision\":\"%s\",",
         cfg->precision);
  printf("\"order\":%ld,\"position\":\"%s\",\"x_hex\":\"%a\",",
         order, position, x_value);
  printf("\"selected_n\":%ld,", n);
  emit_interval_fields("reduced", remainder);
  printf(",\"reduced_abs_upper_hex\":\"%a\"}\n", remainder_abs);
  arb_clear(x);
  arb_clear(offset);
  arb_clear(phase);
  arb_clear(rounded);
  arb_clear(n_value);
  arb_clear(remainder);
}

static void emit_range_partition(const config_t *cfg, long order) {
  arb_t c, split, offset, switch_x, max_x, half, n_value, phase, boundary_x;
  arb_t left_reduced, right_reduced, temporary;
  arb_init(c);
  arb_init(split);
  arb_init(offset);
  arb_init(switch_x);
  arb_init(max_x);
  arb_init(half);
  arb_init(n_value);
  arb_init(phase);
  arb_init(boundary_x);
  arb_init(left_reduced);
  arb_init(right_reduced);
  arb_init(temporary);
  arb_set_d(c, cfg->two_over_pi);
  split_sum(split, cfg);
  arb_set_d(offset, cfg->offsets[order]);
  arb_set_d(switch_x, cfg->switch_x);
  arb_set_d(max_x, DOMAIN_MAX);
  set_half(half);
  long count = 0;
  long first_n = 0;
  long last_n = 0;
  double partition_max = 0.0;
  for (long n = -2048; n <= 2048; ++n) {
    arb_set_si(n_value, n);
    arb_add(phase, n_value, half, PREC);
    arb_div(phase, phase, c, PREC);
    arb_add(boundary_x, phase, offset, PREC);
    if (!arb_gt(boundary_x, switch_x) || !arb_lt(boundary_x, max_x)) {
      continue;
    }
    arb_mul(temporary, n_value, split, PREC);
    arb_sub(left_reduced, phase, temporary, PREC);
    arb_add_ui(n_value, n_value, 1, PREC);
    arb_mul(temporary, n_value, split, PREC);
    arb_sub(right_reduced, phase, temporary, PREC);
    const double left_abs = upper_abs(left_reduced);
    const double right_abs = upper_abs(right_reduced);
    if (left_abs > partition_max) {
      partition_max = left_abs;
    }
    if (right_abs > partition_max) {
      partition_max = right_abs;
    }
    if (count == 0) {
      first_n = n;
    }
    last_n = n;
    ++count;
    printf("{\"kind\":\"range_boundary\",\"precision\":\"%s\",",
           cfg->precision);
    printf("\"order\":%ld,\"left_n\":%ld,\"right_n\":%ld,", order,
           n, n + 1);
    emit_interval_fields("x", boundary_x);
    printf(",");
    emit_interval_fields("left_reduced", left_reduced);
    printf(",");
    emit_interval_fields("right_reduced", right_reduced);
    printf(",\"both_branches_certified\":true}\n");
  }
  emit_endpoint(cfg, order, "switch", cfg->switch_x, split, c,
                &partition_max);
  emit_endpoint(cfg, order, "domain_max", DOMAIN_MAX, split, c,
                &partition_max);

  arb_t reciprocal, reciprocal_error, radius, n_bound;
  arb_init(reciprocal);
  arb_init(reciprocal_error);
  arb_init(radius);
  arb_init(n_bound);
  arb_inv(reciprocal, c, PREC);
  arb_sub(reciprocal_error, reciprocal, split, PREC);
  arb_abs(reciprocal_error, reciprocal_error);
  arb_mul(radius, half, reciprocal, PREC);
  arb_set_si(n_bound, N_ABS_BOUND);
  arb_mul(temporary, n_bound, reciprocal_error, PREC);
  arb_add(radius, radius, temporary, PREC);
  printf("{\"kind\":\"range_partition\",\"precision\":\"%s\",",
         cfg->precision);
  printf("\"order\":%ld,\"domain_abs_x_lo_hex\":\"%a\",", order,
         cfg->switch_x);
  printf("\"domain_abs_x_hi_hex\":\"%a\",", DOMAIN_MAX);
  printf("\"boundary_count\":%ld,\"first_boundary_left_n\":%ld,",
         count, first_n);
  printf("\"last_boundary_left_n\":%ld,", last_n);
  printf("\"partition_endpoint_abs_upper_hex\":\"%a\",", partition_max);
  printf("\"analytic_reduced_abs_upper_hex\":\"%a\",",
         upper_abs(radius));
  printf("\"coverage\":\"all_rounding_cells_and_both_tie_branches\"}\n");
  arb_clear(reciprocal);
  arb_clear(reciprocal_error);
  arb_clear(radius);
  arb_clear(n_bound);
  arb_clear(c);
  arb_clear(split);
  arb_clear(offset);
  arb_clear(switch_x);
  arb_clear(max_x);
  arb_clear(half);
  arb_clear(n_value);
  arb_clear(phase);
  arb_clear(boundary_x);
  arb_clear(left_reduced);
  arb_clear(right_reduced);
  arb_clear(temporary);
}

int main(void) {
  arb_t pi;
  arb_init(pi);
  arb_const_pi(pi, PREC);
  for (unsigned long index = 0;
       index < sizeof(CONFIGS) / sizeof(CONFIGS[0]); ++index) {
    const config_t *cfg = &CONFIGS[index];
    for (long order = 0; order <= 1; ++order) {
      emit_bounds(cfg, order, pi);
      emit_range_partition(cfg, order);
    }
  }
  arb_clear(pi);
  flint_cleanup();
  return 0;
}
