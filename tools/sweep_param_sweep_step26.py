# tools/sweep_param_sweep_step26.py
# -*- coding: utf-8 -*-
"""Step26: 批量扫参 + 多核 workload 的 sweep dedup 评估脚本

Step25 的 tools/sweep_param_sweep.py 是“少量参数点”的示范。
Step26 在不破坏 Step25 测试的前提下，新增一个更完整的扫参工具：

- sets × ways × index_mode 全组合（可通过 CLI 控制）
- 增加多核 card 分布 workload（interleave 输入，验证统计/替换抖动）

输出：
  - reports/step26_sweep_table.csv
  - reports/step26_sweep_table.md

说明：
  - replace 越少越好（代表替换抖动少）
  - dup 越多越好（代表同 epoch 内去重更有效）
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple, Sequence, Union

from amaranth import Module, Elaboratable
from amaranth.sim import Simulator, Tick

from rtl.gc_sweep_coproc import GCSweepCoProc


@dataclass(frozen=True)
class SweepCfg:
    sets: int
    ways: int
    index_mode: int  # 0=lowbits, 1=xor-fold


CardEvent = Union[int, Tuple[int, int]]  # card_id or (core_id, card_id)


def wl_lowbit_conflict() -> Tuple[str, List[CardEvent]]:
    """低位冲突：0,4,8,12...（容易全部落在同 set）。"""
    return "lowbit_conflict", [i * 4 for i in range(12)]


def wl_toggle_2cards() -> Tuple[str, List[CardEvent]]:
    """两张 card 来回写：主要观察 dup_drop。"""
    return "toggle_2cards", [0, 2, 0, 2, 0, 2, 0, 2]


def wl_multicore_hot0(ncores: int = 4) -> Tuple[str, List[CardEvent]]:
    """多核分布：core0 热点 + 其他核少量事件（验证不会丢 core_id）。"""
    seq: List[CardEvent] = []
    hot = [i * 4 for i in range(24)]  # 0..92
    others: List[CardEvent] = []
    for c in range(1, ncores):
        others += [(c, 1 + 2 * c), (c, 3 + 2 * c)]
    oi = 0
    for i, card in enumerate(hot):
        seq.append((0, card))
        if i % 3 == 2 and oi < len(others):
            seq.append(others[oi]); oi += 1
    while oi < len(others):
        seq.append(others[oi]); oi += 1
    return "multicore_hot0", seq


def wl_multicore_uniform(ncores: int = 4) -> Tuple[str, List[CardEvent]]:
    """多核均匀：各核轮流写不同 card。"""
    seq: List[CardEvent] = []
    for r in range(12):
        for c in range(ncores):
            seq.append((c, c * 16 + r))
    return "multicore_uniform", seq



class _DUT(Elaboratable):
    def __init__(self, cfg: SweepCfg, ncores: int):
        self.sweep = GCSweepCoProc(
            ncores=ncores,
            card_dedup_enable=True,
            card_table_size=cfg.sets,
            card_table_ways=cfg.ways,
            card_index_mode=cfg.index_mode,
        )

    def elaborate(self, platform):
        m = Module()
        m.submodules.sweep = self.sweep
        return m


def run_one(cfg: SweepCfg, seq: Sequence[CardEvent], *, ncores: int, epoch: int = 0) -> dict:
    """跑一组配置 + 一个 workload，返回统计数据。"""
    dut = _DUT(cfg, ncores=ncores)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    out: dict = {}

    def proc():
        for ev in seq:
            if isinstance(ev, tuple):
                core, card = ev
            else:
                core, card = 0, int(ev)

            while (yield dut.sweep.card_in_ready) == 0:
                yield Tick()
            yield dut.sweep.card_in_valid.eq(1)
            yield dut.sweep.card_in_card_id.eq(card)
            yield dut.sweep.card_in_core_id.eq(core)
            yield dut.sweep.card_in_epoch.eq(epoch)
            yield Tick()
            yield dut.sweep.card_in_valid.eq(0)

        # 消费一段时间，确保输入都被处理
        for _ in range(240):
            yield Tick()

        out['mark'] = (yield dut.sweep.mark_count_total)
        out['dup'] = (yield dut.sweep.mark_dup_drop_total)
        out['hit'] = (yield dut.sweep.mark_hit_total)
        out['miss'] = (yield dut.sweep.mark_miss_total)
        out['replace'] = (yield dut.sweep.mark_replace_total)

        # 固定输出 4 核统计，便于表格统一（ncores<4 则补 0）
        for i in range(4):
            if i < ncores:
                out[f'core{i}_mark'] = (yield dut.sweep.mark_count_core[i])
            else:
                out[f'core{i}_mark'] = 0

    sim.add_sync_process(proc)
    sim.run()
    return out


def _expand_cfgs(sets_list: List[int], ways_list: List[int], index_modes: List[int]) -> List[SweepCfg]:
    cfgs: List[SweepCfg] = []
    for s in sets_list:
        for w in ways_list:
            for im in index_modes:
                cfgs.append(SweepCfg(sets=s, ways=w, index_mode=im))
    return cfgs


def generate_report(
    *,
    out_dir: Path,
    base: str,
    sets_list: List[int],
    ways_list: List[int],
    index_modes: List[int],
    include_multicore: bool,
    ncores: int,
) -> tuple[Path, Path]:
    """生成 step26 CSV + Markdown 报告。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"{base}.csv"
    md_path = out_dir / f"{base}.md"

    cfgs = _expand_cfgs(sets_list, ways_list, index_modes)

    workloads: List[Tuple[str, List[CardEvent], int]] = [
        (*wl_lowbit_conflict(), 1),
        (*wl_toggle_2cards(), 1),
    ]
    if include_multicore:
        workloads.extend([
            (*wl_multicore_hot0(ncores=ncores), ncores),
            (*wl_multicore_uniform(ncores=ncores), ncores),
        ])

    rows = []
    for wl_name, seq, wl_ncores in workloads:
        for cfg in cfgs:
            stats = run_one(cfg, seq, ncores=wl_ncores)
            rows.append({
                'workload': wl_name,
                'ncores': wl_ncores,
                'sets': cfg.sets,
                'ways': cfg.ways,
                'index_mode': cfg.index_mode,
                **stats,
            })

    fields = [
        'workload','ncores','sets','ways','index_mode',
        'mark','dup','hit','miss','replace',
        'core0_mark','core1_mark','core2_mark','core3_mark'
    ]

    import csv
    with csv_path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    header = "| workload | ncores | sets | ways | idx | mark | dup | hit | miss | repl | c0 | c1 | c2 | c3 |"
    sep = "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"

    def fmt(r):
        return (
            f"| {r['workload']} | {r['ncores']} | {r['sets']} | {r['ways']} | {r['index_mode']} | "
            f"{r['mark']} | {r['dup']} | {r['hit']} | {r['miss']} | {r['replace']} | "
            f"{r['core0_mark']} | {r['core1_mark']} | {r['core2_mark']} | {r['core3_mark']} |"
        )

    md_lines = [
        '# Step26 Sweep 参数扫描结果（自动生成）',
        '',
        '说明：replace 越小越好；dup 越大越好。多核 workload 会输出每核 mark 计数。',
        '',
        header,
        sep,
    ]
    md_lines.extend(fmt(r) for r in rows)
    md_lines.append('')

    md_path.write_text('\n'.join(md_lines), encoding='utf-8')

    return csv_path, md_path


