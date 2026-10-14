# -*- coding: utf-8 -*-
"""Step67: Verify the fuzz report tool produces a CSV with expected columns.

Run:
  python -m tests.test_step67_fuzz_report_tool
"""

from __future__ import annotations

import csv
from pathlib import Path

from tools.step67_fuzz_report import run_report


def test_step67_fuzz_report_tool():
    out = Path("reports") / "_tmp_step67_fuzz_report.csv"
    rows = run_report(
        seeds=[0x1],
        cycles=5,
        drain_cycles=20,
        card_depth=2,
        reloc_depth=2,
        queries=2,
        out_csv=out,
        continue_on_fail=False,
    )
    assert out.exists(), "report CSV not created"
    assert rows, "no report rows"
    assert all(int(r.get("ok", 0)) == 1 for r in rows), "expected all seeds to pass"

    with out.open("r", newline="") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []

    # Basic schema expectations.
    for h in [
        "seed",
        "ok",
        "cycles",
        "drain_cycles",
        "card_link_depth",
        "reloc_link_depth",
        "max_card_link_level",
        "max_reloc_link_level",
    ]:
        assert h in headers, f"missing column: {h}"


if __name__ == "__main__":
    test_step67_fuzz_report_tool()
    print("OK: step67 fuzz report tool produces a sane CSV.")
