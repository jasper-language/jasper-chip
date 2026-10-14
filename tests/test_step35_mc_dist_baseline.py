# tests/test_step35_mc_dist_baseline.py
# -*- coding: utf-8 -*-
"""Step35：多核 card 分布 workload baseline 回归测试

目的：
  - 确认 reports/step35_mc_dist_baseline.json 存在。
  - 用 baseline_cfg 重新跑两种 workload，要求关键统计完全一致。

说明：
  - shared_hot_shift 是 Step31 原模型（对照）。
  - per_core_partition 是 Step35 新增 workload（local hot + 少量 global hot）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any


def _compact_from_run(d: Dict[str, Any]) -> Dict[str, Any]:
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


def test_step35_mc_dist_baseline_regression():
    p = Path("reports/step35_mc_dist_baseline.json")
    assert p.exists(), "step35 baseline json missing"

    baseline = json.loads(p.read_text(encoding="utf-8"))
    cfg = baseline.get("baseline_cfg")
    assert isinstance(cfg, dict), "baseline_cfg missing"

    from tools.step31_mutator_report import run_step31

    d_shared = run_step31(**cfg, workload_mode="shared_hot_shift", global_share_p=0.10)
    d_part = run_step31(**cfg, workload_mode="per_core_partition", global_share_p=0.10)

    now_shared = _compact_from_run(d_shared)
    now_part = _compact_from_run(d_part)

    assert now_shared == baseline["shared_hot_shift"], f"shared_hot_shift drift\nBASE={baseline['shared_hot_shift']}\nNOW ={now_shared}"
    assert now_part == baseline["per_core_partition"], f"per_core_partition drift\nBASE={baseline['per_core_partition']}\nNOW ={now_part}"

    # 趋势性 sanity：分区 workload 的共享比例应更低（固定 seed 下应稳定成立）
    assert now_part["card_dist"]["shared_ratio"] < now_shared["card_dist"]["shared_ratio"]
