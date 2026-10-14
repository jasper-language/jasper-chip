# tools/step33_scan_recommend.py
# -*- coding: utf-8 -*-

"""Step33：基于 Step31 mutator→scan→sweep 研究模型，自动推荐 scan 参数默认值。

到 Step32 为止：
  - sweep(card) 去重表参数已固化默认（rtl/gc_params.py），并由 Step30 baseline 回归保护。
  - scan 侧（card 去重集合 + FIFO + 共享引擎 consume_every/batch_size）仍以手调为主。

本工具：
  1) 固定 sweep 默认参数（来自 rtl/gc_params.py）。
  2) 固定一个可复现的 mutator workload（复用 tools.step31_mutator_report.run_step31）。
  3) 扫描一小片 scan 参数空间，给出 Top-N 推荐。
  4) 可选：把 Top-1 写入 rtl/gc_scan_params.py，供 TopSoC 默认使用。

注意：
  - 这是研究用“趋势模型推荐”，不是 RTL 正确性证明。
  - 目标是给出一个稳定的默认值，并用测试锁死，避免后续漂移。

用法：
  python -m tools.step33_scan_recommend --outdir reports --name step33_scan_reco --write-defaults
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, asdict
from typing import Dict, List, Tuple

from tools.step31_mutator_report import run_step31


def _load_sweep_defaults() -> Tuple[int, int, int]:
    # sweep 默认值写在 rtl/gc_params.py
    from rtl import gc_params

    return (
        int(gc_params.DEFAULT_SWEEP_CARD_TABLE_SIZE),
        int(gc_params.DEFAULT_SWEEP_CARD_TABLE_WAYS),
        int(gc_params.DEFAULT_SWEEP_CARD_INDEX_MODE),
    )


@dataclass(frozen=True)
class ScanCfg:
    cardset_size: int
    fifo_depth: int
    consume_every: int
    batch_size: int


def _score(result: Dict, *, w_cycle: float, w_stall: float, w_replace: float) -> float:
    """越小越好。

    - cycle：总周期，直接反映 scan 带宽和 backpressure
    - stall_in：写屏障输入被挡住的次数（越小越好）
    - sweep.replace：sweep 去重表替换次数（越小越好，表示 sweep 侧冲突/容量压力）

    这三者是 scan 默认参数最直接的工程目标。
    """
    cycle = float(result.get("cycle", 0))
    stall = float(result["scan"]["stats"].get("stall_in", 0))
    replace = float(result["sweep"]["stats"].get("replace", 0))
    return w_cycle * cycle + w_stall * stall + w_replace * replace


def recommend(
    *,
    base_cfg: Dict,
    scan_grid: List[ScanCfg],
    topn: int,
    w_cycle: float,
    w_stall: float,
    w_replace: float,
    workload_mode: str = "shared_hot_shift",
    global_share_p: float = 0.10,
) -> Dict:
    sweep_sets, sweep_ways, sweep_index_mode = _load_sweep_defaults()

    scored: List[Tuple[float, ScanCfg, Dict]] = []
    for sc in scan_grid:
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
            workload_mode=workload_mode,
            global_share_p=global_share_p,
        )
        s = _score(r, w_cycle=w_cycle, w_stall=w_stall, w_replace=w_replace)
        scored.append((s, sc, r))

    scored.sort(key=lambda x: x[0])
    top = scored[: max(1, topn)]

    def _row(s: float, sc: ScanCfg, r: Dict) -> Dict:
        return {
            "score": s,
            **asdict(sc),
            "cycle": r["cycle"],
            "scan": r["scan"]["stats"],
            "sweep": r["sweep"]["stats"],
        }

    out = {
        "base_cfg": dict(base_cfg),
        "sweep_defaults": {
            "sets": sweep_sets,
            "ways": sweep_ways,
            "index_mode": sweep_index_mode,
        },
        "weights": {"w_cycle": w_cycle, "w_stall": w_stall, "w_replace": w_replace},
        "top": [_row(s, sc, r) for (s, sc, r) in top],
    }
    return out


def _write_gc_scan_params(best: Dict, path: str):
    """把 Top-1 推荐写到 rtl/gc_scan_params.py。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("# rtl/gc_scan_params.py\n")
        f.write("# -*- coding: utf-8 -*-\n\n")
        f.write("\"\"\"Step33 自动推荐的 scan 默认参数（研究用）。\n\n")
        f.write("来源：tools/step33_scan_recommend.py 输出的 Top-1。\n")
        f.write("注意：这是趋势模型推荐，不等于 RTL 级最优。\n\"\"\"\n\n")
        f.write(f"SCAN_CARDSET_SIZE = {int(best['cardset_size'])}\n")
        f.write(f"SCAN_FIFO_DEPTH   = {int(best['fifo_depth'])}\n")
        f.write(f"SCAN_CONSUME_EVERY = {int(best['consume_every'])}\n")
        f.write(f"SCAN_BATCH_SIZE    = {int(best['batch_size'])}\n")


