# tools/sweep_param_sweep.py
# -*- coding: utf-8 -*-
"""Step25: Sweep 去重表参数扫描（可量化报告）

Step23/24 已把 sweep 的 dedup 表做成组相联，并加入可选 xor-fold 索引。
到 Step25，我们把这些参数“跑一遍”，输出一张表，避免拍脑袋。

输出：
  - reports/step25_sweep_table.csv
  - reports/step25_sweep_table.md

注意：
  - 这是研究基准（micro-benchmark）。
  - 主要比较趋势：replace_total 越少越好；dup_drop 越多越好。
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

from amaranth import Module, Elaboratable
from amaranth.sim import Simulator, Tick

from rtl.gc_sweep_coproc import GCSweepCoProc


@dataclass(frozen=True)
class SweepCfg:
    sets: int
    ways: int
    index_mode: int  # 0=lowbits, 1=xor-fold


def _workload_lowbit_conflict() -> Tuple[str, List[int]]:
    """低位冲突：所有 card_id 低位 idx 相同（非常容易冲突）。"""
    # 0,4,8,12... 如果 sets=4 且用 lowbits idx=card_id&3，全落在 set0。
    seq = [i * 4 for i in range(8)]  # 0..28
    return "lowbit_conflict", seq


def _workload_two_card_toggle() -> Tuple[str, List[int]]:
    """两张 card 来回写：主要观察 dup_drop 是否正确。"""
    seq = [0, 2, 0, 2, 0, 2, 0, 2]
    return "toggle_2cards", seq


class _DUT(Elaboratable):
    def __init__(self, cfg: SweepCfg):
        self.sweep = GCSweepCoProc(
            ncores=1,
            card_dedup_enable=True,
            card_table_size=cfg.sets,
            card_table_ways=cfg.ways,
            card_index_mode=cfg.index_mode,
        )

    def elaborate(self, platform):
        m = Module()
        m.submodules.sweep = self.sweep
        return m


def run_one(cfg: SweepCfg, seq: List[int], epoch: int = 0) -> dict:
    """跑一组配置 + 一段 card 序列，返回统计。"""
    dut = _DUT(cfg)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    out = {}

    def proc():
        # 入队 card 记录
        for card in seq:
            while (yield dut.sweep.card_in_ready) == 0:
                yield Tick()
            yield dut.sweep.card_in_valid.eq(1)
            yield dut.sweep.card_in_card_id.eq(card)
            yield dut.sweep.card_in_core_id.eq(0)
            yield dut.sweep.card_in_epoch.eq(epoch)
            yield Tick()
            yield dut.sweep.card_in_valid.eq(0)

        # 让 sweep 消费一段时间
        for _ in range(80):
            yield Tick()

        out["mark"] = (yield dut.sweep.mark_count_total)
        out["dup"] = (yield dut.sweep.mark_dup_drop_total)
        out["hit"] = (yield dut.sweep.mark_hit_total)
        out["miss"] = (yield dut.sweep.mark_miss_total)
        out["replace"] = (yield dut.sweep.mark_replace_total)

    sim.add_sync_process(proc)
    sim.run()
    return out


def generate_report(cfgs: List[SweepCfg], out_dir: Path) -> Tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "step25_sweep_table.csv"
    md_path = out_dir / "step25_sweep_table.md"

    workloads = [_workload_lowbit_conflict(), _workload_two_card_toggle()]

    rows = []
    for wl_name, seq in workloads:
        for cfg in cfgs:
            stats = run_one(cfg, seq)
            rows.append({
                "workload": wl_name,
                "sets": cfg.sets,
                "ways": cfg.ways,
                "index_mode": cfg.index_mode,
                **stats,
            })

    # CSV
    fields = ["workload", "sets", "ways", "index_mode", "mark", "dup", "hit", "miss", "replace"]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    # Markdown
    def fmt_row(r):
        return "| {workload} | {sets} | {ways} | {index_mode} | {mark} | {dup} | {hit} | {miss} | {replace} |".format(**r)

    header = "| workload | sets | ways | index_mode | mark | dup | hit | miss | replace |"
    sep = "|---|---:|---:|---:|---:|---:|---:|---:|---:|"

    md_lines = [
        "# Step25 Sweep 参数扫描结果（自动生成）",
        "",
        "说明：replace 越小越好；dup 越大越好。",
        "",
        header,
        sep,
    ]
    md_lines.extend(fmt_row(r) for r in rows)
    md_lines.append("")

    md_path.write_text("\n".join(md_lines), encoding="utf-8")

    return csv_path, md_path


def main():
    # 选择一组“够用且不太慢”的参数点
    cfgs = [
        SweepCfg(sets=2, ways=1, index_mode=0),
        SweepCfg(sets=2, ways=2, index_mode=0),
        SweepCfg(sets=2, ways=2, index_mode=1),
        SweepCfg(sets=4, ways=1, index_mode=0),
        SweepCfg(sets=4, ways=2, index_mode=0),
        SweepCfg(sets=4, ways=2, index_mode=1),
    ]

    csv_path, md_path = generate_report(cfgs, Path("reports"))
    print(f"OK: wrote {csv_path} and {md_path}")


if __name__ == "__main__":
    main()
