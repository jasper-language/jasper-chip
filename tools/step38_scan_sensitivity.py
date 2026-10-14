# tools/step38_scan_sensitivity.py
# -*- coding: utf-8 -*-

"""Step38：scan 参数 *跨 workload* 敏感性分析（解释性报告）。

动机：
  Step33~37 已把 scan 参数推荐闭环（含 worst-case 稳健指标）跑通并固化 baseline。
  但在做“协处理器微结构收敛/商品化取舍”时，还需要回答一个解释性问题：
    - 是 fifo 深度更关键，还是 cardset 大小更关键？
    - consume_every / batch_size 的收益是否递减？

本工具：
  1) 对固定 scan_grid，在多个 workload 下评估每个配置的 per-mode score。
  2) 计算每个配置的 worst_score=max(scores)。
  3) 按参数维度做 group-by：给出不同取值的 mean(worst_score)，并输出 delta（重要性）。

输出：
  - JSON：包含网格行、Top-N、以及 sensitivity（每个维度的均值表 + delta）。
  - MD：人类可读报告。
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from statistics import mean
from typing import Dict, List

from tools.step31_mutator_report import run_step31
import tools.step33_scan_recommend as s33


def _eval_grid(
    *,
    base_cfg: Dict,
    scan_grid: List[s33.ScanCfg],
    modes: List[str],
    global_share_p: float,
    w_cycle: float,
    w_stall: float,
    w_replace: float,
) -> List[Dict]:
    """返回每个 ScanCfg 的 per-mode 分数和 worst-case。"""

    sweep_sets, sweep_ways, sweep_index_mode = s33._load_sweep_defaults()
    rows: List[Dict] = []
    for sc in scan_grid:
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
            per_mode_score[mode] = float(s)

        worst_score = max(per_mode_score.values())
        worst_mode = max(per_mode_score.items(), key=lambda kv: kv[1])[0]

        rows.append(
            {
                **asdict(sc),
                "scores": per_mode_score,
                "worst_score": float(worst_score),
                "worst_mode": worst_mode,
            }
        )
    return rows


def _sensitivity(rows: List[Dict], key: str) -> Dict:
    """对 rows 按 key 分组，计算 mean(worst_score) 并给出 delta。"""
    buckets: Dict[int, List[float]] = {}
    for r in rows:
        v = int(r[key])
        buckets.setdefault(v, []).append(float(r["worst_score"]))
    means = {str(k): float(mean(vs)) for (k, vs) in sorted(buckets.items(), key=lambda kv: kv[0])}
    # delta: 越大表示该维度选择不当会带来越明显的 worst-case 退化
    delta = max(means.values()) - min(means.values()) if means else 0.0
    best_value = min(means.items(), key=lambda kv: kv[1])[0] if means else None
    return {"means": means, "delta": float(delta), "best": best_value}


def analyze(
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
    rows = _eval_grid(
        base_cfg=base_cfg,
        scan_grid=scan_grid,
        modes=modes,
        global_share_p=global_share_p,
        w_cycle=w_cycle,
        w_stall=w_stall,
        w_replace=w_replace,
    )
    rows.sort(key=lambda r: r["worst_score"])
    top = rows[: max(1, topn)]

    sweep_sets, sweep_ways, sweep_index_mode = s33._load_sweep_defaults()

    sens = {
        "cardset_size": _sensitivity(rows, "cardset_size"),
        "fifo_depth": _sensitivity(rows, "fifo_depth"),
        "consume_every": _sensitivity(rows, "consume_every"),
        "batch_size": _sensitivity(rows, "batch_size"),
    }

    # 给一个“维度重要性”排序（按 delta 从大到小）
    importance = sorted(
        [{"param": k, **v} for (k, v) in sens.items()],
        key=lambda x: x["delta"],
        reverse=True,
    )

    return {
        "base_cfg": dict(base_cfg),
        "workloads": {"modes": list(modes), "global_share_p": float(global_share_p)},
        "sweep_defaults": {"sets": sweep_sets, "ways": sweep_ways, "index_mode": sweep_index_mode},
        "weights": {"w_cycle": float(w_cycle), "w_stall": float(w_stall), "w_replace": float(w_replace)},
        "top": top,
        "sensitivity": sens,
        "importance": importance,
        "grid_count": int(len(rows)),
    }


def _md(report: Dict) -> str:
    b = report["base_cfg"]
    wl = report["workloads"]
    modes = wl["modes"]
    w = report["weights"]

    lines: List[str] = []
    lines.append("# Step38 Scan Sensitivity (Worst-case)\n\n")
    lines.append("## Base workload\n")
    lines.append(
        f"- seed={b['seed']} ncores={b['ncores']} epochs={b['epochs']} events/core/epoch={b['events_per_core_per_epoch']}\n"
    )
    lines.append(f"- card_space={b['card_space']} zipf_s={b['zipf_s']} phase_shift={b['phase_shift']}\n")
    lines.append("\n## Workload modes\n")
    lines.append(f"- modes={', '.join(modes)} global_share_p={wl['global_share_p']}\n")
    lines.append("\n## Score weights\n")
    lines.append(f"- w_cycle={w['w_cycle']} w_stall={w['w_stall']} w_replace={w['w_replace']}\n")

    lines.append("\n## Parameter importance (by delta of mean worst_score)\n")
    lines.append("|rank|param|delta|best|means|\n")
    lines.append("|---:|---|---:|---:|---|\n")
    for i, it in enumerate(report["importance"], start=1):
        means = ", ".join([f"{k}:{v:.1f}" for (k, v) in it["means"].items()])
        lines.append(f"|{i}|{it['param']}|{it['delta']:.1f}|{it['best']}|{means}|\n")

    lines.append("\n## Worst-case Top-N configs\n")
    lines.append("|rank|worst_score|worst_mode|cardset|fifo|consume|batch|" + "|".join([f"score:{m}" for m in modes]) + "|\n")
    lines.append("|---:|---:|---|---:|---:|---:|---:|" + "|".join(["---:"] * len(modes)) + "|\n")
    for i, r in enumerate(report["top"], start=1):
        scores = "|".join([f"{r['scores'][m]:.1f}" for m in modes])
        lines.append(
            f"|{i}|{r['worst_score']:.1f}|{r['worst_mode']}|{r['cardset_size']}|{r['fifo_depth']}|{r['consume_every']}|{r['batch_size']}|{scores}|\n"
        )

    return "".join(lines)


def _parse_int_list(s: str) -> List[int]:
    return [int(x) for x in s.split(",") if x.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="reports")
    ap.add_argument("--name", default="step38_scan_sensitivity")

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
    rep = analyze(
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
