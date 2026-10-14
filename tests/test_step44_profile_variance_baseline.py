# tests/test_step44_profile_variance_baseline.py
# -*- coding: utf-8 -*-

"""Step44：profile variance baseline 回归测试（跨多个随机种子）"""

from __future__ import annotations

import json
import os
from typing import Dict, Any

from tools.step44_profile_variance import eval_profiles_over_seeds, _default_seeds
from tools.step42_profile_compare import _default_base_cfg, _default_workloads
from tools.generate_step44_profile_variance_baseline import _stable_trim


def _load_baseline() -> Dict[str, Any]:
    path = os.path.join("reports", "step44_profile_variance_baseline.json")
    assert os.path.exists(path), f"missing baseline: {path} (run tools/generate_step44_profile_variance_baseline.py first)"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_step44_profile_variance_baseline():
    base_cfg = _default_base_cfg()
    base_cfg_no_seed = dict(base_cfg)
    base_cfg_no_seed.pop("seed", None)

    rep = eval_profiles_over_seeds(
        profile_names=["step30", "step40_joint", "step40_pareto3"],
        base_cfg_no_seed=base_cfg_no_seed,
        seeds=_default_seeds(),
        workloads=_default_workloads(),
        w_cycle=1.0,
        w_stall=10.0,
        w_replace=2.0,
    )
    trimmed = _stable_trim(rep)
    baseline = _load_baseline()

    # helpful sanity: mean ordering should put step40_joint at rank1
    assert trimmed["profiles"][0]["profile"] == "step40_joint"

    assert trimmed == baseline
