/* SPDX-License-Identifier: ISC
 *
 * Independent interval evidence through FLINT/Arb.  This program calls Arb's
 * certified hypergeometric Bessel implementation; it shares no approximation
 * coefficients or range-reduction code with the Futhark prototype.
 */
#include <flint/arb.h>
#include <flint/arb_hypgeom.h>
#include <flint/flint.h>
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

int main(void) {
  const char *points[] = {
      "-20", "-12", "-8", "-1", "-0", "0", "1", "8", "12", "20",
  };
  const long npoints = (long)(sizeof(points) / sizeof(points[0]));
  for (long i = 0; i < npoints; ++i) {
    emit_value("j0", i, points[i], 0);
    emit_value("j1", i, points[i], 1);
  }
  flint_cleanup();
  return 0;
}
