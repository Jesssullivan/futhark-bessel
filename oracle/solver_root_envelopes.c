/* SPDX-License-Identifier: ISC
 *
 * Independent true-residual certificates at source-interpreted solver outputs.
 * This oracle consumes only the canonical returned-root bit manifest.  It does
 * not consume or recompute the public root cache, root-isolating brackets, or
 * any Futhark approximation coefficient.
 */
#include <flint/arb.h>
#include <flint/arb_hypgeom.h>
#include <flint/arf.h>
#include <flint/flint.h>
#include <errno.h>
#include <inttypes.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { PRECISION_BITS = 512, ROOT_COUNT = 256, LINE_CAPACITY = 768 };

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

static void bessel_j1(arb_t value, const arb_t x) {
  arb_t order;
  arb_init(order);
  arb_one(order);
  arb_hypgeom_bessel_j(value, order, x, PRECISION_BITS);
  arb_clear(order);
}

static void abort_row(const char *message, long row_number) {
  fprintf(stderr, "%s at manifest row %ld\n", message, row_number);
  flint_abort();
}

static uint64_t parse_bits(const char *text, int width, long row_number) {
  const size_t expected_length = (size_t)(2 + width / 4);
  if (strlen(text) != expected_length || text[0] != '0' || text[1] != 'x') {
    abort_row("malformed solver-root bits", row_number);
  }
  errno = 0;
  char *end = NULL;
  const uint64_t bits = strtoull(text + 2, &end, 16);
  if (errno != 0 || end == NULL || *end != '\0') {
    abort_row("malformed solver-root bits", row_number);
  }
  return bits;
}

static void emit_residual(const char *precision, long index,
                          const char *root_text, double root) {
  arb_t exact_root, residual;
  arf_t residual_upper;
  arb_init(exact_root);
  arb_init(residual);
  arf_init(residual_upper);

  arb_set_d(exact_root, root);
  bessel_j1(residual, exact_root);
  arb_abs(residual, residual);
  arb_get_ubound_arf(residual_upper, residual, PRECISION_BITS);
  const double upper = arf_get_d(residual_upper, ARF_RND_CEIL);
  if (!(upper >= 0.0) || !isfinite(upper)) {
    fprintf(stderr, "invalid %s solver residual bound at root %ld\n", precision,
            index);
    flint_abort();
  }

  printf("{\"kind\":\"%s_solver_j1_root_envelope\",\"index\":%ld,",
         precision, index);
  printf("\"solver_root_%s_bits\":\"%s\",", precision, root_text);
  printf("\"solver_root_%s_hex\":\"%a\",", precision, root);
  printf("\"true_residual_ball\":\"");
  arb_printn(residual, 80, 0);
  printf("\",\"true_residual_upper_hex\":\"%a\",", upper);
  printf("\"certified_true_residual\":true}\n");

  arf_clear(residual_upper);
  arb_clear(exact_root);
  arb_clear(residual);
}

