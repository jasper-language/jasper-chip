# tools/generate_step38_scan_sensitivity_baseline.py
# -*- coding: utf-8 -*-

"""Step38：scan 参数 worst-case 敏感性 baseline。

动机：
  Step37 已给出 worst-case(max) 稳健推荐，但在做协处理器微结构收敛时，
  仍需要知道“哪个维度更重要”。本脚本生成敏感性报告 baseline，
  防止将来模型/权重调整时解释性结论悄悄漂移。

输出：
  - reports/step38_scan_sensitivity_baseline.json
  - reports/step38_scan_sensitivity_baseline.md
"""

from __future__ import annotations

import argparse
import json
import os

import tools.step38_scan_sensitivity as s38
import tools.step33_scan_recommend as s33


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="reports")
    ap.add_argument("--seed", type=int, default=20260102)
    ap.add_argument("--global-share-p", type=float, default=0.10)
    args = ap.parse_args()

    base_cfg = {
        "seed": args.seed,
        "ncores": 4,
        "epochs": 2,
        "events_per_core_per_epoch": 64,
        "card_space": 64,
        "zipf_s": 1.07,
        "phase_shift": 7,
    }

    scan_grid = []
    for cs in [8, 16]:
        for fd in [1, 2, 4]:
            for ce in [2, 4, 8]:
                for bs in [1, 2, 4]:
                    scan_grid.append(s33.ScanCfg(cardset_size=cs, fifo_depth=fd, consume_every=ce, batch_size=bs))

    rep = s38.analyze(
        base_cfg=base_cfg,
        scan_grid=scan_grid,
        topn=10,
        modes=["shared_hot_shift", "per_core_partition"],
        global_share_p=float(args.global_share_p),
        w_cycle=1.0,
        w_stall=8.0,
        w_replace=4.0,
    )

    os.makedirs(args.outdir, exist_ok=True)
    jpath = os.path.join(args.outdir, "step38_scan_sensitivity_baseline.json")
    mpath = os.path.join(args.outdir, "step38_scan_sensitivity_baseline.md")
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
    with open(mpath, "w", encoding="utf-8") as f:
        f.write(s38._md(rep))

    print(f"OK: wrote {jpath} and {mpath}")


if __name__ == "__main__":
    main()
