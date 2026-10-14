# -*- coding: utf-8 -*-
"""Step68: Verify the fuzz matrix tool produces CSV + markdown artifacts.

Run:
  python -m tests.test_step68_fuzz_matrix_tool
"""

from __future__ import annotations

import csv
from pathlib import Path

from tools.step68_fuzz_matrix import run_matrix


def test_step68_fuzz_matrix_tool():
    out_matrix = Path("reports") / "_tmp_step68_matrix.csv"
    out_summary = Path("reports") / "_tmp_step68_summary.csv"
    out_md = Path("reports") / "_tmp_step68_summary.md"

    rows, summary = run_matrix(
        seeds=[0x1],
        card_depths=[1],
        reloc_depths=[1],
        cycles=5,
        drain_cycles=20,
        queries=1,
        out_matrix=out_matrix,
        out_summary=out_summary,
        out_md=out_md,
    )

    assert out_matrix.exists(), "matrix CSV not created"
    assert out_summary.exists(), "summary CSV not created"
    assert out_md.exists(), "summary markdown not created"

    assert rows and summary
    assert all(int(r.get("ok", 0)) == 1 for r in rows)

    with out_matrix.open("r", newline="") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []

    for h in [
        "seed",
        "card_link_depth",
        "reloc_link_depth",
        "ok",
        "max_card_link_level",
        "max_reloc_link_level",
    ]:
        assert h in headers, f"missing column: {h}"


if __name__ == "__main__":
    test_step68_fuzz_matrix_tool()
    print("OK: step68 fuzz matrix tool produces expected artifacts.")
