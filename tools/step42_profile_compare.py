# tools/step42_profile_compare.py
# -*- coding: utf-8 -*-

"""Step42：Profile 对比基准（step30 vs step40_joint）

动机（承接 Step41）：
- Step41 引入了 GC profile（step30 / step40_joint），并接入 TopSoC.with_profile()。
- 但目前 profile 的“收益/代价”只有在 Step40/41 的单点结论里体现，缺少一个可复现、可回归的对比基准。
- Step42 增加一个纯 Python 的 profile benchmark：
    * 在相同 mutator→scan→sweep workload 下，对多个 profile 计算 per-workload score 和 worst-case score
    * 同时输出 cost proxy（复用 Step40 cost_model），用于工程取舍解释
    * 结果固化为 baseline，避免后续模型调整导致 profile 结论悄悄漂移

Score 定义：越小越好（与 Step33/37/40 一致）
  score = w_cycle*cycle + w_stall*stall_in + w_replace*sweep.replace
Worst-case：worst_score = max(score across workload_modes)
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from typing import Dict, Any, List, Tuple

from .step31_mutator_report import run_step31
from .step33_scan_recommend import _score as score_fn  # reuse exact formula
from .step40_joint_opt_pareto import ScanCfg, SweepCfg, cost_model
from rtl.gc_profile_params import get_profile


def _default_base_cfg() -> dict:
    # 与 Step34 baseline 一致，保证回归快速可复现
    return {
        "seed": 20260102,
        "ncores": 4,
        "epochs": 2,
        "events_per_core_per_epoch": 64,
        "card_space": 64,
        "zipf_s": 1.07,
        "phase_shift": 7,
    }


def _default_workloads() -> List[Tuple[str, float]]:
    return [
        ("shared_hot_shift", 0.10),
        ("per_core_partition", 0.10),
    ]


def eval_profile(
    *,
    profile_name: str,
    base_cfg: Dict[str, Any],
    workloads: List[Tuple[str, float]],
    w_cycle: float = 1.0,
    w_stall: float = 10.0,
    w_replace: float = 2.0,
) -> Dict[str, Any]:
    prof = get_profile(profile_name)
    scan = prof["scan"]
    sweep = prof["sweep"]

    scan_cfg = ScanCfg(
        cardset_size=int(scan["cardset_size"]),
        fifo_depth=int(scan["fifo_depth"]),
        consume_every=int(scan["consume_every"]),
        batch_size=int(scan["batch_size"]),
    )
    sweep_cfg = SweepCfg(
        sets=int(sweep["sets"]),
        ways=int(sweep["ways"]),
        index_mode=int(sweep["index_mode"]),
    )

    per_mode: List[Dict[str, Any]] = []
    for mode, gsp in workloads:
        r = run_step31(
            seed=int(base_cfg["seed"]),
            ncores=int(base_cfg["ncores"]),
            epochs=int(base_cfg["epochs"]),
            events_per_core_per_epoch=int(base_cfg["events_per_core_per_epoch"]),
            card_space=int(base_cfg["card_space"]),
            zipf_s=float(base_cfg["zipf_s"]),
            phase_shift=int(base_cfg["phase_shift"]),
            scan_cardset_size=scan_cfg.cardset_size,
            scan_fifo_depth=scan_cfg.fifo_depth,
            scan_consume_every=scan_cfg.consume_every,
            scan_batch_size=scan_cfg.batch_size,
            sweep_sets=sweep_cfg.sets,
            sweep_ways=sweep_cfg.ways,
            sweep_index_mode=sweep_cfg.index_mode,
            workload_mode=mode,
            global_share_p=float(gsp),
        )
        s = score_fn(r, w_cycle=w_cycle, w_stall=w_stall, w_replace=w_replace)
        per_mode.append(
            {
                "workload_mode": mode,
                "global_share_p": float(gsp),
                "score": float(s),
                "cycle": int(r.get("cycle", 0)),
                "stall_in": int(r["scan"]["stats"].get("stall_in", 0)),
                "sweep_replace": int(r["sweep"]["stats"].get("replace", 0)),
            }
        )

    worst = max(per_mode, key=lambda x: x["score"])
    best = min(per_mode, key=lambda x: x["score"])
    return {
        "profile": profile_name,
        "note": prof.get("note", ""),
        "scan": asdict(scan_cfg),
        "sweep": asdict(sweep_cfg),
        "per_mode": per_mode,
        "worst_score": float(worst["score"]),
        "worst_mode": str(worst["workload_mode"]),
        "best_score": float(best["score"]),
        "best_mode": str(best["workload_mode"]),
        "cost": float(cost_model(scan_cfg, sweep_cfg)),
        "weights": {"w_cycle": float(w_cycle), "w_stall": float(w_stall), "w_replace": float(w_replace)},
        "base_cfg": dict(base_cfg),
    }


def compare_profiles(
    *,
    profile_names: List[str],
    base_cfg: Dict[str, Any],
    workloads: List[Tuple[str, float]],
    w_cycle: float = 1.0,
    w_stall: float = 10.0,
    w_replace: float = 2.0,
) -> Dict[str, Any]:
    results = [eval_profile(profile_name=p, base_cfg=base_cfg, workloads=workloads,
                            w_cycle=w_cycle, w_stall=w_stall, w_replace=w_replace)
               for p in profile_names]

    # convenience: improvement vs first profile
    ref = results[0]
    ref_worst = float(ref["worst_score"])
    for r in results[1:]:
        r["worst_improve_vs_ref"] = float(ref_worst - float(r["worst_score"]))
        r["worst_improve_pct_vs_ref"] = float((ref_worst - float(r["worst_score"])) / ref_worst) if ref_worst else 0.0

    # sort by worst_score
    results_sorted = sorted(results, key=lambda x: x["worst_score"])
    return {
        "profiles": results_sorted,
        "ref_profile": profile_names[0] if profile_names else None,
        "workloads": [{"mode": m, "global_share_p": float(g)} for m, g in workloads],
    }


def _md_report(rep: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# Step42 Profile Benchmark\n\n")
    lines.append("## Workloads\n\n")
    for w in rep["workloads"]:
        lines.append(f"- {w['mode']} (global_share_p={w['global_share_p']})\n")
    lines.append("\n## Profiles (sorted by worst_score, lower is better)\n\n")
    lines.append("|rank|profile|worst_score|worst_mode|cost|note|\n|---:|---|---:|---|---:|---|\n")
    for i, p in enumerate(rep["profiles"], 1):
        note = (p.get("note", "") or "").replace("|", "\\|")
        lines.append(f"|{i}|{p['profile']}|{p['worst_score']:.2f}|{p['worst_mode']}|{p['cost']:.2f}|{note}|\n")
    lines.append("\n## Per-workload details\n\n")
    for p in rep["profiles"]:
        lines.append(f"### {p['profile']}\n\n")
        lines.append(f"- scan={p['scan']} sweep={p['sweep']} cost={p['cost']:.2f}\n\n")
        lines.append("|workload|score|cycle|stall_in|sweep.replace|\n|---|---:|---:|---:|---:|\n")
        for m in p["per_mode"]:
            lines.append(f"|{m['workload_mode']}|{m['score']:.2f}|{m['cycle']}|{m['stall_in']}|{m['sweep_replace']}|\n")
        if "worst_improve_pct_vs_ref" in p:
            lines.append(f"\n- worst_score improve vs {rep.get('ref_profile')}: {p['worst_improve_vs_ref']:.2f} ({p['worst_improve_pct_vs_ref']*100:.2f}%)\n\n")
        lines.append("\n")
    return "".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="reports")
    ap.add_argument("--name", default="step42_profile_benchmark")
    ap.add_argument("--profiles", default="step30,step40_joint")
    ap.add_argument("--w-cycle", type=float, default=1.0)
    ap.add_argument("--w-stall", type=float, default=10.0)
    ap.add_argument("--w-replace", type=float, default=2.0)
    args = ap.parse_args()

    base_cfg = _default_base_cfg()
    workloads = _default_workloads()
    profile_names = [p.strip() for p in args.profiles.split(",") if p.strip()]
    rep = compare_profiles(
        profile_names=profile_names,
        base_cfg=base_cfg,
        workloads=workloads,
        w_cycle=args.w_cycle,
        w_stall=args.w_stall,
        w_replace=args.w_replace,
    )

    os.makedirs(args.outdir, exist_ok=True)
    jpath = os.path.join(args.outdir, f"{args.name}.json")
    mpath = os.path.join(args.outdir, f"{args.name}.md")
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(rep, f, indent=2, ensure_ascii=False, sort_keys=True)
    with open(mpath, "w", encoding="utf-8") as f:
        f.write(_md_report(rep))
    print(f"Wrote {jpath} and {mpath}")


if __name__ == "__main__":
    main()
