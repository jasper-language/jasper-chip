# tools/sweep_param_sweep_step27.py
# -*- coding: utf-8 -*-
"""Step27: 批量扫参 + Zipf 分布 workload + 自动 Top-N 汇总

Step26 已经能批量扫描 sets×ways×index_mode，并加入多核 workload。
Step27 在此基础上补上两件“做研究必须要有”的能力：

1) Zipf 热点分布 workload
   - 真实系统里写屏障/card 访问通常呈现强热点（Zipf/长尾）。
   - 仅用 lowbit_conflict/toggle 这类构造序列，会把结论过度偏向某一类冲突模式。

2) Top-N 自动汇总视图
   - 生成 CSV/MD 明细表仍保留。
   - 另外在 Markdown 顶部生成 Top-N（按 replace 最小、dup 最大排序）
     无需肉眼翻表即可看出“该选什么参数”。

输出：
  - reports/step27_sweep_table.csv
  - reports/step27_sweep_table.md（含 Top-N 汇总 + 全表）
"""

from __future__ import annotations

import argparse
import csv
import random
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple, Sequence, Union, Dict

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
    return "lowbit_conflict", [i * 4 for i in range(12)]


def wl_toggle_2cards() -> Tuple[str, List[CardEvent]]:
    return "toggle_2cards", [0, 2, 0, 2, 0, 2, 0, 2]


def wl_multicore_hot0(ncores: int = 4) -> Tuple[str, List[CardEvent]]:
    seq: List[CardEvent] = []
    hot = [i * 4 for i in range(24)]
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
    seq: List[CardEvent] = []
    for r in range(12):
        for c in range(ncores):
            seq.append((c, c * 16 + r))
    return "multicore_uniform", seq


def _zipf_weights(n_items: int, s: float) -> List[float]:
    # 权重：1 / k^s，k 从 1 开始
    return [1.0 / ((k + 1) ** s) for k in range(n_items)]


def wl_zipf_single(*, n_items: int = 64, n_events: int = 128, s: float = 1.2, seed: int = 0) -> Tuple[str, List[CardEvent]]:
    """单核 Zipf：card_id 范围 [0, n_items)，事件数 n_events。"""
    rng = random.Random(seed)
    w = _zipf_weights(n_items, s)
    cards = rng.choices(list(range(n_items)), weights=w, k=n_events)
    return f"zipf_single_s{str(s).replace('.','p')}", cards


def wl_zipf_multicore(*, ncores: int = 4, n_items: int = 128, n_events_per_core: int = 64, s: float = 1.2, seed: int = 1) -> Tuple[str, List[CardEvent]]:
    """多核 Zipf：每核独立 Zipf 采样，然后按轮询交织（更像并发写入）。"""
    w = _zipf_weights(n_items, s)
    per: List[List[int]] = []
    for c in range(ncores):
        rng = random.Random(seed + 97 * c)
        per.append(rng.choices(list(range(n_items)), weights=w, k=n_events_per_core))

    seq: List[CardEvent] = []
    for i in range(n_events_per_core):
        for c in range(ncores):
            seq.append((c, per[c][i]))
    return f"zipf_mc_s{str(s).replace('.','p')}", seq


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


def run_one(cfg: SweepCfg, seq: Sequence[CardEvent], *, ncores: int, epoch: int = 0) -> Dict[str, int]:
    dut = _DUT(cfg, ncores=ncores)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    out: Dict[str, int] = {}

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

        for _ in range(300):
            yield Tick()

        out['mark'] = (yield dut.sweep.mark_count_total)
        out['dup'] = (yield dut.sweep.mark_dup_drop_total)
        out['hit'] = (yield dut.sweep.mark_hit_total)
        out['miss'] = (yield dut.sweep.mark_miss_total)
        out['replace'] = (yield dut.sweep.mark_replace_total)
        for i in range(4):
            out[f'core{i}_mark'] = (yield dut.sweep.mark_count_core[i]) if i < ncores else 0

    sim.add_sync_process(proc)
    sim.run()
    return out


def _expand_cfgs(sets_list: List[int], ways_list: List[int], idx_list: List[int]) -> List[SweepCfg]:
    return [SweepCfg(s, w, im) for s in sets_list for w in ways_list for im in idx_list]


def _sort_key(r: dict) -> tuple:
    # replace 越小越好，dup 越大越好；其次 prefer larger hit
    return (r['replace'], -r['dup'], -r['hit'], r['miss'])


def _topn_by_workload(rows: List[dict], topn: int) -> Dict[str, List[dict]]:
    by: Dict[str, List[dict]] = {}
    for r in rows:
        by.setdefault(r['workload'], []).append(r)
    for k in by:
        by[k].sort(key=_sort_key)
        by[k] = by[k][:topn]
    return by


