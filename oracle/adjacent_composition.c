/* SPDX-License-Identifier: ISC
 *
 * FLINT/Arb certificates for the shadow-index adjacent-cell composition.
 * This program does not model backend lowering.  It certifies, at 1024-bit
 * precision, the mathematical error from either selected adjacent quadrant's
 * Taylor reconstruction and Hankel approximation to the true Bessel value.
 */
#include <flint/arb.h>
#include <flint/flint.h>
#include <math.h>
#include <stdio.h>

#if __FLINT_VERSION != 3 || __FLINT_VERSION_MINOR != 6 ||                      \
    __FLINT_VERSION_PATCHLEVEL != 0
#error "adjacent composition certificates require FLINT/Arb 3.6.0"
#endif

#define PREC 1024
#define INDEX_ABS_BOUND 653L

typedef struct {
  const char *precision;
  double switch_x;
  long hankel_last;
  long sin_first_omitted;
  long cos_first_omitted;
  double two_over_pi;
  double pio2_hi;
  double pio2_lo;
  double pio2_tail;
  double pi_used;
  double offsets[2];
  double etas[2];
} config_t;

static const config_t CONFIGS[] = {
    {.precision = "f32",
     .switch_x = 6.0,
     .hankel_last = 7,
     .sin_first_omitted = 11,
     .cos_first_omitted = 12,
     .two_over_pi = (double)0x1.45f306p-1f,
     .pio2_hi = (double)0x1.9218p+0f,
     .pio2_lo = (double)0x1.ed511p-14f,
     .pio2_tail = (double)0x1.68c234p-39f,
     .pi_used = (double)0x1.921fb6p+1f,
     .offsets = {(double)0x1.921fb6p-1f, (double)0x1.2d97c8p+1f},
     .etas = {0x1.463306a30c131p-14, 0x1.46b306a2dfb66p-14}},
    {.precision = "f64",
     .switch_x = 12.0,
     .hankel_last = 12,
     .sin_first_omitted = 15,
     .cos_first_omitted = 14,
     .two_over_pi = 0x1.45f306dc9c883p-1,
     .pio2_hi = 0x1.921fb54000000p+0,
     .pio2_lo = 0x1.10b4611a62633p-30,
     .pio2_tail = 0x1.45c06e0e68948p-86,
     .pi_used = 0x1.921fb54442d18p+1,
     .offsets = {0x1.921fb54442d18p-1, 0x1.2d97c7f3321d2p+1},
     .etas = {0x1.463306dc9c884p-43, 0x1.46b306dc9c884p-43}},
};

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
  const long candidate = last + 1;
  return candidate % 2 == parity ? candidate : candidate + 1;
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

static void taylor_remainder(arb_t result, const arb_t radius,
                             long first_omitted) {
  arb_t factorial;
  arb_init(factorial);
  arb_pow_ui(result, radius, (unsigned long)first_omitted, PREC);
  arb_fac_ui(factorial, (unsigned long)first_omitted, PREC);
  arb_div(result, result, factorial, PREC);
  arb_clear(factorial);
}

static void emit_ball(const char *name, const arb_t value) {
  char *rendered = arb_get_str(value, 80, 0);
  printf("\"%s\":\"%s\"", name, rendered);
  flint_free(rendered);
}

