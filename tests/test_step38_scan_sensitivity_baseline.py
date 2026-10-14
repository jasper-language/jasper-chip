# tests/test_step38_scan_sensitivity_baseline.py
# -*- coding: utf-8 -*-
"""Step38：scan worst-case 敏感性 baseline 回归测试。

目的：
  1) 确认 reports/step38_scan_sensitivity_baseline.json 存在。
  2) 用同样的 scan_grid + workload 重新计算一次，确保解释性结论（mean/delta/importance）不漂移。
"""

from __future__ import annotations

import json
from pathlib import Path

import tools.step38_scan_sensitivity as s38
import tools.step33_scan_recommend as s33


def _round_obj(x, nd=9):
    if isinstance(x, float):
        return round(x, nd)
    if isinstance(x, dict):
        return {k: _round_obj(v, nd) for k, v in x.items()}
    if isinstance(x, list):
        return [_round_obj(v, nd) for v in x]
    return x


def main():
    path = Path("reports/step38_scan_sensitivity_baseline.json")
    assert path.exists(), "missing reports/step38_scan_sensitivity_baseline.json (run tools/generate_step38_scan_sensitivity_baseline.py)"

    baseline = json.loads(path.read_text(encoding="utf-8"))
    b = baseline["base_cfg"]
    wl = baseline["workloads"]
    modes = list(wl["modes"])

    scan_grid = []
    for cs in [8, 16]:
        for fd in [1, 2, 4]:
            for ce in [2, 4, 8]:
                for bs in [1, 2, 4]:
                    scan_grid.append(s33.ScanCfg(cardset_size=cs, fifo_depth=fd, consume_every=ce, batch_size=bs))

    rep = s38.analyze(
        base_cfg=b,
        scan_grid=scan_grid,
        topn=10,
        modes=modes,
        global_share_p=float(wl["global_share_p"]),
        w_cycle=float(baseline["weights"]["w_cycle"]),
        w_stall=float(baseline["weights"]["w_stall"]),
        w_replace=float(baseline["weights"]["w_replace"]),
    )

    assert _round_obj(rep) == _round_obj(baseline), "step38 sensitivity baseline drifted"

    # sanity: importance is sorted by delta desc
    imps = rep["importance"]
    deltas = [float(x["delta"]) for x in imps]
    assert deltas == sorted(deltas, reverse=True), "importance should be sorted by delta desc"

    top1 = rep["top"][0]
    print(
        "OK: step38 sensitivity baseline stable; "
        f"top1=cardset{top1['cardset_size']} fifo{top1['fifo_depth']} consume{top1['consume_every']} batch{top1['batch_size']} "
        f"worst={top1['worst_score']:.1f} worst_mode={top1['worst_mode']} "
        f"importance={[ (x['param'], round(x['delta'],1), x['best']) for x in imps[:3] ]}"
    )


if __name__ == "__main__":
    main()