def generate_report(
    *,
    out_dir: Path,
    base: str,
    sets_list: List[int],
    ways_list: List[int],
    idx_list: List[int],
    include_multicore: bool,
    include_zipf: bool,
    ncores: int,
    topn: int,
    zipf_s: float,
    zipf_single_events: int = 160,
    zipf_mc_events_per_core: int = 48,
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"{base}.csv"
    md_path = out_dir / f"{base}.md"

    cfgs = _expand_cfgs(sets_list, ways_list, idx_list)

    workloads: List[Tuple[str, List[CardEvent], int]] = [
        (*wl_lowbit_conflict(), 1),
        (*wl_toggle_2cards(), 1),
    ]
    if include_multicore:
        workloads.extend([
            (*wl_multicore_hot0(ncores=ncores), ncores),
            (*wl_multicore_uniform(ncores=ncores), ncores),
        ])
    if include_zipf:
        workloads.extend([
            (*wl_zipf_single(n_items=64, n_events=zipf_single_events, s=zipf_s, seed=3), 1),
            (*wl_zipf_multicore(ncores=ncores, n_items=128, n_events_per_core=zipf_mc_events_per_core, s=zipf_s, seed=5), ncores),
        ])

    rows: List[dict] = []
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
    with csv_path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    header = "| workload | ncores | sets | ways | idx | mark | dup | hit | miss | repl | c0 | c1 | c2 | c3 |"
    sep = "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
    def fmt(r: dict) -> str:
        return (
            f"| {r['workload']} | {r['ncores']} | {r['sets']} | {r['ways']} | {r['index_mode']} | "
            f"{r['mark']} | {r['dup']} | {r['hit']} | {r['miss']} | {r['replace']} | "
            f"{r['core0_mark']} | {r['core1_mark']} | {r['core2_mark']} | {r['core3_mark']} |"
        )

    top = _topn_by_workload(rows, topn=topn)
    md_lines: List[str] = [
        '# Step27 Sweep 参数扫描结果（自动生成）',
        '',
        'Top-N 说明：按 (replace 升序, dup 降序, hit 降序, miss 升序) 排序。',
        '',
        '## Top-N 推荐参数（每个 workload）',
        '',
    ]

    for wl, trs in top.items():
        md_lines.append(f"### {wl}")
        md_lines.append('')
        md_lines.append('| rank | sets | ways | idx | mark | dup | repl | hit | miss |')
        md_lines.append('|---:|---:|---:|---:|---:|---:|---:|---:|---:|')
        for i, r in enumerate(trs, start=1):
            md_lines.append(
                f"| {i} | {r['sets']} | {r['ways']} | {r['index_mode']} | {r['mark']} | {r['dup']} | {r['replace']} | {r['hit']} | {r['miss']} |"
            )
        md_lines.append('')

    md_lines.extend([
        '## 明细全表',
        '',
        '说明：replace 越小越好（替换抖动少）；dup 越大越好（同 epoch 去重有效）。',
        '',
        header,
        sep,
    ])
    md_lines.extend(fmt(r) for r in rows)
    md_lines.append('')
    md_path.write_text('\n'.join(md_lines), encoding='utf-8')
    return csv_path, md_path


def main():
    ap = argparse.ArgumentParser(description='Step27 sweep dedup 批量扫参 + Zipf + TopN')
    ap.add_argument('--out', default='reports', help='输出目录')
    ap.add_argument('--base', default='step27_sweep_table', help='输出文件 base（不含扩展名）')
    ap.add_argument('--sets', default='2,4,8', help='sets 列表，逗号分隔')
    ap.add_argument('--ways', default='1,2,4', help='ways 列表，逗号分隔')
    ap.add_argument('--index', default='0,1', help='index_mode 列表：0=lowbits,1=xor-fold')
    ap.add_argument('--no-multicore', action='store_true', help='不包含多核 workload')
    ap.add_argument('--no-zipf', action='store_true', help='不包含 Zipf workload')
    ap.add_argument('--ncores', type=int, default=4, help='多核 workload 的核数')
    ap.add_argument('--topn', type=int, default=3, help='Top-N 汇总个数')
    ap.add_argument('--zipf-s', type=float, default=1.2, help='Zipf 参数 s（越大越热点）')
    ap.add_argument('--zipf-single-events', type=int, default=160, help='Zipf 单核事件数（默认 160）')
    ap.add_argument('--zipf-mc-events-per-core', type=int, default=48, help='Zipf 多核：每核事件数（默认 48）')
    args = ap.parse_args()

    sets_list = [int(x) for x in args.sets.split(',') if x.strip()]
    ways_list = [int(x) for x in args.ways.split(',') if x.strip()]
    idx_list = [int(x) for x in args.index.split(',') if x.strip()]

    csv_path, md_path = generate_report(
        out_dir=Path(args.out),
        base=args.base,
        sets_list=sets_list,
        ways_list=ways_list,
        idx_list=idx_list,
        include_multicore=not args.no_multicore,
        include_zipf=not args.no_zipf,
        ncores=args.ncores,
        topn=args.topn,
        zipf_s=args.zipf_s,
        zipf_single_events=args.zipf_single_events,
        zipf_mc_events_per_core=args.zipf_mc_events_per_core,
    )
    print(f'OK: wrote {csv_path} and {md_path}')


if __name__ == '__main__':
    main()
