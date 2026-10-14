# tools/step39_sweep_recommend_worstcase.py
# -*- coding: utf-8 -*-

'''Step39：把 Step31 的端到端模型用于 sweep(card) 参数的 worst-case 选择，并输出解释性敏感性。

到 Step30：
  - sweep_param_sweep_step29/30 主要基于“事件序列类 workload”，能证明 sweep 机制与参数影响。
到 Step31~38：
  - 我们有了更贴近真实 mutator 的多核写屏障压力模型（run_step31），并已把 scan 参数默认值做成
    worst-case 稳健推荐 + baseline 回归。

本工具把同一套“稳健原则”应用到 sweep 参数选择上：
  1) 固定 scan 默认值（rtl/gc_scan_params.py）。
  2) 在多个 mutator workload 上评估 sweep 配置（shared_hot_shift / per_core_partition）。
  3) 用 worst_score = max(per_mode_score) 进行排名（越小越好）。
  4) 输出 Top-K + sweep 参数敏感性（解释：哪个维度选错代价最大）。

注意：本工具不会改写 rtl/gc_params.py，只给出报告与推荐。
'''

from __future__ import annotations

import argparse
import dataclasses
import json
import os
from typing import Dict, List, Tuple

from tools.step31_mutator_report import run_step31


@dataclasses.dataclass(frozen=True)
class SweepCfg:
    sets: int
    ways: int
    index_mode: int


def _load_scan_defaults() -> Tuple[int, int, int, int]:
    """从 rtl/gc_scan_params.py 读取 scan 默认值。"""
    from rtl import gc_scan_params

    return (
        int(getattr(gc_scan_params, 'DEFAULT_SCAN_CARDSET_SIZE', gc_scan_params.SCAN_CARDSET_SIZE)),
        int(getattr(gc_scan_params, 'DEFAULT_SCAN_FIFO_DEPTH', gc_scan_params.SCAN_FIFO_DEPTH)),
        int(getattr(gc_scan_params, 'DEFAULT_SCAN_CONSUME_EVERY', gc_scan_params.SCAN_CONSUME_EVERY)),
        int(getattr(gc_scan_params, 'DEFAULT_SCAN_BATCH_SIZE', gc_scan_params.SCAN_BATCH_SIZE)),
    )


def _score(result: Dict, *, w_cycle: float, w_stall: float, w_replace: float) -> float:
    """越小越好（与 Step33 一致）。"""
    cycle = float(result.get("cycle", 0))
    stall = float(result["scan"]["stats"].get("stall_in", 0))
    replace = float(result["sweep"]["stats"].get("replace", 0))
    return w_cycle * cycle + w_stall * stall + w_replace * replace


def recommend(
    *,
    base_cfg: Dict,
    sweep_grid: List[SweepCfg],
    workload_modes: List[str],
    global_share_p: float,
    w_cycle: float,
    w_stall: float,
    w_replace: float,
    topn: int,
) -> Dict:
    scan_cardset, scan_fifo, scan_consume, scan_batch = _load_scan_defaults()

    rows: List[Dict] = []
    for scfg in sweep_grid:
        per_mode: Dict[str, Dict] = {}
        per_mode_score: Dict[str, float] = {}
        for wm in workload_modes:
            r = run_step31(
                seed=base_cfg["seed"],
                ncores=base_cfg["ncores"],
                epochs=base_cfg["epochs"],
                events_per_core_per_epoch=base_cfg["events_per_core_per_epoch"],
                card_space=base_cfg["card_space"],
                zipf_s=base_cfg["zipf_s"],
                phase_shift=base_cfg["phase_shift"],
                workload_mode=wm,
                global_share_p=float(global_share_p),
                scan_cardset_size=scan_cardset,
                scan_fifo_depth=scan_fifo,
                scan_consume_every=scan_consume,
                scan_batch_size=scan_batch,
                sweep_sets=int(scfg.sets),
                sweep_ways=int(scfg.ways),
                sweep_index_mode=int(scfg.index_mode),
            )
            s = _score(r, w_cycle=w_cycle, w_stall=w_stall, w_replace=w_replace)
            per_mode[wm] = r
            per_mode_score[wm] = float(s)

        worst_mode = max(per_mode_score, key=lambda k: per_mode_score[k])
        worst_score = float(per_mode_score[worst_mode])

        rows.append(
            {
                "sweep": dataclasses.asdict(scfg),
                "per_mode_score": per_mode_score,
                "worst_mode": worst_mode,
                "worst_score": worst_score,
                "per_mode_stats": {
                    wm: {
                        "cycle": per_mode[wm]["cycle"],
                        "stall_in": per_mode[wm]["scan"]["stats"].get("stall_in", 0),
                        "replace": per_mode[wm]["sweep"]["stats"].get("replace", 0),
                        "miss": per_mode[wm]["sweep"]["stats"].get("miss", 0),
                        "hit": per_mode[wm]["sweep"]["stats"].get("hit", 0),
                        "dup": per_mode[wm]["sweep"]["stats"].get("dup", 0),
                    }
                    for wm in workload_modes
                },
            }
        )

    rows_sorted = sorted(
        rows,
        key=lambda d: (
            d["worst_score"],
            d["sweep"]["sets"],
            d["sweep"]["ways"],
            d["sweep"]["index_mode"],
        ),
    )
    topk = rows_sorted[: max(1, int(topn))]

    sens = []
    for key in ["sets", "ways", "index_mode"]:
        bucket: Dict[int, List[float]] = {}
        for r in rows_sorted:
            v = int(r["sweep"][key])
            bucket.setdefault(v, []).append(float(r["worst_score"]))
        mean_by_v = {v: sum(xs) / max(1, len(xs)) for v, xs in bucket.items()}
        if mean_by_v:
            delta = max(mean_by_v.values()) - min(mean_by_v.values())
            best_v = min(mean_by_v, key=lambda v: mean_by_v[v])
        else:
            delta = 0.0
            best_v = None
        sens.append(
            {
                "param": key,
                "mean_worst_by_value": {str(k): float(v) for k, v in sorted(mean_by_v.items())},
                "delta": float(delta),
                "best_value": best_v,
            }
        )

    sens_sorted = sorted(sens, key=lambda d: d["delta"], reverse=True)

    return {
        "base_cfg": dict(base_cfg),
        "scan_defaults": {
            "cardset_size": scan_cardset,
            "fifo_depth": scan_fifo,
            "consume_every": scan_consume,
            "batch_size": scan_batch,
        },
        "workload_modes": list(workload_modes),
        "global_share_p": float(global_share_p),
        "weights": {"w_cycle": w_cycle, "w_stall": w_stall, "w_replace": w_replace},
        "grid_size": len(sweep_grid),
        "topk": topk,
        "sensitivity": sens_sorted,
    }


