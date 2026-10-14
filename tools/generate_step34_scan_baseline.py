# tools/generate_step34_scan_baseline.py
# -*- coding: utf-8 -*-

"""Step34：Scan 参数推荐 baseline（回归保护）

动机：
  - Step33 增加了 scan 参数推荐器，并把 Top-1 写入 rtl/gc_scan_params.py 作为 SoC 默认。
  - 但是如果后续修改趋势模型（mutator/scan/sweep）或默认权重，推荐结果可能悄悄漂移。
  - Step34 用“固定种子/固定规模/固定网格”的 baseline 把推荐结果钉死，后续改动必须显式更新 baseline。

本脚本做什么：
  1) 构造一份小网格 scan 参数空间（覆盖当前默认组合）。
  2) 调用 tools.step33_scan_recommend.recommend() 生成 Top-N。
  3) 写入 reports/step34_scan_baseline.json / .md

说明：
  - baseline 网格刻意选得很小（便于 CI/回归），不是为了找全局最优。
"""

from __future__ import annotations

import argparse
import json
import os
from typing import List

from tools.step33_scan_recommend import ScanCfg, recommend, _md


def _default_base_cfg() -> dict:
    # 与 step33_scan_recommend.py CLI 默认值保持一致（但更“回归友好”）
    return {
        "seed": 20260102,
        "ncores": 4,
        "epochs": 2,
        "events_per_core_per_epoch": 64,
        "card_space": 64,
        "zipf_s": 1.07,
        "phase_shift": 7,
    }


def _default_grid() -> List[ScanCfg]:
    # 小网格（2*2*2*2=16），覆盖当前默认组合：
    #   cardset=8 fifo=1 consume=2 batch=2
    cardset = [8, 16]
    fifo = [1, 2]
    consume = [2, 4]
    batch = [1, 2]
    return [ScanCfg(cs, fd, ce, bs) for cs in cardset for fd in fifo for ce in consume for bs in batch]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="reports")
    ap.add_argument("--topn", type=int, default=5)
    # weights: 与 Step33 的默认权重一致
    ap.add_argument("--w-cycle", type=float, default=1.0)
    ap.add_argument("--w-stall", type=float, default=10.0)
    ap.add_argument("--w-replace", type=float, default=2.0)
    args = ap.parse_args()

    base_cfg = _default_base_cfg()
    grid = _default_grid()

    rep = recommend(
        base_cfg=base_cfg,
        scan_grid=grid,
        topn=args.topn,
        w_cycle=args.w_cycle,
        w_stall=args.w_stall,
        w_replace=args.w_replace,
    )

    os.makedirs(args.outdir, exist_ok=True)
    jpath = os.path.join(args.outdir, "step34_scan_baseline.json")
    mpath = os.path.join(args.outdir, "step34_scan_baseline.md")
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
    with open(mpath, "w", encoding="utf-8") as f:
        f.write(_md(rep))

    print(f"OK: wrote {jpath} and {mpath}")


if __name__ == "__main__":
    main()
