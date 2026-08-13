#!/usr/bin/env python3
# SPDX-License-Identifier: ISC
"""Mutation checks for certified-bit root-cache rendering."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Callable

import render_root_cache as renderer


def expect_blocked(function: Callable[[], str], fragment: str) -> None:
    try:
        function()
    except SystemExit as error:
        if fragment not in str(error):
            raise SystemExit(
                f"wrong fail-closed reason: expected {fragment!r}, got {error!r}"
            ) from error
        return
    raise SystemExit(f"mutation did not fail closed: expected {fragment!r}")


def render_rows(rows: list[dict[str, object]]) -> str:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "arb-certificates.jsonl"
        path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        original = renderer.EVIDENCE
        try:
            renderer.EVIDENCE = path
            return renderer.render()
        finally:
            renderer.EVIDENCE = original


def main() -> None:
    rows = [json.loads(line) for line in renderer.EVIDENCE.read_text().splitlines()]
    roots = [row for row in rows if row.get("kind") == "j1_root_bracket"]
    if len(roots) != 256:
        raise SystemExit("fixture must contain 256 root rows")

    missing = [row for row in rows if row is not roots[-1]]
    expect_blocked(lambda: render_rows(missing), "exactly indices 1..256")

    wrong_width = json.loads(json.dumps(rows))
    target = next(row for row in wrong_width if row.get("kind") == "j1_root_bracket")
    target["root_f64_reference_bits"] = "0x1"
    expect_blocked(lambda: render_rows(wrong_width), "malformed f64 root reference bits")

    missing_rounding = json.loads(json.dumps(rows))
    target = next(
        row for row in missing_rounding if row.get("kind") == "j1_root_bracket"
    )
    target["certified_unique_rounding"] = False
    expect_blocked(lambda: render_rows(missing_rounding), "missing root rounding proof")

    escaped = json.loads(json.dumps(rows))
    target = next(row for row in escaped if row.get("kind") == "j1_root_bracket")
    target["root_f64_reference_bits"] = "0x3ff0000000000000"
    expect_blocked(lambda: render_rows(escaped), "certified f64 root escaped bracket")

    rendered = render_rows(rows)
    if rendered != renderer.CACHE.read_text():
        raise SystemExit("unmutated renderer output disagrees with disposable cache")
    print("OK certified-bit root-cache renderer mutations fail closed")


if __name__ == "__main__":
    main()
