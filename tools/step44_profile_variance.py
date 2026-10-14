# tools/step44_profile_variance.py
# -*- coding: utf-8 -*-

"""Step44：Profile 稳健性/方差评估（跨随机种子）

动机：
- Step42/43 的 profile benchmark/catelog 都是“单个固定种子”的可回归基准。
- 但真实 mutator 写入存在随机性：热点排序、phase 迁移、跨核共享触达等。
- Step44 增加跨多个种子的统计评估：
    * per-seed 端到端评估（mutator→scan→sweep）
    * 计算每个 profile 的 worst_score 均值/方差/区间
    * 统计与参考 profile（默认第一个）相比的胜率

注意：
- 这是研究用统计工具，不替代 Step42 的“单点 baseline 回归”。
- 本工具的结果同样可以固化为 baseline（generate_step44_*），用于防止“稳健性结论”漂移。
"""

from __future__ import annotations

import argparse
import json
import math
import os
from typing import Any, Dict, List, Tuple

from .step42_profile_compare import _default_base_cfg, _default_workloads, eval_profile


def _default_seeds() -> List[int]:
    # 连续种子便于人工复现
    return [20260102, 20260103, 20260104, 20260105, 20260106]


def _mean(xs: List[float]) -> float:
    return sum(xs) / float(len(xs)) if xs else 0.0


def _std(xs: List[float]) -> float:
    if len(xs) <= 1:
        return 0.0
    m = _mean(xs)
    v = sum((x - m) ** 2 for x in xs) / float(len(xs) - 1)
    return math.sqrt(v)


def eval_profiles_over_seeds(
    *,
    profile_names: List[str],
    base_cfg_no_seed: Dict[str, Any],
    seeds: List[int],
    workloads: List[Tuple[str, float]],
    w_cycle: float = 1.0,
    w_stall: float = 10.0,
    w_replace: float = 2.0,
) -> Dict[str, Any]:
    assert profile_names, "need at least one profile"
    assert seeds, "need at least one seed"

    per_seed: List[Dict[str, Any]] = []
    for seed in seeds:
        base_cfg = dict(base_cfg_no_seed)
        base_cfg["seed"] = int(seed)
        one: Dict[str, Any] = {
            "seed": int(seed),
            "profiles": [],
        }
        for p in profile_names:
            r = eval_profile(
                profile_name=p,
                base_cfg=base_cfg,
                workloads=workloads,
                w_cycle=w_cycle,
                w_stall=w_stall,
                w_replace=w_replace,
            )
            one["profiles"].append(
                {
                    "profile": r["profile"],
                    "worst_score": float(r["worst_score"]),
                    "worst_mode": str(r["worst_mode"]),
                    "best_score": float(r["best_score"]),
                    "best_mode": str(r["best_mode"]),
                    "cost": float(r["cost"]),
                }
            )
        # stable ordering for later processing
        one["profiles"] = sorted(one["profiles"], key=lambda x: profile_names.index(x["profile"]))
        per_seed.append(one)

    # aggregate per profile
    ref = profile_names[0]
    agg: List[Dict[str, Any]] = []
    for p in profile_names:
        scores = [
            next(pp["worst_score"] for pp in s["profiles"] if pp["profile"] == p)
            for s in per_seed
        ]
        mean = _mean(scores)
        std = _std(scores)
        mn = min(scores)
        mx = max(scores)

        # wins vs ref (lower is better)
        if p == ref:
            wins = None
            win_rate = None
        else:
            wins = 0
            for s in per_seed:
                s_ref = next(pp["worst_score"] for pp in s["profiles"] if pp["profile"] == ref)
                s_p = next(pp["worst_score"] for pp in s["profiles"] if pp["profile"] == p)
                if s_p < s_ref:
                    wins += 1
            win_rate = float(wins) / float(len(seeds))

        # average rank per seed (1=best)
        ranks: List[int] = []
        for s in per_seed:
            sorted_p = sorted(s["profiles"], key=lambda x: x["worst_score"])
            for i, item in enumerate(sorted_p, 1):
                if item["profile"] == p:
                    ranks.append(i)
                    break
        avg_rank = _mean([float(r) for r in ranks]) if ranks else 0.0

        agg.append(
            {
                "profile": p,
                "worst_score_mean": float(mean),
                "worst_score_std": float(std),
                "worst_score_min": float(mn),
                "worst_score_max": float(mx),
                "avg_rank": float(avg_rank),
                "wins_vs_ref": wins,
                "win_rate_vs_ref": win_rate,
                "n_seeds": int(len(seeds)),
            }
        )

    # sort by mean worst_score
    agg_sorted = sorted(agg, key=lambda x: x["worst_score_mean"])

    return {
        "profiles": agg_sorted,
        "per_seed": per_seed,
        "ref_profile": ref,
        "seeds": [int(x) for x in seeds],
        "workloads": [{"mode": m, "global_share_p": float(g)} for m, g in workloads],
        "weights": {"w_cycle": float(w_cycle), "w_stall": float(w_stall), "w_replace": float(w_replace)},
        "base_cfg_no_seed": dict(base_cfg_no_seed),
    }


