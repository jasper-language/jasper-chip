# tools/generate_step44_profile_variance_baseline.py
# -*- coding: utf-8 -*-

"""Step44 baseline：profile variance across seeds.

Outputs:
  - reports/step44_profile_variance_baseline.json
  - reports/step44_profile_variance_baseline.md
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict

from .step42_profile_compare import _default_base_cfg, _default_workloads
from .step44_profile_variance import eval_profiles_over_seeds, _default_seeds, _md_report


def _stable_trim(rep: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "ref_profile": rep.get("ref_profile"),
        "seeds": rep.get("seeds"),
        "workloads": rep.get("workloads"),
        "weights": rep.get("weights"),
        "base_cfg_no_seed": rep.get("base_cfg_no_seed"),
        "profiles": [],
        "per_seed": [],
    }

    for p in rep["profiles"]:
        out["profiles"].append(
            {
                "profile": p["profile"],
                "worst_score_mean": round(float(p["worst_score_mean"]), 6),
                "worst_score_std": round(float(p["worst_score_std"]), 6),
                "worst_score_min": round(float(p["worst_score_min"]), 6),
                "worst_score_max": round(float(p["worst_score_max"]), 6),
                "avg_rank": round(float(p["avg_rank"]), 6),
                "wins_vs_ref": p.get("wins_vs_ref"),
                "win_rate_vs_ref": None
                if p.get("win_rate_vs_ref") is None
                else round(float(p["win_rate_vs_ref"]), 6),
                "n_seeds": int(p["n_seeds"]),
            }
        )

    for s in rep["per_seed"]:
        out["per_seed"].append(
            {
                "seed": int(s["seed"]),
                "profiles": [
                    {
                        "profile": pp["profile"],
                        "worst_score": round(float(pp["worst_score"]), 6),
                        "worst_mode": pp["worst_mode"],
                        "best_score": round(float(pp["best_score"]), 6),
                        "best_mode": pp["best_mode"],
                        "cost": round(float(pp["cost"]), 6),
                    }
                    for pp in s["profiles"]
                ],
            }
        )

    return out


def main() -> None:
    base_cfg = _default_base_cfg()
    base_cfg_no_seed = dict(base_cfg)
    base_cfg_no_seed.pop("seed", None)

    rep = eval_profiles_over_seeds(
        profile_names=["step30", "step40_joint", "step40_pareto3"],
        base_cfg_no_seed=base_cfg_no_seed,
        seeds=_default_seeds(),
        workloads=_default_workloads(),
        w_cycle=1.0,
        w_stall=10.0,
        w_replace=2.0,
    )

    trimmed = _stable_trim(rep)

    outdir = "reports"
    os.makedirs(outdir, exist_ok=True)
    jpath = os.path.join(outdir, "step44_profile_variance_baseline.json")
    mpath = os.path.join(outdir, "step44_profile_variance_baseline.md")
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(trimmed, f, indent=2, ensure_ascii=False, sort_keys=True)
    with open(mpath, "w", encoding="utf-8") as f:
        f.write(_md_report(rep))

    print(f"Wrote {jpath} and {mpath}")


if __name__ == "__main__":
    main()
