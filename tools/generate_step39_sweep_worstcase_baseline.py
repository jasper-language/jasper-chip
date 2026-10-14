# tools/generate_step39_sweep_worstcase_baseline.py
# -*- coding: utf-8 -*-

"""Step39：基于 Step31 端到端模型的 sweep 参数 worst-case 推荐 baseline。

动机：
  Step39 引入 “mutator→scan→sweep” 的端到端评估来选择 sweep(card) 参数，
  并使用 worst-case(max across workloads) 来避免对单一写入形态过拟合。
  本脚本生成 baseline 报告，防止后续改模型/权重/默认 scan 参数时推荐结果悄然漂移。

输出：
  - reports/step39_sweep_worstcase_baseline.json
  - reports/step39_sweep_worstcase_baseline.md
"""

from __future__ import annotations

import argparse
import json
import os

from tools import step39_sweep_recommend_worstcase as s39


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="reports")
    args = ap.parse_args()

    base_cfg = {
        "seed": 20260103,
        "ncores": 4,
        "epochs": 2,
        "events_per_core_per_epoch": 64,
        "card_space": 64,
        "zipf_s": 1.07,
        "phase_shift": 7,
    }

    sets_list = [4, 8, 16, 32]
    ways_list = [1, 2, 4]
    idx_list = [0, 1, 2]
    grid = [s39.SweepCfg(sets=s, ways=w, index_mode=i) for s in sets_list for w in ways_list for i in idx_list]

    rep = s39.recommend(
        base_cfg=base_cfg,
        sweep_grid=grid,
        workload_modes=["shared_hot_shift", "per_core_partition"],
        global_share_p=0.10,
        w_cycle=1.0,
        w_stall=8.0,
        w_replace=4.0,
        topn=10,
    )

    os.makedirs(args.outdir, exist_ok=True)
    jpath = os.path.join(args.outdir, "step39_sweep_worstcase_baseline.json")
    mpath = os.path.join(args.outdir, "step39_sweep_worstcase_baseline.md")
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
    with open(mpath, "w", encoding="utf-8") as f:
        f.write(s39._md_report(rep))

    print(f"OK: wrote {jpath} and {mpath}")


if __name__ == "__main__":
    main()
