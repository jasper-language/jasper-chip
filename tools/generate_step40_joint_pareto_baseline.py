# tools/generate_step40_joint_pareto_baseline.py
# -*- coding: utf-8 -*-

"""Step40：scan+sweep 联合扫参（worst-case）+ Pareto + knee baseline。

输出：
  - reports/step40_joint_pareto_baseline.json
  - reports/step40_joint_pareto_baseline.md
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Dict, List

import tools.step40_joint_opt_pareto as s40


def _default_base_cfg() -> Dict:
    # 与 Step39 baseline 保持一致，便于跨步骤对比
    return {
        "seed": 1,
        "ncores": 4,
        "epochs": 8,
        "events_per_core_per_epoch": 64,
        "card_space": 64,
        "zipf_s": 1.07,
        "phase_shift": 7,
    }


def _default_scan_grid() -> List[s40.ScanCfg]:
    # 复用 Step34 的小网格（16 组合），覆盖当前 scan 默认组合
    cardset = [8, 16]
    fifo = [1, 2]
    consume = [2, 4]
    batch = [2]
    return [s40.ScanCfg(cs, fd, ce, bs) for cs in cardset for fd in fifo for ce in consume for bs in batch]


def _default_sweep_grid() -> List[s40.SweepCfg]:
    sets_list = [8, 16, 32]
    ways_list = [1, 4]
    idx_list = [0, 2]
    return [s40.SweepCfg(sets=s, ways=w, index_mode=i) for s in sets_list for w in ways_list for i in idx_list]


def _md(rep: Dict) -> str:
    lines = []
    lines.append("# Step40 Joint Pareto Baseline\n")
    lines.append("## Summary\n")
    sm = rep["summary"]
    lines.append(f"- n_total: {sm['n_total']}")
    lines.append(f"- n_front: {sm['n_front']}")
    lines.append(f"- best_worst_score: {sm['best_worst_score']}")
    lines.append(f"- min_cost_on_front: {sm['min_cost_on_front']}")
    lines.append("")
    lines.append("## Knee 선택\n")
    lines.append(f"- method: {rep.get('knee_method', 'n/a')}")
    knee = rep["knee"]
    lines.append(f"- worst_score: {knee['worst_score']}")
    lines.append(f"- cost: {knee['cost']}")
    lines.append(f"- worst_mode: {knee['worst_mode']}")
    lines.append(f"- scan: {knee['scan']}")
    lines.append(f"- sweep: {knee['sweep']}")
    lines.append("")
    lines.append("## Pareto Front (Top 12 by worst_score)\n")
    front = rep["pareto_front"][:12]
    for i, r in enumerate(front):
        lines.append(f"{i+1}. worst={r['worst_score']:.2f}, cost={r['cost']:.1f}, scan={r['scan']}, sweep={r['sweep']}, worst_mode={r['worst_mode']}")
    lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="reports")
    ap.add_argument("--topn", type=int, default=10)
    ap.add_argument("--global_share_p", type=float, default=0.10)
    ap.add_argument("--w_cycle", type=float, default=1.0)
    ap.add_argument("--w_stall", type=float, default=10.0)
    ap.add_argument("--w_replace", type=float, default=200.0)
    args = ap.parse_args()

    rep = s40.recommend_joint_pareto(
        base_cfg=_default_base_cfg(),
        scan_grid=_default_scan_grid(),
        sweep_grid=_default_sweep_grid(),
        workload_modes=["shared_hot_shift", "per_core_partition"],
        global_share_p=float(args.global_share_p),
        w_cycle=float(args.w_cycle),
        w_stall=float(args.w_stall),
        w_replace=float(args.w_replace),
        topn=int(args.topn),
    )

    os.makedirs(args.outdir, exist_ok=True)
    jpath = os.path.join(args.outdir, "step40_joint_pareto_baseline.json")
    mpath = os.path.join(args.outdir, "step40_joint_pareto_baseline.md")
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(rep, f, indent=2, ensure_ascii=False)
    with open(mpath, "w", encoding="utf-8") as f:
        f.write(_md(rep))

    print(f"[step40] wrote {jpath} and {mpath}")


if __name__ == "__main__":
    main()
