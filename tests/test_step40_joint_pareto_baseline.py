# tests/test_step40_joint_pareto_baseline.py
# -*- coding: utf-8 -*-

"""Step40 baseline 回归测试。

- 重新计算 scan+sweep 联合 worst-case 结果，并与 baseline 对齐。
- 额外 sanity：knee 和 Pareto 前沿候选的 worst_score 必须等于 per_mode_score 的 max。
"""

from __future__ import annotations

import json
import os

from tools import step40_joint_opt_pareto as s40


def _round(x: float) -> float:
    return float(f"{x:.6f}")


def _default_base_cfg():
    return {
        "seed": 1,
        "ncores": 4,
        "epochs": 8,
        "events_per_core_per_epoch": 64,
        "card_space": 64,
        "zipf_s": 1.07,
        "phase_shift": 7,
    }


def _default_scan_grid():
    cardset = [8, 16]
    fifo = [1, 2]
    consume = [2, 4]
    batch = [2]
    return [s40.ScanCfg(cs, fd, ce, bs) for cs in cardset for fd in fifo for ce in consume for bs in batch]


def _default_sweep_grid():
    sets_list = [8, 16, 32]
    ways_list = [1, 4]
    idx_list = [0, 2]
    return [s40.SweepCfg(sets=s, ways=w, index_mode=i) for s in sets_list for w in ways_list for i in idx_list]


def _compact_row(r):
    return {
        "scan": r["scan"],
        "sweep": r["sweep"],
        "worst_mode": r["worst_mode"],
        "worst_score": _round(float(r["worst_score"])),
        "cost": _round(float(r["cost"])),
    }


def _sanity_worst_score(row):
    per = row["per_mode"]
    mx = max(float(v["score"]) for v in per.values())
    assert abs(float(row["worst_score"]) - mx) < 1e-9


def test_step40_joint_pareto_baseline() -> None:
    repo_root = os.path.dirname(os.path.dirname(__file__))
    baseline_path = os.path.join(repo_root, "reports", "step40_joint_pareto_baseline.json")
    assert os.path.exists(baseline_path), "baseline json missing; run tools/generate_step40_joint_pareto_baseline.py"

    with open(baseline_path, "r", encoding="utf-8") as f:
        base = json.load(f)

    rep = s40.recommend_joint_pareto(
        base_cfg=_default_base_cfg(),
        scan_grid=_default_scan_grid(),
        sweep_grid=_default_sweep_grid(),
        workload_modes=["shared_hot_shift", "per_core_partition"],
        global_share_p=float(base.get("global_share_p", 0.10)),
        w_cycle=float(base["weights"]["w_cycle"]),
        w_stall=float(base["weights"]["w_stall"]),
        w_replace=float(base["weights"]["w_replace"]),
        topn=10,
    )

    # summary
    assert rep["summary"]["n_total"] == base["summary"]["n_total"]
    assert rep["summary"]["n_front"] == base["summary"]["n_front"]

    # knee
    _sanity_worst_score(rep["knee"])
    _sanity_worst_score(base["knee"])
    assert _compact_row(rep["knee"]) == _compact_row(base["knee"])

    # pareto front: check first 8 entries
    ncheck = min(8, len(rep["pareto_front"]))
    for i in range(ncheck):
        _sanity_worst_score(rep["pareto_front"][i])
        _sanity_worst_score(base["pareto_front"][i])
        assert _compact_row(rep["pareto_front"][i]) == _compact_row(base["pareto_front"][i])


def main() -> None:
    test_step40_joint_pareto_baseline()
    print("OK: step40 joint pareto baseline stable")

if __name__ == "__main__":
    main()