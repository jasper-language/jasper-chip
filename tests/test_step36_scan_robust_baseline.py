# tests/test_step36_scan_robust_baseline.py
# -*- coding: utf-8 -*-
"""Step36：robust scan baseline 回归测试（shared_hot_shift + per_core_partition）

目的：
  1) 确认 reports/step36_scan_robust_baseline.json 存在。
  2) 用同样配置重新计算一次 robust Top-N，确保推荐结果不漂移。
  3) 做一个 sanity：robust_score == min(per-mode score)。
"""

from __future__ import annotations

import json
from pathlib import Path

import tools.step36_scan_recommend_robust as s36
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
    path = Path("reports/step36_scan_robust_baseline.json")
    assert path.exists(), "missing reports/step36_scan_robust_baseline.json (run tools/generate_step36_scan_robust_baseline.py)"

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

    rep = s36.recommend_robust(
        base_cfg=b,
        scan_grid=scan_grid,
        topn=10,
        modes=modes,
        global_share_p=float(wl["global_share_p"]),
        w_cycle=float(baseline["weights"]["w_cycle"]),
        w_stall=float(baseline["weights"]["w_stall"]),
        w_replace=float(baseline["weights"]["w_replace"]),
    )

    assert _round_obj(rep) == _round_obj(baseline), "step36 robust baseline drifted"

    # sanity
    for row in rep["top"]:
        ms = [row["scores"][m] for m in modes]
        assert abs(row["robust_score"] - min(ms)) < 1e-9

    best = rep["top"][0]
    print(
        f"OK: step36 robust baseline stable; best=cardset{best['cardset_size']} fifo{best['fifo_depth']} consume{best['consume_every']} batch{best['batch_size']} "
        f"robust={best['robust_score']:.2f} scores={best['scores']}"
    )


if __name__ == "__main__":
    main()