static void consume_row(FILE *manifest, long expected_index,
                        const char *expected_precision, long row_number,
                        char implementation_sha[65],
                        char evidence_sha[65], char transcript_sha[2][65]) {
  char line[LINE_CAPACITY];
  if (fgets(line, sizeof(line), manifest) == NULL) {
    abort_row("missing solver-root manifest row", row_number);
  }
  const size_t length = strlen(line);
  if (length == 0 || line[length - 1] != '\n') {
    abort_row("noncanonical solver-root manifest line ending", row_number);
  }
  line[length - 1] = '\0';

  char row_implementation_sha[65] = {0};
  char kind[64] = {0};
  char root_text[19] = {0};
  char row_evidence_sha[65] = {0};
  char row_transcript_sha[65] = {0};
  long index = 0;
  int consumed = -1;
  const int parsed = sscanf(
      line,
      "{\"implementation_sha256\":\"%64[0-9a-f]\",\"index\":%ld,"
      "\"kind\":\"%63[^\"]\",\"root_bits\":\"%18[^\"]\","
      "\"root_solver_evidence_sha256\":\"%64[0-9a-f]\","
      "\"source_transcript_sha256\":\"%64[0-9a-f]\"}%n",
      row_implementation_sha, &index, kind, root_text, row_evidence_sha,
      row_transcript_sha, &consumed);
  if (parsed != 6 || consumed < 0 || line[consumed] != '\0' ||
      strlen(row_implementation_sha) != 64 || strlen(row_evidence_sha) != 64 ||
      strlen(row_transcript_sha) != 64) {
    abort_row("malformed or noncanonical solver-root manifest row", row_number);
  }

  char expected_kind[64];
  const int kind_length = snprintf(expected_kind, sizeof(expected_kind),
                                   "%s_solver_j1_root_output",
                                   expected_precision);
  if (kind_length < 0 || (size_t)kind_length >= sizeof(expected_kind) ||
      index != expected_index || strcmp(kind, expected_kind) != 0) {
    abort_row("unordered solver-root manifest row", row_number);
  }

  const int precision_slot = strcmp(expected_precision, "f32") == 0 ? 0 : 1;
  if (row_number == 1) {
    strcpy(implementation_sha, row_implementation_sha);
    strcpy(evidence_sha, row_evidence_sha);
  } else if (strcmp(implementation_sha, row_implementation_sha) != 0 ||
             strcmp(evidence_sha, row_evidence_sha) != 0) {
    abort_row("inconsistent solver-root manifest authority hash", row_number);
  }
  if (transcript_sha[precision_slot][0] == '\0') {
    strcpy(transcript_sha[precision_slot], row_transcript_sha);
  } else if (strcmp(transcript_sha[precision_slot], row_transcript_sha) != 0) {
    abort_row("inconsistent source transcript hash", row_number);
  }

  if (precision_slot == 0) {
    const uint64_t wide_bits = parse_bits(root_text, 32, row_number);
    if (wide_bits > UINT32_MAX) {
      abort_row("out-of-range f32 solver-root bits", row_number);
    }
    const uint32_t bits = (uint32_t)wide_bits;
    float root;
    memcpy(&root, &bits, sizeof(root));
    if (!(root > 0.0f) || !isfinite(root) || f32_bits(root) != bits) {
      abort_row("non-positive-finite f32 solver root", row_number);
    }
    emit_residual(expected_precision, index, root_text, (double)root);
  } else {
    const uint64_t bits = parse_bits(root_text, 64, row_number);
    double root;
    memcpy(&root, &bits, sizeof(root));
    if (!(root > 0.0) || !isfinite(root) || f64_bits(root) != bits) {
      abort_row("non-positive-finite f64 solver root", row_number);
    }
    emit_residual(expected_precision, index, root_text, root);
  }
}

int main(int argc, char **argv) {
  if (argc != 2) {
    fprintf(stderr, "usage: %s solver-root-outputs.jsonl\n", argv[0]);
    return 2;
  }
  FILE *manifest = fopen(argv[1], "r");
  if (manifest == NULL) {
    perror("cannot open solver-root output manifest");
    return 2;
  }

  char implementation_sha[65] = {0};
  char evidence_sha[65] = {0};
  char transcript_sha[2][65] = {{0}, {0}};
  long row_number = 0;
  for (long index = 1; index <= ROOT_COUNT; ++index) {
    consume_row(manifest, index, "f32", ++row_number, implementation_sha,
                evidence_sha, transcript_sha);
    consume_row(manifest, index, "f64", ++row_number, implementation_sha,
                evidence_sha, transcript_sha);
  }
  char extra[2];
  if (fgets(extra, sizeof(extra), manifest) != NULL) {
    abort_row("extra solver-root manifest row", row_number + 1);
  }
  if (ferror(manifest)) {
    perror("failed reading solver-root output manifest");
    fclose(manifest);
    return 2;
  }
  fclose(manifest);
  flint_cleanup();
  return 0;
}
