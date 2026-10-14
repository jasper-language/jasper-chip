# tools/generate_step35_mc_dist_baseline.py
# -*- coding: utf-8 -*-

"""Step35：多核 card 分布 workload baseline（回归保护 + 方向评估）

动机：
  - Step31/32/33/34 已经把 mutator→scan→sweep 的趋势模型与 scan 参数推荐做成“可复现 + 可回归”。
  - 但真实系统里，多核写入的 card 分布经常不是“全局共享热点”这一种形态：
      * 每核主要写自己的 region（local hot），但仍会触达一些全局共享结构（global hot）。
  - Step35 增加一个新的 workload 模式：per_core_partition，并把关键 card 分布指标固化为 baseline：
      * shared_ratio：跨核共享 card 的比例
      * avg_jaccard：两两 core 的 card 集合重叠程度
    这样后续修改 mutator 生成策略/scan 接线时，能第一时间发现“多核分布形态”被意外破坏。

本脚本做什么：
  1) 用固定种子/固定规模分别跑两种 workload：
       - shared_hot_shift（Step31 原模型，用于对照）
       - per_core_partition（新增：local hot + 少量 global hot）
  2) 抽取关键指标写入 reports/step35_mc_dist_baseline.json / .md

说明：
  - baseline 规模刻意很小（跑得快），但足够体现“共享 vs 分区”的分布差异。
  - 不改 Step31/32/33/34 默认行为；新增 workload 只在显式指定时启用。
"""

from __future__ import annotations

import json
import os
from typing import Dict, Any

from tools.step31_mutator_report import run_step31


def _pick(d: Dict[str, Any]) -> Dict[str, Any]:
    """提取用于回归/对比的关键字段（避免无关字段干扰）。"""
    sst = d["scan"]["stats"]
    wst = d["sweep"]["stats"]
    cdt = d.get("card_dist", {})
    return {
        "cycle": int(d["cycle"]),
        "scan": {
            "in": int(sst["in_count"]),
            "uniq": int(sst["uniq_enq"]),
            "dup": int(sst["dup_drop"]),
            "stall": int(sst["stall_in"]),
            "out": int(sst["out_emit"]),
            "per_core_out": [int(x["out_emit"]) for x in sst["per_core"]],
        },
        "sweep": {
            "mark": int(wst["mark_total"]),
            "dup_drop": int(wst["dup_drop"]),
            "hit": int(wst["hit"]),
            "miss": int(wst["miss"]),
            "replace": int(wst["replace"]),
            "per_core_mark": [int(x) for x in wst["per_core_mark"]],
        },
        "card_dist": {
            "per_core_unique": [int(x) for x in cdt.get("per_core_unique", [])],
            "union_unique": int(cdt.get("union_unique", 0)),
            "shared_unique": int(cdt.get("shared_unique", 0)),
            "shared_ratio": float(cdt.get("shared_ratio", 0.0)),
            "avg_jaccard": float(cdt.get("avg_jaccard", 0.0)),
        },
        "workload": d.get("workload", {}),
    }


def main() -> None:
    from rtl import gc_params

    base_cfg = dict(
        seed=20260102,
        ncores=4,
        epochs=2,
        events_per_core_per_epoch=96,
        card_space=64,
        zipf_s=1.10,
        phase_shift=9,
        scan_cardset_size=16,
        scan_fifo_depth=2,
        scan_consume_every=4,
        scan_batch_size=2,
        sweep_sets=int(gc_params.DEFAULT_SWEEP_CARD_TABLE_SIZE),
        sweep_ways=int(gc_params.DEFAULT_SWEEP_CARD_TABLE_WAYS),
        sweep_index_mode=int(gc_params.DEFAULT_SWEEP_CARD_INDEX_MODE),
    )

    d_shared = run_step31(**base_cfg, workload_mode="shared_hot_shift", global_share_p=0.10)
    d_part = run_step31(**base_cfg, workload_mode="per_core_partition", global_share_p=0.10)

    out = {
        "meta": {"step": 35, "seed": base_cfg["seed"], "ver": 1},
        "baseline_cfg": base_cfg,
        "shared_hot_shift": _pick(d_shared),
        "per_core_partition": _pick(d_part),
    }

    os.makedirs("reports", exist_ok=True)
    jpath = os.path.join("reports", "step35_mc_dist_baseline.json")
    mpath = os.path.join("reports", "step35_mc_dist_baseline.md")
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    # 简单 md 摘要
    def _fmt(name: str, d: Dict[str, Any]) -> str:
        cd = d["card_dist"]
        return (
            f"### {name}\n"
            f"- cycle={d['cycle']}\n"
            f"- scan_out={d['scan']['out']} (stall={d['scan']['stall']})\n"
            f"- sweep_mark={d['sweep']['mark']} replace={d['sweep']['replace']}\n"
            f"- card_dist: union={cd['union_unique']} shared={cd['shared_unique']} "
            f"shared_ratio={cd['shared_ratio']:.3f} avg_jaccard={cd['avg_jaccard']:.3f}\n"
            f"- per_core_unique={cd['per_core_unique']}\n"
        )

    md = (
        "# Step35 多核 card 分布 workload baseline\n\n"
        + _fmt("shared_hot_shift (对照)", out["shared_hot_shift"])
        + "\n"
        + _fmt("per_core_partition (新增 workload)", out["per_core_partition"])
        + "\n"
        "> 期望趋势：per_core_partition 的 shared_ratio / avg_jaccard 应明显低于 shared_hot_shift。\n"
    )
    with open(mpath, "w", encoding="utf-8") as f:
        f.write(md)

    print(f"Wrote {jpath} and {mpath}")


if __name__ == "__main__":
    main()
