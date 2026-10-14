# -*- coding: utf-8 -*-
"""Step69: Verify pareto selection tool works on a synthetic summary CSV.

Run:
  python -m tests.test_step69_pareto_select_tool
"""

from __future__ import annotations

import csv
from pathlib import Path

from tools.step69_select_pareto import _read_summary, pareto_front, recommend, write_csv, write_md


def test_step69_pareto_select_tool():
    in_csv = Path("reports") / "_tmp_step69_in_summary.csv"
    out_csv = Path("reports") / "_tmp_step69_pareto.csv"
    out_md = Path("reports") / "_tmp_step69_pareto.md"

    in_csv.parent.mkdir(parents=True, exist_ok=True)

    # Synthetic Step68 summary rows.
    rows = [
        {
            "card_link_depth": 1,
            "reloc_link_depth": 1,
            "seeds": 10,
            "ok": 10,
            "ok_rate_pct": 100,
            "avg_max_card_link_level": 1,
            "avg_max_reloc_link_level": 1,
        },
        {
            "card_link_depth": 1,
            "reloc_link_depth": 2,
            "seeds": 10,
            "ok": 10,
            "ok_rate_pct": 100,
            "avg_max_card_link_level": 1,
            "avg_max_reloc_link_level": 0,
        },
        {
            "card_link_depth": 2,
            "reloc_link_depth": 1,
            "seeds": 10,
            "ok": 10,
            "ok_rate_pct": 100,
            "avg_max_card_link_level": 0,
            "avg_max_reloc_link_level": 1,
        },
        {
            "card_link_depth": 2,
            "reloc_link_depth": 2,
            "seeds": 10,
            "ok": 9,
            "ok_rate_pct": 90,
            "avg_max_card_link_level": 0,
            "avg_max_reloc_link_level": 0,
        },
    ]

    headers = list(rows[0].keys())
    with in_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        for r in rows:
            w.writerow({k: int(v) for k, v in r.items()})

    parsed = _read_summary(in_csv)
    feasible = [r for r in parsed if r.ok_rate_pct >= 100]
    front = pareto_front(feasible)
    rec = recommend(front)

    assert rec is not None
    assert rec.key == (1, 1), f"expected (1,1) recommended, got {rec.key}"

    write_csv(front, rec, out_csv)
    write_md(front, rec, 100, out_md)

    assert out_csv.exists(), "pareto CSV not created"
    assert out_md.exists(), "pareto markdown not created"

    md = out_md.read_text(encoding="utf-8")
    assert "Recommended" in md
    assert "card_link_depth = **1**" in md


if __name__ == "__main__":
    test_step69_pareto_select_tool()
    print("OK: step69 pareto selection tool produces expected artifacts.")
