# tools/generate_step36_scan_robust_baseline.py
# -*- coding: utf-8 -*-

"""Step36：Robust scan 推荐 baseline（跨多核 workload 模式）

动机：
  - Step35 引入 per_core_partition，更贴近“每核分区写入 + 少量全局共享”。
  - Step36 用 worst-case(min) 方式把 scan 参数推荐扩展成“跨 workload 稳健选择”。
  - 本脚本生成 baseline，防止推荐在未来悄悄漂移。

输出：
  - reports/step36_scan_robust_baseline.json
  - reports/step36_scan_robust_baseline.md
"""

from __future__ import annotations

import argparse
import json
import os

import tools.step36_scan_recommend_robust as s36
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

    # 固定网格（覆盖默认组合）
    scan_grid = []
    for cs in [8, 16]:
        for fd in [1, 2, 4]:
            for ce in [2, 4, 8]:
                for bs in [1, 2, 4]:
                    scan_grid.append(s33.ScanCfg(cardset_size=cs, fifo_depth=fd, consume_every=ce, batch_size=bs))

    rep = s36.recommend_robust(
        base_cfg=base_cfg,
        scan_grid=scan_grid,
        topn=10,
        modes=["shared_hot_shift", "per_core_partition"],
        global_share_p=args.global_share_p,
        w_cycle=1.0,
        w_stall=8.0,
        w_replace=4.0,
    )

    os.makedirs(args.outdir, exist_ok=True)
    jpath = os.path.join(args.outdir, "step36_scan_robust_baseline.json")
    mpath = os.path.join(args.outdir, "step36_scan_robust_baseline.md")
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
    with open(mpath, "w", encoding="utf-8") as f:
        f.write(s36._md(rep))

    print(f"OK: wrote {jpath} and {mpath}")


if __name__ == "__main__":
    main()
