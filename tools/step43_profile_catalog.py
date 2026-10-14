# tools/step43_profile_catalog.py
# -*- coding: utf-8 -*-

"""Step43：Profile 目录（catalog）与工程对比

承接 Step42：
- Step42 只对比了 step30 vs step40_joint。
- Step43 将 Step40 的 Pareto 前沿其它点也固化为 profile（见 rtl/gc_profile_params.py），
  并提供一个“目录式”的对比报告：同一套端到端 workload 下，按 worst_score 排序列出所有 profile。

用途：
- 便于在“多档配置/资源预算”讨论时，不止有一个 knee 点，而是有一条可审计的成本-性能序列。
- 同时把对比固化为 baseline，避免后续模型变更导致档位结论悄悄漂移。
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, List, Tuple

from .step42_profile_compare import (
    compare_profiles,
    _default_base_cfg,
    _default_workloads,
)


def _default_profiles() -> List[str]:
    return [
        "step30",
        "step40_joint",
        "step40_pareto1",
        "step40_pareto2",
        "step40_pareto3",
    ]


def _md_report(rep: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# Step43 Profile Catalog\n\n")
    lines.append("## Workloads\n\n")
    for w in rep["workloads"]:
        lines.append(f"- {w['mode']} (global_share_p={w['global_share_p']})\n")
    lines.append("\n## Profiles (sorted by worst_score, lower is better)\n\n")
    lines.append("|rank|profile|worst_score|worst_mode|cost|\n|---:|---|---:|---|---:|\n")
    for i, p in enumerate(rep["profiles"], 1):
        lines.append(f"|{i}|{p['profile']}|{p['worst_score']:.2f}|{p['worst_mode']}|{p['cost']:.2f}|\n")
    lines.append("\n## Per-workload details\n\n")
    for p in rep["profiles"]:
        lines.append(f"### {p['profile']}\n\n")
        lines.append(f"- scan={p['scan']} sweep={p['sweep']} cost={p['cost']:.2f}\n\n")
        lines.append("|workload|score|cycle|stall_in|sweep.replace|\n|---|---:|---:|---:|---:|\n")
        for m in p["per_mode"]:
            lines.append(
                f"|{m['workload_mode']}|{m['score']:.2f}|{m['cycle']}|{m['stall_in']}|{m['sweep_replace']}|\n"
            )
        lines.append("\n")
    return "".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="reports")
    ap.add_argument("--name", default="step43_profile_catalog")
    ap.add_argument("--profiles", default=",".join(_default_profiles()))
    ap.add_argument("--w-cycle", type=float, default=1.0)
    ap.add_argument("--w-stall", type=float, default=10.0)
    ap.add_argument("--w-replace", type=float, default=2.0)
    args = ap.parse_args()

    profile_names = [p.strip() for p in args.profiles.split(",") if p.strip()]
    rep = compare_profiles(
        profile_names=profile_names,
        base_cfg=_default_base_cfg(),
        workloads=_default_workloads(),
        w_cycle=float(args.w_cycle),
        w_stall=float(args.w_stall),
        w_replace=float(args.w_replace),
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
