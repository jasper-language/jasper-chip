# tests/test_step37_scan_worstcase_baseline.py
# -*- coding: utf-8 -*-
"""Step37：worst-case(max) robust scan baseline 回归测试。

目的：
  1) 确认 reports/step37_scan_worstcase_baseline.json 存在。
  2) 用同样配置重新计算一次 Top-N，确保推荐结果不漂移。
  3) sanity：worst_score == max(per-mode score) 且 worst_mode 指向最大项。
"""

from __future__ import annotations

import json
from pathlib import Path

import tools.step37_scan_recommend_worstcase as s37
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
    path = Path("reports/step37_scan_worstcase_baseline.json")
    assert path.exists(), "missing reports/step37_scan_worstcase_baseline.json (run tools/generate_step37_scan_worstcase_baseline.py)"

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

    rep = s37.recommend_worstcase(
        base_cfg=b,
        scan_grid=scan_grid,
        topn=10,
        modes=modes,
        global_share_p=float(wl["global_share_p"]),
        w_cycle=float(baseline["weights"]["w_cycle"]),
        w_stall=float(baseline["weights"]["w_stall"]),
        w_replace=float(baseline["weights"]["w_replace"]),
    )

    assert _round_obj(rep) == _round_obj(baseline), "step37 worst-case robust baseline drifted"

    # sanity
    for row in rep["top"]:
        scores = row["scores"]
        worst = max(scores.values())
        assert abs(row["worst_score"] - worst) < 1e-9
        assert row["worst_mode"] in scores
        assert abs(scores[row["worst_mode"]] - worst) < 1e-9

    best = rep["top"][0]
    print(
        f"OK: step37 worst-case baseline stable; best=cardset{best['cardset_size']} fifo{best['fifo_depth']} consume{best['consume_every']} batch{best['batch_size']} "
        f"worst={best['worst_score']:.2f} worst_mode={best['worst_mode']} scores={best['scores']}"
    )


if __name__ == "__main__":
    main()
