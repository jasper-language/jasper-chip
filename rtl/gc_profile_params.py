# rtl/gc_profile_params.py
# -*- coding: utf-8 -*-
"""GC 参数配置档（profile）

目的：
  - 保留 Step30 的“默认 sweep 参数锁定 + 回归基线”，避免历史回归被新研究结果打破；
  - 同时提供更后续的研究档（例如 Step40 的 joint pareto knee），用于可控切换默认值。

约定：
  - profile 只负责“推荐的默认参数组合”；
  - TopSoC.with_profile(profile, **kwargs) 会把对应参数填入构造函数（kwargs 可覆盖）。
"""

from __future__ import annotations

from typing import Dict, Any

from .gc_params import (
    DEFAULT_SWEEP_CARD_TABLE_SIZE,
    DEFAULT_SWEEP_CARD_TABLE_WAYS,
    DEFAULT_SWEEP_CARD_INDEX_MODE,
)

# scan 默认值来自 Step33/34 固化文件：rtl/gc_scan_params.py
try:
    from .gc_scan_params import (
        SCAN_CARDSET_SIZE,
        SCAN_FIFO_DEPTH,
        SCAN_CONSUME_EVERY,
        SCAN_BATCH_SIZE,
    )
except Exception:  # pragma: no cover
    # 兜底：不影响 ISA 正确性，只影响研究/吞吐指标
    SCAN_CARDSET_SIZE = 16
    SCAN_FIFO_DEPTH = 16
    SCAN_CONSUME_EVERY = 1
    SCAN_BATCH_SIZE = 1


def _mk_scan(cardset_size: int, fifo_depth: int, consume_every: int, batch_size: int) -> Dict[str, int]:
    return dict(
        cardset_size=int(cardset_size),
        fifo_depth=int(fifo_depth),
        consume_every=int(consume_every),
        batch_size=int(batch_size),
    )


def _mk_sweep(sets: int, ways: int, index_mode: int) -> Dict[str, int]:
    return dict(sets=int(sets), ways=int(ways), index_mode=int(index_mode))


PROFILES: Dict[str, Dict[str, Any]] = {
    # 历史默认：用于 Step30 baseline 回归
    "step30": {
        "scan": _mk_scan(SCAN_CARDSET_SIZE, SCAN_FIFO_DEPTH, SCAN_CONSUME_EVERY, SCAN_BATCH_SIZE),
        "sweep": _mk_sweep(DEFAULT_SWEEP_CARD_TABLE_SIZE, DEFAULT_SWEEP_CARD_TABLE_WAYS, DEFAULT_SWEEP_CARD_INDEX_MODE),
        "note": "Step30 baseline: sweep 参数锁定 + 回归保护（scan 使用 Step33/34 固化默认）",
    },
    # 新研究默认：来自 Step40 joint pareto knee（scan + sweep 联合折中点）
    "step40_joint": {
        "scan": _mk_scan(8, 1, 2, 2),
        "sweep": _mk_sweep(16, 4, 0),
        "note": "Step40 knee: joint scan×sweep worst-case + pareto cost proxy 的折中点",
    },

    # Step43：把 Step40 的 Pareto 前沿其它点也固化成 profile，方便“不同成本档”做工程对比。
    # 这些 profile 仅用于研究/评估，不改变 TopSoC() 的历史默认。
    # 来源：reports/step40_joint_pareto_baseline.json 中的 pareto_front[1:]
    "step40_pareto1": {
        "scan": _mk_scan(8, 1, 4, 2),
        "sweep": _mk_sweep(8, 4, 0),
        "note": "Step40 pareto[1]: cost≈45，吞吐明显退化但更省 sweep 容量（用于成本档对比）",
    },
    "step40_pareto2": {
        "scan": _mk_scan(8, 1, 4, 2),
        "sweep": _mk_sweep(16, 1, 0),
        "note": "Step40 pareto[2]: cost≈29，进一步压 ways（用于探索极低成本 sweep 配置的代价）",
    },
    "step40_pareto3": {
        "scan": _mk_scan(8, 1, 4, 2),
        "sweep": _mk_sweep(8, 1, 0),
        "note": "Step40 pareto[3]: cost≈21，最低成本点（用于估计最小 sweep 资源下的 worst-case 损失）",
    },
}


def get_profile(name: str) -> Dict[str, Any]:
    if name not in PROFILES:
        raise KeyError(f"unknown GC profile: {name!r}, available={sorted(PROFILES.keys())}")
    return PROFILES[name]
