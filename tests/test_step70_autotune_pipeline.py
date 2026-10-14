# -*- coding: utf-8 -*-
"""Step70: Verify the autotune pipeline produces a recommended JSON artifact.

Run:
  python -m tests.test_step70_autotune_pipeline
"""

from __future__ import annotations

import json
from pathlib import Path

from tools.step70_autotune import run_autotune


def test_step70_autotune_pipeline():
    # NOTE: This test is intentionally "no-amaranth" (pure python).
    # In some constrained environments, amaranth may not be installed.
    # Step70 supports --skip-matrix to operate on a pre-generated summary.
    out_matrix = Path("reports") / "_tmp_step70_matrix.csv"
    out_summary = Path("reports") / "_tmp_step70_summary.csv"
    out_md68 = Path("reports") / "_tmp_step70_summary.md"
    out_pareto_csv = Path("reports") / "_tmp_step70_pareto.csv"
    out_pareto_md = Path("reports") / "_tmp_step70_pareto.md"
    out_json = Path("reports") / "_tmp_step70_recommended.json"

    out_summary.parent.mkdir(parents=True, exist_ok=True)
    out_summary.write_text(
        "card_link_depth,reloc_link_depth,seeds,ok,ok_rate_pct,avg_max_card_link_level,avg_max_reloc_link_level\n"
        "1,1,4,4,100,1,1\n"
        "2,1,4,4,100,2,1\n",
        encoding="utf-8",
    )

    payload = run_autotune(
        card_depths=[1, 2],
        reloc_depths=[1],
        seeds=[0x1, 0x2, 0x3, 0x4],
        cycles=5,
        drain_cycles=20,
        queries=1,
        ok_threshold=100,
        out_matrix=out_matrix,
        out_summary=out_summary,
        out_md68=out_md68,
        out_pareto_csv=out_pareto_csv,
        out_pareto_md=out_pareto_md,
        out_json=out_json,
        run_matrix_step=False,
    )

    assert out_summary.exists(), "step70: summary CSV missing"
    assert out_pareto_csv.exists(), "step70: pareto CSV missing"
    assert out_json.exists(), "step70: recommended JSON missing"

    assert int(payload.get("ok", 0)) == 1, f"step70: expected feasible recommendation, got {payload}"
    assert int(payload.get("card_link_depth")) == 1
    assert int(payload.get("reloc_link_depth")) == 1

    disk = json.loads(out_json.read_text(encoding="utf-8"))
    assert disk == payload, "step70: JSON payload mismatch between return value and disk"


if __name__ == "__main__":
    test_step70_autotune_pipeline()
    print("OK: step70 autotune pipeline produces expected artifacts.")