def _expand_cfgs(sets_list: List[int], ways_list: List[int], idx_list: List[int]) -> List[SweepCfg]:
    cfgs: List[SweepCfg] = []
    for s in sets_list:
        for w in ways_list:
            for im in idx_list:
                cfgs.append(SweepCfg(sets=s, ways=w, index_mode=im))
    return cfgs


def main():
    ap = argparse.ArgumentParser(description='Step26 sweep dedup 参数批量扫描')
    ap.add_argument('--out', default='reports', help='输出目录')
    ap.add_argument('--base', default='step26_sweep_table', help='输出文件 base（不含扩展名）')
    ap.add_argument('--sets', default='2,4,8', help='sets 列表，逗号分隔')
    ap.add_argument('--ways', default='1,2,4', help='ways 列表，逗号分隔')
    ap.add_argument('--index', default='0,1', help='index_mode 列表：0=lowbits,1=xor-fold')
    ap.add_argument('--no-multicore', action='store_true', help='不包含多核 workload')
    ap.add_argument('--ncores', type=int, default=4, help='多核 workload 的核数')
    args = ap.parse_args()

    sets_list = [int(x) for x in args.sets.split(',') if x.strip()]
    ways_list = [int(x) for x in args.ways.split(',') if x.strip()]
    idx_list = [int(x) for x in args.index.split(',') if x.strip()]

    csv_path, md_path = generate_report(
        out_dir=Path(args.out),
        base=args.base,
        sets_list=sets_list,
        ways_list=ways_list,
        index_modes=idx_list,
        include_multicore=not args.no_multicore,
        ncores=args.ncores,
    )
    print(f'OK: wrote {csv_path} and {md_path}')


if __name__ == '__main__':
    main()
