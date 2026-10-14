# tools/generate_step32_mutator_baseline.py
# -*- coding: utf-8 -*-

"""Step32：Mutator→Scan→Sweep 研究模型 baseline 生成器

目的：
  - Step31 给了一个纯 Python 的趋势模型（mutator→scan→sweep），跑得快、可复现。
  - Step32 把它固化为回归 baseline：以后只要模型/默认参数变了，测试能第一时间报警。

本脚本做什么：
  1) 用固定种子与固定规模调用 tools.step31_mutator_report.run_step31()
  2) 写入 reports/step32_mutator_baseline.json / .md

说明：
  - baseline 规模刻意选得很小（跑得快），但足够覆盖：Zipf 热点、phase_shift、多核 interleave。
  - sweep 参数默认取 rtl/gc_params.py（Step30 固化的推荐配置）。
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict


def main():
    from tools.step31_mutator_report import run_step31, _md_report
    from rtl import gc_params

    # 固定 baseline 配置（小规模、可复现）
    cfg = dict(
        seed=20260102,
        ncores=4,
        epochs=2,
        events_per_core_per_epoch=64,
        card_space=64,
        zipf_s=1.15,
        phase_shift=16,
        scan_cardset_size=16,
        scan_fifo_depth=4,
        scan_consume_every=4,
        scan_batch_size=4,
        sweep_sets=gc_params.DEFAULT_SWEEP_CARD_TABLE_SIZE,
        sweep_ways=gc_params.DEFAULT_SWEEP_CARD_TABLE_WAYS,
        sweep_index_mode=gc_params.DEFAULT_SWEEP_CARD_INDEX_MODE,
    )

    d = run_step31(**cfg)
    # 为了回归对比方便，把 cfg 再显式塞回去
    d["baseline_cfg"] = cfg

    outdir = "reports"
    os.makedirs(outdir, exist_ok=True)
    jpath = os.path.join(outdir, "step32_mutator_baseline.json")
    mpath = os.path.join(outdir, "step32_mutator_baseline.md")

    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    with open(mpath, "w", encoding="utf-8") as f:
        f.write(_md_report(d))

    print(f"OK: wrote {jpath} and {mpath}")


if __name__ == "__main__":
    main()
