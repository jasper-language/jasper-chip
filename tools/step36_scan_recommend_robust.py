# tools/step36_scan_recommend_robust.py
# -*- coding: utf-8 -*-

"""
Step36：把 Step35 引入的更真实多核写入形态（per_core_partition）纳入 scan 参数推荐，并做 robust 排名。

原则：
- 不破坏 Step34 的单模式 baseline（仍使用 tools.step33_scan_recommend.recommend 默认 shared_hot_shift）。
- Step36 额外生成一个“跨 workload 模式”的推荐：
    * shared_hot_shift
    * per_core_partition
  并以 worst-case(min) 作为 robust_score，排序给出 Top-N。
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from typing import Dict, List, Tuple

from tools.step31_mutator_report import run_step31
import tools.step33_scan_recommend as s33  # 复用 Step33 的 sweep 默认与 score 逻辑


def recommend_robust(
    *,
    base_cfg: Dict,
    scan_grid: List[s33.ScanCfg],
    topn: int,
    modes: List[str],
    global_share_p: float,
    w_cycle: float,
    w_stall: float,
    w_replace: float,
) -> Dict:
    """对同一 scan_grid 在多种 workload 下评估，并做 robust(min) 排名。"""
    sweep_sets, sweep_ways, sweep_index_mode = s33._load_sweep_defaults()

    rows: List[Dict] = []
    for sc in scan_grid:
        per_mode: Dict[str, Dict] = {}
        per_mode_score: Dict[str, float] = {}
        for mode in modes:
            r = run_step31(
                seed=base_cfg["seed"],
                ncores=base_cfg["ncores"],
                epochs=base_cfg["epochs"],
                events_per_core_per_epoch=base_cfg["events_per_core_per_epoch"],
                card_space=base_cfg["card_space"],
                zipf_s=base_cfg["zipf_s"],
                phase_shift=base_cfg["phase_shift"],
                scan_cardset_size=sc.cardset_size,
                scan_fifo_depth=sc.fifo_depth,
                scan_consume_every=sc.consume_every,
                scan_batch_size=sc.batch_size,
                sweep_sets=sweep_sets,
                sweep_ways=sweep_ways,
                sweep_index_mode=sweep_index_mode,
                workload_mode=mode,
                global_share_p=global_share_p,
            )
            s = s33._score(r, w_cycle=w_cycle, w_stall=w_stall, w_replace=w_replace)
            per_mode[mode] = r
            per_mode_score[mode] = float(s)

        robust_score = min(per_mode_score.values())
        rows.append(
            {
                "robust_score": float(robust_score),
                "scores": per_mode_score,
                **asdict(sc),
                # 只保留关键统计（避免 baseline 因字段增减漂移）
                "per_mode": {
                    m: {
                        "cycle": per_mode[m]["cycle"],
                        "scan": {"stall_in": per_mode[m]["scan"]["stats"]["stall_in"]},
                        "sweep": {"replace": per_mode[m]["sweep"]["stats"]["replace"]},
                    }
                    for m in modes
                },
            }
        )

    rows.sort(key=lambda r: r["robust_score"])
    top = rows[: max(1, topn)]

    # 也输出每个 mode 的 Top-1（方便直观看到差异）
    per_mode_best = {}
    for m in modes:
        best = min(rows, key=lambda r: r["scores"][m])
        per_mode_best[m] = best

    return {
        "base_cfg": dict(base_cfg),
        "workloads": {"modes": list(modes), "global_share_p": float(global_share_p)},
        "sweep_defaults": {"sets": sweep_sets, "ways": sweep_ways, "index_mode": sweep_index_mode},
        "weights": {"w_cycle": w_cycle, "w_stall": w_stall, "w_replace": w_replace},
        "per_mode_best": per_mode_best,
        "top": top,
    }


def _md(report: Dict) -> str:
    b = report["base_cfg"]
    sw = report["sweep_defaults"]
    w = report["weights"]
    wl = report["workloads"]
    modes = wl["modes"]

    lines: List[str] = []
    lines.append("# Step36 Robust Scan Default Recommendation\n\n")
    lines.append("## Base workload\n")
    lines.append(
        f"- seed={b['seed']} ncores={b['ncores']} epochs={b['epochs']} events/core/epoch={b['events_per_core_per_epoch']}\n"
    )
    lines.append(f"- card_space={b['card_space']} zipf_s={b['zipf_s']} phase_shift={b['phase_shift']}\n")
    lines.append("\n## Workload modes\n")
    lines.append(f"- modes={', '.join(modes)} global_share_p={wl['global_share_p']}\n")
    lines.append("\n## Sweep defaults\n")
    lines.append(f"- sets={sw['sets']} ways={sw['ways']} index_mode={sw['index_mode']}\n")
    lines.append("\n## Score weights\n")
    lines.append(f"- w_cycle={w['w_cycle']} w_stall={w['w_stall']} w_replace={w['w_replace']}\n")

    lines.append("\n## Per-mode Top-1 (for comparison)\n")
    lines.append("|mode|robust_score|score(mode)|cardset|fifo|consume|batch|cycle|stall_in|replace|\n")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n")
    for m in modes:
        r = report["per_mode_best"][m]
        lines.append(
            f"|{m}|{r['robust_score']:.2f}|{r['scores'][m]:.2f}|{r['cardset_size']}|{r['fifo_depth']}|{r['consume_every']}|{r['batch_size']}|"
            f"{r['per_mode'][m]['cycle']}|{r['per_mode'][m]['scan']['stall_in']}|{r['per_mode'][m]['sweep']['replace']}|\n"
        )

    lines.append("\n## Robust Top-N (sorted by min(score))\n")
    # header includes per-mode scores
    lines.append("|rank|robust_score|" + "|".join([f"score:{m}" for m in modes]) + "|cardset|fifo|consume|batch|\n")
    lines.append("|---:|---:|" + "|".join(["---:"] * len(modes)) + "|---:|---:|---:|---:|\n")
    for i, r in enumerate(report["top"], start=1):
        scores = "|".join([f"{r['scores'][m]:.2f}" for m in modes])
        lines.append(
            f"|{i}|{r['robust_score']:.2f}|{scores}|{r['cardset_size']}|{r['fifo_depth']}|{r['consume_every']}|{r['batch_size']}|\n"
        )
    return "".join(lines)


def _parse_int_list(s: str) -> List[int]:
    return [int(x) for x in s.split(",") if x.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="reports")
    ap.add_argument("--name", default="step36_scan_robust")

    ap.add_argument("--seed", type=int, default=20260102)
    ap.add_argument("--ncores", type=int, default=4)
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--events-per-core-per-epoch", type=int, default=64)
    ap.add_argument("--card-space", type=int, default=64)
    ap.add_argument("--zipf-s", type=float, default=1.07)
    ap.add_argument("--phase-shift", type=int, default=7)

    ap.add_argument("--modes", default="shared_hot_shift,per_core_partition")
    ap.add_argument("--global-share-p", type=float, default=0.10)

    ap.add_argument("--cardset", default="8,16")
    ap.add_argument("--fifo", default="1,2,4")
    ap.add_argument("--consume", default="2,4,8")
    ap.add_argument("--batch", default="1,2,4")

    ap.add_argument("--topn", type=int, default=10)
    ap.add_argument("--w-cycle", type=float, default=1.0)
    ap.add_argument("--w-stall", type=float, default=8.0)
    ap.add_argument("--w-replace", type=float, default=4.0)

    args = ap.parse_args()

    base_cfg = {
        "seed": args.seed,
        "ncores": args.ncores,
        "epochs": args.epochs,
        "events_per_core_per_epoch": args.events_per_core_per_epoch,
        "card_space": args.card_space,
        "zipf_s": args.zipf_s,
        "phase_shift": args.phase_shift,
    }

    scan_grid: List[s33.ScanCfg] = []
    for cs in _parse_int_list(args.cardset):
        for fd in _parse_int_list(args.fifo):
            for ce in _parse_int_list(args.consume):
                for bs in _parse_int_list(args.batch):
                    scan_grid.append(s33.ScanCfg(cardset_size=cs, fifo_depth=fd, consume_every=ce, batch_size=bs))

    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    rep = recommend_robust(
        base_cfg=base_cfg,
        scan_grid=scan_grid,
        topn=args.topn,
        modes=modes,
        global_share_p=args.global_share_p,
        w_cycle=args.w_cycle,
        w_stall=args.w_stall,
        w_replace=args.w_replace,
    )

    os.makedirs(args.outdir, exist_ok=True)
    json_path = os.path.join(args.outdir, f"{args.name}.json")
    md_path = os.path.join(args.outdir, f"{args.name}.md")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(_md(rep))

    print(f"OK: wrote {json_path} and {md_path}")


if __name__ == "__main__":
    main()