def _md_report(d: Dict) -> str:
    b = d["base_cfg"]
    sdef = d["scan_defaults"]
    lines: List[str] = []
    lines.append("# Step39 Sweep Worst-case Recommendation (mutator model)\n")
    lines.append("## Base config\n")
    lines.append(
        f"- seed={b['seed']} ncores={b['ncores']} epochs={b['epochs']} events/core/epoch={b['events_per_core_per_epoch']}\n"
    )
    lines.append(f"- card_space={b['card_space']} zipf_s={b['zipf_s']} phase_shift={b['phase_shift']}\n")
    lines.append(f"- workload_modes={', '.join(d['workload_modes'])}  global_share_p={d['global_share_p']}\n")
    lines.append("\n## Fixed scan defaults\n")
    lines.append(
        f"- cardset={sdef['cardset_size']} fifo={sdef['fifo_depth']} consume={sdef['consume_every']} batch={sdef['batch_size']}\n"
    )
    w = d["weights"]
    lines.append("\n## Score weights (lower is better)\n")
    lines.append(
        f"- score = {w['w_cycle']}*cycle + {w['w_stall']}*stall_in + {w['w_replace']}*sweep.replace\n"
    )

    lines.append("\n## Global Top-K (worst-case=max across workloads)\n")
    for i, r in enumerate(d["topk"], 1):
        sw = r["sweep"]
        lines.append(f"### #{i}: sets={sw['sets']} ways={sw['ways']} index_mode={sw['index_mode']}\n")
        lines.append(f"- worst_score={r['worst_score']:.2f}  worst_mode={r['worst_mode']}\n")
        for wm, sc in r["per_mode_score"].items():
            st = r["per_mode_stats"][wm]
            lines.append(
                f"  - {wm}: score={sc:.2f}  cycle={st['cycle']} stall_in={st['stall_in']} replace={st['replace']} miss={st['miss']} hit={st['hit']} dup={st['dup']}\n"
            )
        lines.append("")

    lines.append("\n## Sensitivity (by mean worst_score)\n")
    for s in d["sensitivity"]:
        lines.append(
            f"- **{s['param']}**: delta={s['delta']:.2f}, best={s['best_value']}, mean_worst_by_value={s['mean_worst_by_value']}\n"
        )

    lines.append("")
    return "\n".join(lines)


def _parse_int_list(s: str) -> List[int]:
    return [int(x.strip()) for x in s.split(",") if x.strip()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="reports")
    ap.add_argument("--name", default="step39_sweep_worstcase")
    ap.add_argument("--seed", type=int, default=20260103)
    ap.add_argument("--ncores", type=int, default=4)
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--events-per-core-per-epoch", type=int, default=64)
    ap.add_argument("--card-space", type=int, default=64)
    ap.add_argument("--zipf-s", type=float, default=1.07)
    ap.add_argument("--phase-shift", type=int, default=7)

    ap.add_argument("--sets", default="4,8,16,32")
    ap.add_argument("--ways", default="1,2,4")
    ap.add_argument("--index", default="0,1,2")
    ap.add_argument("--workloads", default="shared_hot_shift,per_core_partition")
    ap.add_argument("--global-share-p", type=float, default=0.10)

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

    sets_list = _parse_int_list(args.sets)
    ways_list = _parse_int_list(args.ways)
    idx_list = _parse_int_list(args.index)
    workload_modes = [x.strip() for x in args.workloads.split(",") if x.strip()]

    grid: List[SweepCfg] = []
    for s in sets_list:
        for wv in ways_list:
            for idx in idx_list:
                grid.append(SweepCfg(sets=s, ways=wv, index_mode=idx))

    report = recommend(
        base_cfg=base_cfg,
        sweep_grid=grid,
        workload_modes=workload_modes,
        global_share_p=float(args.global_share_p),
        w_cycle=float(args.w_cycle),
        w_stall=float(args.w_stall),
        w_replace=float(args.w_replace),
        topn=int(args.topn),
    )

    os.makedirs(args.outdir, exist_ok=True)
    jpath = os.path.join(args.outdir, f"{args.name}.json")
    mpath = os.path.join(args.outdir, f"{args.name}.md")
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    with open(mpath, "w", encoding="utf-8") as f:
        f.write(_md_report(report))

    print(f"OK: wrote {jpath} and {mpath}")


if __name__ == "__main__":
    main()