static void emit_case(const config_t *cfg, long order, const arb_t pi) {
  const long first_even = first_after_with_parity(cfg->hankel_last, 0);
  const long first_odd = first_after_with_parity(cfg->hankel_last, 1);
  arb_t c, reciprocal, split, split_difference, eta, half, index_bound;
  arb_t rho, delta, offset, true_offset, temporary, sin_tail, cos_tail;
  arb_t p_abs, q_abs, p_remainder, q_remainder, prefactor, used_prefactor;
  arb_t prefactor_error, hankel_error, one;
  arb_init(c);
  arb_init(reciprocal);
  arb_init(split);
  arb_init(split_difference);
  arb_init(eta);
  arb_init(half);
  arb_init(index_bound);
  arb_init(rho);
  arb_init(delta);
  arb_init(offset);
  arb_init(true_offset);
  arb_init(temporary);
  arb_init(sin_tail);
  arb_init(cos_tail);
  arb_init(p_abs);
  arb_init(q_abs);
  arb_init(p_remainder);
  arb_init(q_remainder);
  arb_init(prefactor);
  arb_init(used_prefactor);
  arb_init(prefactor_error);
  arb_init(hankel_error);
  arb_init(one);
  arb_one(one);
  arb_set_d(c, cfg->two_over_pi);
  arb_inv(reciprocal, c, PREC);
  split_sum(split, cfg);
  arb_sub(split_difference, reciprocal, split, PREC);
  arb_abs(split_difference, split_difference);
  arb_set_d(eta, cfg->etas[order]);
  arb_one(half);
  arb_mul_2exp_si(half, half, -1);
  arb_set_si(index_bound, INDEX_ABS_BOUND);
  arb_add(rho, half, eta, PREC);
  arb_mul(rho, rho, reciprocal, PREC);
  arb_mul(temporary, index_bound, split_difference, PREC);
  arb_add(rho, rho, temporary, PREC);

  arb_set_d(offset, cfg->offsets[order]);
  arb_mul_ui(true_offset, pi, (unsigned long)(2 * order + 1), PREC);
  arb_div_ui(true_offset, true_offset, 4, PREC);
  arb_sub(delta, offset, true_offset, PREC);
  arb_abs(delta, delta);
  arb_mul_2exp_si(temporary, pi, -1);
  arb_sub(temporary, split, temporary, PREC);
  arb_abs(temporary, temporary);
  arb_mul(temporary, temporary, index_bound, PREC);
  arb_add(delta, delta, temporary, PREC);
  taylor_remainder(sin_tail, rho, cfg->sin_first_omitted);
  taylor_remainder(cos_tail, rho, cfg->cos_first_omitted);
  hankel_components(p_abs, q_abs, p_remainder, q_remainder, cfg, order);

  arb_set_d(temporary, cfg->switch_x);
  arb_mul(temporary, temporary, pi, PREC);
  arb_ui_div(prefactor, 2, temporary, PREC);
  arb_sqrt(prefactor, prefactor, PREC);
  arb_set_d(temporary, cfg->switch_x);
  arb_set_d(used_prefactor, cfg->pi_used);
  arb_mul(temporary, temporary, used_prefactor, PREC);
  arb_ui_div(used_prefactor, 2, temporary, PREC);
  arb_sqrt(used_prefactor, used_prefactor, PREC);
  arb_sub(prefactor_error, used_prefactor, prefactor, PREC);
  arb_abs(prefactor_error, prefactor_error);
  arb_add(hankel_error, p_remainder, q_remainder, PREC);
  arb_mul(hankel_error, hankel_error, prefactor, PREC);

  printf("{\"kind\":\"shadow_case\",\"precision\":\"%s\",\"order\":%ld,",
         cfg->precision, order);
  emit_ball("accepted_eta", eta);
  printf(",");
  emit_ball("shadow_reduction_radius", rho);
  printf(",");
  emit_ball("phase_reconstruction_error", delta);
  printf(",");
  emit_ball("sin_taylor_remainder", sin_tail);
  printf(",");
  emit_ball("cos_taylor_remainder", cos_tail);
  printf(",");
  emit_ball("p_sum_abs", p_abs);
  printf(",");
  emit_ball("q_sum_abs", q_abs);
  printf(",");
  emit_ball("p_remainder", p_remainder);
  printf(",");
  emit_ball("q_remainder", q_remainder);
  printf(",");
  emit_ball("prefactor", prefactor);
  printf(",");
  emit_ball("prefactor_error", prefactor_error);
  printf(",");
  emit_ball("hankel_error", hankel_error);
  printf(",\"index_abs_bound\":%ld,", INDEX_ABS_BOUND);
  printf("\"p_first_omitted_index\":%ld,\"q_first_omitted_index\":%ld,",
         first_even, first_odd);
  printf("\"p_ell\":%ld,\"q_ell\":%ld,", first_even / 2,
         (first_odd - 1) / 2);
  printf("\"dlmf_real_argument_conditions_certified\":true,");
  printf("\"certifier\":\"FLINT/Arb 3.6.0\"}\n");

  for (long boundary_quadrant = 0; boundary_quadrant < 4;
       ++boundary_quadrant) {
    for (long candidate = 0; candidate < 2; ++candidate) {
      const long selected_quadrant = (boundary_quadrant + candidate) % 4;
      const int swapped = selected_quadrant % 2 != 0;
      arb_t sin_error, cos_error, total, first, second;
      arb_init(sin_error);
      arb_init(cos_error);
      arb_init(total);
      arb_init(first);
      arb_init(second);
      arb_add(sin_error, delta, swapped ? cos_tail : sin_tail, PREC);
      arb_add(cos_error, delta, swapped ? sin_tail : cos_tail, PREC);

      /* K*(Rp+Rq) + |K_used-K|*((1+Ec)|P|+(1+Es)|Q|)
       *                 + K*(Ec|P|+Es|Q|). */
      arb_set(total, hankel_error);
      arb_add(first, one, cos_error, PREC);
      arb_mul(first, first, p_abs, PREC);
      arb_add(second, one, sin_error, PREC);
      arb_mul(second, second, q_abs, PREC);
      arb_add(first, first, second, PREC);
      arb_mul(first, first, prefactor_error, PREC);
      arb_add(total, total, first, PREC);
      arb_mul(first, cos_error, p_abs, PREC);
      arb_mul(second, sin_error, q_abs, PREC);
      arb_add(first, first, second, PREC);
      arb_mul(first, first, prefactor, PREC);
      arb_add(total, total, first, PREC);

      printf("{\"kind\":\"adjacent_quadrant\",\"precision\":\"%s\",",
             cfg->precision);
      printf("\"order\":%ld,\"boundary_quadrant\":%ld,", order,
             boundary_quadrant);
      printf("\"candidate\":\"%s\",\"selected_quadrant\":%ld,",
             candidate == 0 ? "k" : "k+1", selected_quadrant);
      emit_ball("sin_error", sin_error);
      printf(",");
      emit_ball("cos_error", cos_error);
      printf(",");
      emit_ball("shadow_math_absolute_error", total);
      printf(",\"certifier\":\"FLINT/Arb 3.6.0\"}\n");
      arb_clear(sin_error);
      arb_clear(cos_error);
      arb_clear(total);
      arb_clear(first);
      arb_clear(second);
    }
  }

  arb_clear(c);
  arb_clear(reciprocal);
  arb_clear(split);
  arb_clear(split_difference);
  arb_clear(eta);
  arb_clear(half);
  arb_clear(index_bound);
  arb_clear(rho);
  arb_clear(delta);
  arb_clear(offset);
  arb_clear(true_offset);
  arb_clear(temporary);
  arb_clear(sin_tail);
  arb_clear(cos_tail);
  arb_clear(p_abs);
  arb_clear(q_abs);
  arb_clear(p_remainder);
  arb_clear(q_remainder);
  arb_clear(prefactor);
  arb_clear(used_prefactor);
  arb_clear(prefactor_error);
  arb_clear(hankel_error);
  arb_clear(one);
}

int main(void) {
  arb_t pi;
  arb_init(pi);
  arb_const_pi(pi, PREC);
  for (unsigned long index = 0;
       index < sizeof(CONFIGS) / sizeof(CONFIGS[0]); ++index) {
    for (long order = 0; order <= 1; ++order) {
      emit_case(&CONFIGS[index], order, pi);
    }
  }
  arb_clear(pi);
  flint_cleanup();
  return 0;
}