def _md(report: Dict) -> str:
    b = report["base_cfg"]
    sw = report["sweep_defaults"]
    w = report["weights"]
    lines = []
    lines.append("# Step33 Scan Default Recommendation\n\n")
    lines.append("## Base workload\n")
    lines.append(
        f"- seed={b['seed']} ncores={b['ncores']} epochs={b['epochs']} events/core/epoch={b['events_per_core_per_epoch']}\n"
    )
    lines.append(
        f"- card_space={b['card_space']} zipf_s={b['zipf_s']} phase_shift={b['phase_shift']}\n"
    )
    lines.append("\n## Sweep defaults\n")
    lines.append(f"- sets={sw['sets']} ways={sw['ways']} index_mode={sw['index_mode']}\n")
    lines.append("\n## Score weights\n")
    lines.append(f"- w_cycle={w['w_cycle']} w_stall={w['w_stall']} w_replace={w['w_replace']}\n")
    lines.append("\n## Top-N\n")
    lines.append("|rank|score|cardset|fifo|consume_every|batch|cycle|stall_in|sweep_replace|\n")
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n")
    for i, row in enumerate(report["top"], start=1):
        lines.append(
            f"|{i}|{row['score']:.2f}|{row['cardset_size']}|{row['fifo_depth']}|{row['consume_every']}|{row['batch_size']}|{row['cycle']}|{row['scan']['stall_in']}|{row['sweep']['replace']}|\n"
        )
    return "".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="reports")
    ap.add_argument("--name", default="step33_scan_reco")

    # base workload (keep small by default; tests can shrink further)
    ap.add_argument("--seed", type=int, default=20260102)
    ap.add_argument("--ncores", type=int, default=4)
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--events-per-core-per-epoch", type=int, default=64)
    ap.add_argument("--card-space", type=int, default=64)
    ap.add_argument("--zipf-s", type=float, default=1.07)
    ap.add_argument("--phase-shift", type=int, default=7)

    # scan grid
    ap.add_argument("--cardset", default="8,16")
    ap.add_argument("--fifo", default="1,2,4")
    ap.add_argument("--consume", default="2,4,8")
    ap.add_argument("--batch", default="1,2,4")

    ap.add_argument("--topn", type=int, default=10)
    ap.add_argument("--w-cycle", type=float, default=1.0)
    ap.add_argument("--w-stall", type=float, default=8.0)
    ap.add_argument("--w-replace", type=float, default=4.0)

    ap.add_argument("--write-defaults", action="store_true")

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

    def _parse_int_list(s: str) -> List[int]:
        return [int(x.strip()) for x in s.split(",") if x.strip()]

    cardset_list = _parse_int_list(args.cardset)
    fifo_list = _parse_int_list(args.fifo)
    consume_list = _parse_int_list(args.consume)
    batch_list = _parse_int_list(args.batch)

    grid: List[ScanCfg] = []
    for cs in cardset_list:
        for fd in fifo_list:
            for ce in consume_list:
                for bs in batch_list:
                    grid.append(ScanCfg(cardset_size=cs, fifo_depth=fd, consume_every=ce, batch_size=bs))

    report = recommend(
        base_cfg=base_cfg,
        scan_grid=grid,
        topn=args.topn,
        w_cycle=args.w_cycle,
        w_stall=args.w_stall,
        w_replace=args.w_replace,
    )

    os.makedirs(args.outdir, exist_ok=True)
    json_path = os.path.join(args.outdir, f"{args.name}.json")
    md_path = os.path.join(args.outdir, f"{args.name}.md")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(_md(report))

    if args.write_defaults:
        best = report["top"][0]
        _write_gc_scan_params(best, os.path.join("rtl", "gc_scan_params.py"))

    print(f"OK: wrote {json_path} and {md_path}")
    if args.write_defaults:
        print("OK: updated rtl/gc_scan_params.py")


if __name__ == "__main__":
    main()
