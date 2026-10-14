# tests/test_step43_pareto_profiles_match_step40.py
# -*- coding: utf-8 -*-

"""Step43：确保 step40_pareto* profiles 与 Step40 pareto_front 一致。

目的是避免手工复制配置时引入错配：
- Step40 的 pareto_front 是扫参+pareto 算出来的“源数据”；
- Step43 将其中的点固化成 profile，供工程对比/档位讨论。
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from rtl.gc_profile_params import get_profile


def _load_step40_pareto() -> List[Dict[str, Any]]:
    path = os.path.join("reports", "step40_joint_pareto_baseline.json")
    assert os.path.exists(path), f"missing Step40 baseline: {path}"
    with open(path, "r", encoding="utf-8") as f:
        obj = json.load(f)
    return obj["pareto_front"]


def test_step43_pareto_profiles_match_step40():
    pareto = _load_step40_pareto()
    # pareto_front[0] 是 knee/最优点（已被 step40_joint 覆盖）
    mapping = {
        "step40_pareto1": pareto[1],
        "step40_pareto2": pareto[2],
        "step40_pareto3": pareto[3],
    }

    for name, src in mapping.items():
        prof = get_profile(name)
        assert prof["scan"] == {
            "cardset_size": int(src["scan"]["cardset_size"]),
            "fifo_depth": int(src["scan"]["fifo_depth"]),
            "consume_every": int(src["scan"]["consume_every"]),
            "batch_size": int(src["scan"]["batch_size"]),
        }
        assert prof["sweep"] == {
            "sets": int(src["sweep"]["sets"]),
            "ways": int(src["sweep"]["ways"]),
            "index_mode": int(src["sweep"]["index_mode"]),
        }
