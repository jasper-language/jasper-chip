# tests/test_step39_sweep_worstcase_baseline.py
# -*- coding: utf-8 -*-

"""Step39 baseline 回归测试。

- 重新计算 sweep worst-case 推荐结果，并与 reports/step39_sweep_worstcase_baseline.json 对齐。
- 额外 sanity：每个候选的 worst_score 必须等于 per_mode_score 的 max。
"""

from __future__ import annotations

import json
import os

from tools import step39_sweep_recommend_worstcase as s39


def _round(x: float) -> float:
    return float(f"{x:.6f}")


def test_step39_sweep_worstcase_baseline() -> None:
    repo_root = os.path.dirname(os.path.dirname(__file__))
    baseline_path = os.path.join(repo_root, "reports", "step39_sweep_worstcase_baseline.json")
    assert os.path.exists(baseline_path), "baseline json missing; run tools/generate_step39_sweep_worstcase_baseline.py"

    with open(baseline_path, "r", encoding="utf-8") as f:
        base = json.load(f)

    bcfg = base["base_cfg"]
    grid = []
    for s in [4, 8, 16, 32]:
        for w in [1, 2, 4]:
            for i in [0, 1, 2]:
                grid.append(s39.SweepCfg(sets=s, ways=w, index_mode=i))

    rep = s39.recommend(
        base_cfg=bcfg,
        sweep_grid=grid,
        workload_modes=base["workload_modes"],
        global_share_p=float(base["global_share_p"]),
        w_cycle=float(base["weights"]["w_cycle"]),
        w_stall=float(base["weights"]["w_stall"]),
        w_replace=float(base["weights"]["w_replace"]),
        topn=10,
    )

    # compare Top-1 (most important for defaults / recommendation stability)
    top0_a = base["topk"][0]
    top0_b = rep["topk"][0]
    assert top0_a["sweep"] == top0_b["sweep"]
    assert _round(top0_a["worst_score"]) == _round(top0_b["worst_score"])
    for wm in base["workload_modes"]:
        assert _round(top0_a["per_mode_score"][wm]) == _round(top0_b["per_mode_score"][wm])

    # sanity for all topk: worst_score == max(per_mode_score)
    for r in rep["topk"]:
        p = r["per_mode_score"]
        worst = max(p.values())
        assert _round(r["worst_score"]) == _round(worst)
        assert r["worst_mode"] in p
        assert _round(p[r["worst_mode"]]) == _round(worst)
