# tests/test_step32_mutator_baseline.py
# -*- coding: utf-8 -*-
"""Step32：Mutator→Scan→Sweep baseline 回归测试

目的：
  - 确认 reports/step32_mutator_baseline.json 存在。
  - 用 baseline_cfg 重新跑一次 Step31 趋势模型，要求关键统计完全一致。

说明：
  - 该模型是纯 Python，可复现性应当是“严格一致”。
  - 如果未来刻意修改模型语义（例如 scan/sweep 的消费策略或 dedup 规则），
    就需要同步更新 baseline（运行 tools/generate_step32_mutator_baseline.py）。
"""

from __future__ import annotations

import json
from pathlib import Path


def _pick_key_metrics(d: dict) -> dict:
    """抽取用于回归的关键指标（保持稳定、避免无关字段干扰）。"""
    sst = d["scan"]["stats"]
    wst = d["sweep"]["stats"]
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
    }


def main():
    p = Path("reports") / "step32_mutator_baseline.json"
    assert p.exists(), "step32 baseline json missing"

    baseline = json.loads(p.read_text(encoding="utf-8"))
    cfg = baseline.get("baseline_cfg")
    assert isinstance(cfg, dict), "baseline_cfg missing"

    from tools.step31_mutator_report import run_step31

    d2 = run_step31(**cfg)

    m0 = _pick_key_metrics(baseline)
    m1 = _pick_key_metrics(d2)
    assert m1 == m0, f"baseline drift detected:\nBASE={m0}\nNOW ={m1}"

    print("OK: step32 mutator baseline stable (no drift).")


if __name__ == "__main__":
    main()
