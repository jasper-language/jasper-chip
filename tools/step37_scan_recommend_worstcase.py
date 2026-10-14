# tools/step37_scan_recommend_worstcase.py
# -*- coding: utf-8 -*-

"""Step37：引入真正的 worst-case(max) scan 参数稳健推荐。

背景：
  Step36 已把 per_core_partition 纳入推荐闭环，但其 robust_score 采用的是
  `min(score_mode)`。在“score 越小越好”的前提下，min 实际上代表 *best-case*，
  并不能衡量跨 workload 的最坏情况。

本 Step37：
  - 保留 Step36 不动（避免破坏已有 baseline）。
  - 新增本工具：对同一 scan_grid 在多 workload 模式下评估，并用
      worst_score = max(score_mode)
    作为稳健指标：选择能把“最差 workload 表现”也压下去的配置。

输出：
  - JSON：包含 per-mode score、worst_score、以及只保留关键统计字段的 per_mode 摘要。
  - MD：人类可读表格。
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from typing import Dict, List

from tools.step31_mutator_report import run_step31
import tools.step33_scan_recommend as s33


def recommend_worstcase(
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
    """对 scan_grid 在多 workload 下评估，并按 worst-case(max) 排名。"""

    sweep_sets, sweep_ways, sweep_index_mode = s33._load_sweep_defaults()

    rows: List[Dict] = []
    for sc in scan_grid:
        per_mode_score: Dict[str, float] = {}
        per_mode_stats: Dict[str, Dict] = {}
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
            per_mode_score[mode] = float(s)
            # 只保留关键统计，避免 baseline 因字段增减漂移
            per_mode_stats[mode] = {
                "cycle": int(r["cycle"]),
                "scan": {"stall_in": int(r["scan"]["stats"]["stall_in"])},
                "sweep": {"replace": int(r["sweep"]["stats"]["replace"])},
            }

        worst_score = max(per_mode_score.values())
        worst_mode = max(per_mode_score.items(), key=lambda kv: kv[1])[0]

        rows.append(
            {
                "worst_score": float(worst_score),
                "worst_mode": worst_mode,
                "scores": per_mode_score,
                **asdict(sc),
                "per_mode": per_mode_stats,
            }
        )

    rows.sort(key=lambda r: r["worst_score"])
    top = rows[: max(1, topn)]

    # 同时给出 per-mode Top-1（方便对比）
    per_mode_best = {}
    for m in modes:
        per_mode_best[m] = min(rows, key=lambda r: r["scores"][m])

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
    lines.append("# Step37 Worst-case Robust Scan Default Recommendation\n\n")
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
    lines.append("|mode|worst_score|score(mode)|cardset|fifo|consume|batch|cycle|stall_in|replace|\n")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n")
    for m in modes:
        r = report["per_mode_best"][m]
        lines.append(
            f"|{m}|{r['worst_score']:.2f}|{r['scores'][m]:.2f}|{r['cardset_size']}|{r['fifo_depth']}|{r['consume_every']}|{r['batch_size']}|"
            f"{r['per_mode'][m]['cycle']}|{r['per_mode'][m]['scan']['stall_in']}|{r['per_mode'][m]['sweep']['replace']}|\n"
        )

    lines.append("\n## Worst-case Robust Top-N (sorted by max(score))\n")
    lines.append(
        "|rank|worst_score|worst_mode|" + "|".join([f"score:{m}" for m in modes]) + "|cardset|fifo|consume|batch|\n"
    )
    lines.append("|---:|---:|---|" + "|".join(["---:"] * len(modes)) + "|---:|---:|---:|---:|\n")
    for i, r in enumerate(report["top"], start=1):
        scores = "|".join([f"{r['scores'][m]:.2f}" for m in modes])
        lines.append(
            f"|{i}|{r['worst_score']:.2f}|{r['worst_mode']}|{scores}|{r['cardset_size']}|{r['fifo_depth']}|{r['consume_every']}|{r['batch_size']}|\n"
        )
    return "".join(lines)


def _parse_int_list(s: str) -> List[int]:
    return [int(x) for x in s.split(",") if x.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="reports")
    ap.add_argument("--name", default="step37_scan_worstcase")

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
    rep = recommend_worstcase(
        base_cfg=base_cfg,
        scan_grid=scan_grid,
        topn=args.topn,
        modes=modes,
        global_share_p=float(args.global_share_p),
        w_cycle=float(args.w_cycle),
        w_stall=float(args.w_stall),
        w_replace=float(args.w_replace),
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