def _md_report(rep: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# Step44 Profile Variance (across seeds)\n\n")
    lines.append(f"ref_profile: **{rep['ref_profile']}**\\n\\n")

    lines.append("## Workloads\n\n")
    for w in rep["workloads"]:
        lines.append(f"- {w['mode']} (global_share_p={w['global_share_p']})\n")
    lines.append("\n")

    lines.append("## Summary (sorted by mean worst_score, lower is better)\n\n")
    lines.append("|rank|profile|mean|std|min|max|avg_rank|wins_vs_ref|win_rate|\n|---:|---|---:|---:|---:|---:|---:|---:|---:|\n")
    for i, p in enumerate(rep["profiles"], 1):
        wins = "-" if p["wins_vs_ref"] is None else str(p["wins_vs_ref"])
        wr = "-" if p["win_rate_vs_ref"] is None else f"{p['win_rate_vs_ref']*100:.1f}%"
        lines.append(
            f"|{i}|{p['profile']}|{p['worst_score_mean']:.2f}|{p['worst_score_std']:.2f}|{p['worst_score_min']:.2f}|{p['worst_score_max']:.2f}|{p['avg_rank']:.2f}|{wins}|{wr}|\n"
        )

    lines.append("\n## Per-seed details\n\n")
    for s in rep["per_seed"]:
        lines.append(f"### seed={s['seed']}\n\n")
        lines.append("|profile|worst_score|worst_mode|cost|\n|---|---:|---|---:|\n")
        for p in s["profiles"]:
            lines.append(f"|{p['profile']}|{p['worst_score']:.2f}|{p['worst_mode']}|{p['cost']:.2f}|\n")
        lines.append("\n")

    return "".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="reports")
    ap.add_argument("--name", default="step44_profile_variance")
    ap.add_argument("--profiles", default="step30,step40_joint")
    ap.add_argument("--seeds", default="")
    ap.add_argument("--w-cycle", type=float, default=1.0)
    ap.add_argument("--w-stall", type=float, default=10.0)
    ap.add_argument("--w-replace", type=float, default=2.0)
    args = ap.parse_args()

    base_cfg = _default_base_cfg()
    base_cfg_no_seed = dict(base_cfg)
    base_cfg_no_seed.pop("seed", None)

    workloads = _default_workloads()
    profile_names = [p.strip() for p in args.profiles.split(",") if p.strip()]
    seeds = (
        [int(x.strip()) for x in args.seeds.split(",") if x.strip()]
        if args.seeds.strip()
        else _default_seeds()
    )

    rep = eval_profiles_over_seeds(
        profile_names=profile_names,
        base_cfg_no_seed=base_cfg_no_seed,
        seeds=seeds,
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
