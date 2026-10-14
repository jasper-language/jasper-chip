# tools/generate_step43_profile_catalog_baseline.py
# -*- coding: utf-8 -*-

"""Step43 baseline：profile catalog（加入 step40 pareto profiles）

输出：
  - reports/step43_profile_catalog_baseline.json
  - reports/step43_profile_catalog_baseline.md
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict

from .step43_profile_catalog import _default_profiles, _md_report
from .step42_profile_compare import compare_profiles, _default_base_cfg, _default_workloads


def _stable_trim(rep: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "ref_profile": rep.get("ref_profile"),
        "workloads": rep.get("workloads"),
        "profiles": [],
    }
    for p in rep["profiles"]:
        out["profiles"].append(
            {
                "profile": p["profile"],
                "scan": p["scan"],
                "sweep": p["sweep"],
                "worst_score": round(float(p["worst_score"]), 6),
                "worst_mode": p["worst_mode"],
                "cost": round(float(p["cost"]), 6),
                "per_mode": [
                    {
                        "workload_mode": m["workload_mode"],
                        "score": round(float(m["score"]), 6),
                        "cycle": int(m["cycle"]),
                        "stall_in": int(m["stall_in"]),
                        "sweep_replace": int(m["sweep_replace"]),
                    }
                    for m in p["per_mode"]
                ],
            }
        )
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="reports")
    args = ap.parse_args()

    rep = compare_profiles(
        profile_names=_default_profiles(),
        base_cfg=_default_base_cfg(),
        workloads=_default_workloads(),
        w_cycle=1.0,
        w_stall=10.0,
        w_replace=2.0,
    )
    trimmed = _stable_trim(rep)

    os.makedirs(args.outdir, exist_ok=True)
    jpath = os.path.join(args.outdir, "step43_profile_catalog_baseline.json")
    mpath = os.path.join(args.outdir, "step43_profile_catalog_baseline.md")
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(trimmed, f, indent=2, ensure_ascii=False, sort_keys=True)
    with open(mpath, "w", encoding="utf-8") as f:
        f.write(_md_report(rep))

    print(f"Wrote {jpath} and {mpath}")


if __name__ == "__main__":
    main()
