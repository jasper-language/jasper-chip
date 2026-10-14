# tests/test_step34_scan_baseline.py
# -*- coding: utf-8 -*-
"""Step34：scan baseline 回归测试（固定种子/固定规模/固定网格）

目的：
  1) 确认 reports/step34_scan_baseline.json 存在。
  2) 用同样的配置重新计算一次 Top-N，确保推荐结果不漂移（否则说明趋势模型/权重/默认值变了）。
  3) 确认 rtl/gc_scan_params.py 与 TopSoC 默认参数跟 baseline 的 Top-1 一致。
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

from amaranth.hdl import UnusedElaboratable  # type: ignore

from rtl import gc_scan_params
from rtl.top_soc import TopSoC
from tools.generate_step34_scan_baseline import _default_base_cfg, _default_grid
from tools.step33_scan_recommend import recommend


def _strip_report(rep: dict) -> dict:
    """只保留回归关注的字段，避免未来报告扩展导致无谓的 baseline 破坏。"""
    out = {
        "base_cfg": rep.get("base_cfg", {}),
        "sweep_defaults": rep.get("sweep_defaults", {}),
        "weights": rep.get("weights", {}),
        "top": [],
    }
    for row in rep.get("top", []):
        out["top"].append(
            {
                "score": row["score"],
                "cardset_size": row["cardset_size"],
                "fifo_depth": row["fifo_depth"],
                "consume_every": row["consume_every"],
                "batch_size": row["batch_size"],
                "cycle": row["cycle"],
                # 关键统计：scan stall_in 与 sweep replace 是 score 里最敏感的两项
                "scan": {"stall_in": row["scan"]["stall_in"], "dup_drop": row["scan"]["dup_drop"], "uniq_enq": row["scan"]["uniq_enq"]},
                "sweep": {"replace": row["sweep"]["replace"], "dup_drop": row["sweep"]["dup_drop"], "mark_total": row["sweep"]["mark_total"]},
            }
        )
    return out


def main():
    jpath = Path("reports") / "step34_scan_baseline.json"
    assert jpath.exists(), f"missing baseline file: {jpath}"

    baseline = json.loads(jpath.read_text(encoding="utf-8"))

    # recompute
    rep = recommend(
        base_cfg=_default_base_cfg(),
        scan_grid=_default_grid(),
        topn=len(baseline.get("top", [])) or 5,
        w_cycle=float(baseline.get("weights", {}).get("w_cycle", 1.0)),
        w_stall=float(baseline.get("weights", {}).get("w_stall", 10.0)),
        w_replace=float(baseline.get("weights", {}).get("w_replace", 2.0)),
    )

    b0 = _strip_report(baseline)
    r0 = _strip_report(rep)
    assert b0 == r0, "Step34 scan baseline drifted; update reports/step34_scan_baseline.* intentionally if expected."

    best = baseline["top"][0]
    assert gc_scan_params.SCAN_CARDSET_SIZE == int(best["cardset_size"])
    assert gc_scan_params.SCAN_FIFO_DEPTH == int(best["fifo_depth"])
    assert gc_scan_params.SCAN_CONSUME_EVERY == int(best["consume_every"])
    assert gc_scan_params.SCAN_BATCH_SIZE == int(best["batch_size"])

    warnings.filterwarnings("ignore", category=UnusedElaboratable)
    soc = TopSoC()
    assert soc.scan_cardset_size == int(best["cardset_size"])
    assert soc.scan_fifo_depth == int(best["fifo_depth"])
    assert soc.scan_consume_every == int(best["consume_every"])
    assert soc.scan_batch_size == int(best["batch_size"])

    print(
        f"OK: step34 scan baseline stable; best=cardset{best['cardset_size']} fifo{best['fifo_depth']} consume{best['consume_every']} batch{best['batch_size']} score={best['score']:.2f}"
    )


if __name__ == "__main__":
    main()
