# tools/step40_joint_opt_pareto.py
# -*- coding: utf-8 -*-

"""Step40：scan + sweep 联合扫参（worst-case）+ Pareto 前沿 + knee 选择

背景（承接 Step37/38/39）：
- Score 定义：越小越好（cycle + stall_in + sweep.replace 加权）。
- 稳健性：worst_score = max(score across workload_modes)（真正 worst-case）。
- Step38/39 分别给了 scan / sweep 单独维度的敏感性和推荐。
- Step40 把 scan 与 sweep 放到同一个端到端评估里，输出：
  1) 全组合的 worst_score
  2) (worst_score, cost) Pareto 前沿
  3) “knee” 点（在 performance 与 cost 之间的折中点）

注意：
- cost 模型是一个“工程 proxy”，并非面积/功耗的真实物理值；目的只是让扫参结果可解释、可做架构取舍。
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, List, Tuple, Any
import math

from tools.step31_mutator_report import run_step31
from tools.step33_scan_recommend import _score


@dataclass(frozen=True)
class ScanCfg:
    cardset_size: int
    fifo_depth: int
    consume_every: int
    batch_size: int


@dataclass(frozen=True)
class SweepCfg:
    sets: int
    ways: int
    index_mode: int


def cost_model(scan: ScanCfg, sweep: SweepCfg) -> float:
    """一个简单、可解释、可复现的 cost proxy（越小越好）。

    直觉：
    - scan：cardset/batch 影响 datapath 与 SRAM/寄存器规模；fifo_depth 影响队列 SRAM。
    - sweep：sets*ways 近似容量；index_mode 影响 hash/索引逻辑复杂度。
    - consume_every 是节奏参数，主要影响控制与时序，成本近似忽略（在这个 proxy 里为 0）。
    """
    scan_cost = 1.0 * float(scan.cardset_size) + 2.0 * float(scan.fifo_depth) + 1.5 * float(scan.batch_size)
    sweep_cost = 1.0 * float(sweep.sets * sweep.ways) + (0.0 if sweep.index_mode == 0 else (4.0 if sweep.index_mode == 1 else 8.0))
    return scan_cost + sweep_cost


def eval_one(
    *,
    base_cfg: Dict[str, Any],
    scan: ScanCfg,
    sweep: SweepCfg,
    workload_mode: str,
    global_share_p: float,
    w_cycle: float,
    w_stall: float,
    w_replace: float,
) -> Dict[str, Any]:
    rep = run_step31(
        seed=int(base_cfg["seed"]),
        ncores=int(base_cfg["ncores"]),
        epochs=int(base_cfg["epochs"]),
        events_per_core_per_epoch=int(base_cfg["events_per_core_per_epoch"]),
        card_space=int(base_cfg["card_space"]),
        zipf_s=float(base_cfg["zipf_s"]),
        phase_shift=int(base_cfg["phase_shift"]),
        workload_mode=str(workload_mode),
        global_share_p=float(global_share_p),
        scan_cardset_size=int(scan.cardset_size),
        scan_fifo_depth=int(scan.fifo_depth),
        scan_consume_every=int(scan.consume_every),
        scan_batch_size=int(scan.batch_size),
        sweep_sets=int(sweep.sets),
        sweep_ways=int(sweep.ways),
        sweep_index_mode=int(sweep.index_mode),
    )
    score = _score(rep, w_cycle=w_cycle, w_stall=w_stall, w_replace=w_replace)
    return {"workload_mode": workload_mode, "score": float(score), "cycle": int(rep["cycle"]), "stall_in": int(rep["scan"]["stats"].get("stall_in", 0)), "replace": int(rep["sweep"]["stats"].get("replace", 0))}


def pareto_front(points: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """求 (worst_score, cost) 的非支配集合。"""
    # Sort by score asc then cost asc for efficient prune
    pts = sorted(points, key=lambda r: (r["worst_score"], r["cost"]))
    front: List[Dict[str, Any]] = []
    best_cost = math.inf
    for r in pts:
        c = float(r["cost"])
        if c < best_cost - 1e-12:
            front.append(r)
            best_cost = c
    return front


def choose_near_best_cheapest(rows_sorted: List[Dict[str, Any]], *, epsilon: float = 0.02) -> Dict[str, Any]:
    """选一个更贴近工程语义的“折中点”：
    - 先找全局最优 worst_score（越小越好）
    - 在 worst_score 不超过 (1+epsilon)*best 的候选里，选 cost 最小者
    这样更像“性能几乎不变但更省面积/功耗”的默认取舍。
    """
    if not rows_sorted:
        raise ValueError("empty candidates")
    best = float(rows_sorted[0]["worst_score"])
    thr = best * (1.0 + float(epsilon))
    pool = [r for r in rows_sorted if float(r["worst_score"]) <= thr]
    # 如果 pool 为空（极端情况），就退化为 Pareto 最优点
    if not pool:
        pool = rows_sorted[:1]
    pool = sorted(pool, key=lambda r: (float(r["cost"]), float(r["worst_score"])))
    return pool[0]

def recommend_joint_pareto(
    *,
    base_cfg: Dict[str, Any],
    scan_grid: List[ScanCfg],
    sweep_grid: List[SweepCfg],
    workload_modes: List[str],
    global_share_p: float,
    w_cycle: float,
    w_stall: float,
    w_replace: float,
    topn: int,
) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []

    for sc in scan_grid:
        for sw in sweep_grid:
            per_mode: Dict[str, Dict[str, Any]] = {}
            for wm in workload_modes:
                per_mode[wm] = eval_one(
                    base_cfg=base_cfg,
                    scan=sc,
                    sweep=sw,
                    workload_mode=wm,
                    global_share_p=global_share_p,
                    w_cycle=w_cycle,
                    w_stall=w_stall,
                    w_replace=w_replace,
                )

            worst_mode = max(per_mode.keys(), key=lambda k: float(per_mode[k]["score"]))
            worst_score = float(per_mode[worst_mode]["score"])
            row = {
                "scan": asdict(sc),
                "sweep": asdict(sw),
                "per_mode": per_mode,
                "worst_mode": worst_mode,
                "worst_score": worst_score,
                "cost": float(cost_model(sc, sw)),
            }
            rows.append(row)

    rows_sorted = sorted(rows, key=lambda r: (float(r["worst_score"]), float(r["cost"])))
    front = pareto_front(rows_sorted)
    knee = choose_near_best_cheapest(rows_sorted, epsilon=0.02)

    return {
        "base_cfg": base_cfg,
        "workload_modes": list(workload_modes),
        "global_share_p": float(global_share_p),
        "weights": {"w_cycle": float(w_cycle), "w_stall": float(w_stall), "w_replace": float(w_replace)},
        "top": rows_sorted[: int(topn)],
        "pareto_front": front,
        "knee_method": "near_best_cheapest(eps=0.02)",
        "knee": knee,
        "summary": {
            "n_total": len(rows_sorted),
            "n_front": len(front),
            "best_worst_score": float(rows_sorted[0]["worst_score"]) if rows_sorted else None,
            "min_cost_on_front": min(float(r["cost"]) for r in front) if front else None,
        },
    }
