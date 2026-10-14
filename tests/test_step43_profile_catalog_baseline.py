# tests/test_step43_profile_catalog_baseline.py
# -*- coding: utf-8 -*-

"""Step43：profile catalog baseline 回归测试"""

from __future__ import annotations

import json
import os
from typing import Any, Dict

from tools.step42_profile_compare import compare_profiles, _default_base_cfg, _default_workloads
from tools.step43_profile_catalog import _default_profiles
from tools.generate_step43_profile_catalog_baseline import _stable_trim


def _load_baseline() -> Dict[str, Any]:
    path = os.path.join("reports", "step43_profile_catalog_baseline.json")
    assert os.path.exists(path), f"missing baseline: {path} (run tools/generate_step43_profile_catalog_baseline.py first)"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_step43_profile_catalog_baseline():
    rep = compare_profiles(
        profile_names=_default_profiles(),
        base_cfg=_default_base_cfg(),
        workloads=_default_workloads(),
        w_cycle=1.0,
        w_stall=10.0,
        w_replace=2.0,
    )
    trimmed = _stable_trim(rep)
    baseline = _load_baseline()
    assert trimmed == baseline
