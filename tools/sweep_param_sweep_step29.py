# tools/sweep_param_sweep_step29.py
# -*- coding: utf-8 -*-
"""Step29: 批量扫参 + Zipf workload + 全局 Top-K（按 workload 归一化 + 加权）

Step28 的“全局 Top-K”做法是：把所有 workload 的指标直接求和再算 score。
这在工程上有个明显问题：事件数更大的 workload（例如 zipf_mc）会天然主导总和，
导致“全局最优配置”过度迎合某一个 workload。

Step29 的改进：

1) 每个 workload 内先做 min-max 归一化（replace/miss/dup/hit 各自归一化到 [0,1]）
   x_norm = (x - min_x) / (max_x - min_x + eps)
2) 全局 score 为各 workload 的“归一化 score”加权求和：
   score = Σ wl_weight * ( w_replace*replace_norm + w_miss*miss_norm - w_dup*dup_norm - w_hit*hit_norm )
3) 报告中输出每个 workload 的归一化范围（min/max），便于理解尺度。

输出：
  - reports/step29_sweep_table.csv
  - reports/step29_sweep_table.md（含 全局 Top-K（normalized） + ranges + 每 workload Top-N + 全表）
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
    return [1.0 / ((k + 1) ** s) for k in range(n_items)]


def wl_zipf_single(*, n_items: int = 64, n_events: int = 128, s: float = 1.2, seed: int = 0) -> Tuple[str, List[CardEvent]]:
    rng = random.Random(seed)
    w = _zipf_weights(n_items, s)
    cards = rng.choices(list(range(n_items)), weights=w, k=n_events)
    return f"zipf_single_s{str(s).replace('.','p')}", cards


def wl_zipf_multicore(*, ncores: int = 4, n_items: int = 128, n_events_per_core: int = 64, s: float = 1.2, seed: int = 1) -> Tuple[str, List[CardEvent]]:
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


def generate_rows(
    *,
    sets_list: List[int],
    ways_list: List[int],
    idx_list: List[int],
    include_multicore: bool,
    include_zipf: bool,
    ncores: int,
    zipf_s: float,
    zipf_single_events: int,
    zipf_mc_events_per_core: int,
) -> List[dict]:
    """生成 rows（不写文件），便于 Step30 做 baseline 回归。

    每一行对应一个 (workload,cfg) 的统计：mark/dup/hit/miss/replace + per-core mark。
    """
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
    return rows


def _expand_cfgs(sets_list: List[int], ways_list: List[int], idx_list: List[int]) -> List[SweepCfg]:
    return [SweepCfg(s, w, im) for s in sets_list for w in ways_list for im in idx_list]


def _sort_key(r: dict) -> tuple:
    return (r['replace'], -r['dup'], -r['hit'], r['miss'])


def _topn_by_workload(rows: List[dict], topn: int) -> Dict[str, List[dict]]:
    by: Dict[str, List[dict]] = {}
    for r in rows:
        by.setdefault(r['workload'], []).append(r)
    for k in by:
        by[k].sort(key=_sort_key)
        by[k] = by[k][:topn]
    return by


def _cfg_key(r: dict) -> tuple[int, int, int]:
    return (int(r['sets']), int(r['ways']), int(r['index_mode']))


def compute_global_topk_normalized(
    rows: List[dict],
    *,
    topk: int,
    metric_weights: Dict[str, float],
    workload_weights: Dict[str, float] | None = None,
    eps: float = 1e-9,
) -> tuple[List[dict], Dict[str, Dict[str, tuple[float, float]]]]:
    """按 workload 归一化后得到全局 Top-K。

    返回：
      - global_top: 每个配置的聚合结果（含 score_norm）
      - ranges: workload -> metric -> (min,max)
    """
    workload_weights = workload_weights or {}

    # 1) 归一化范围：对每个 workload，统计 replace/miss/dup/hit 在不同 cfg 之间的 min/max
    metrics = ['replace', 'miss', 'dup', 'hit']
    ranges: Dict[str, Dict[str, tuple[float, float]]] = {}
    by_wl: Dict[str, List[dict]] = {}
    for r in rows:
        by_wl.setdefault(r['workload'], []).append(r)

    for wl, rs in by_wl.items():
        ranges[wl] = {}
        for m in metrics:
            xs = [float(rr[m]) for rr in rs]
            ranges[wl][m] = (min(xs), max(xs))

    # 2) 聚合：对每个 cfg，累积各 workload 的“归一化得分”
    agg: Dict[tuple[int, int, int], dict] = {}
    for r in rows:
        cfg = _cfg_key(r)
        wl = r['workload']
        w_wl = float(workload_weights.get(wl, 1.0))

        # 归一化
        def norm(metric: str) -> float:
            mn, mx = ranges[wl][metric]
            return (float(r[metric]) - mn) / (mx - mn + eps)

        term = (
            metric_weights['replace'] * norm('replace')
            + metric_weights['miss'] * norm('miss')
            - metric_weights['dup'] * norm('dup')
            - metric_weights['hit'] * norm('hit')
        )
        term *= w_wl

        a = agg.setdefault(cfg, {
            'sets': cfg[0], 'ways': cfg[1], 'index_mode': cfg[2],
            'workloads': 0,
            'score_norm': 0.0,
            'replace_sum': 0,
            'miss_sum': 0,
            'dup_sum': 0,
            'hit_sum': 0,
        })
        a['workloads'] += 1
        a['score_norm'] += float(term)
        a['replace_sum'] += int(r['replace'])
        a['miss_sum'] += int(r['miss'])
        a['dup_sum'] += int(r['dup'])
        a['hit_sum'] += int(r['hit'])

    out = list(agg.values())
    out.sort(key=lambda x: (x['score_norm'], x['replace_sum'], -x['dup_sum'], -x['hit_sum'], x['miss_sum']))
    return out[:topk], ranges


def _parse_workload_weights(s: str) -> Dict[str, float]:
    """解析 --w-workload 'a=2.0,b=0.5' """
    out: Dict[str, float] = {}
    if not s:
        return out
    for part in s.split(','):
        part = part.strip()
        if not part:
            continue
        if '=' not in part:
            continue
        k, v = part.split('=', 1)
        k = k.strip(); v = v.strip()
        if not k:
            continue
        try:
            out[k] = float(v)
        except ValueError:
            continue
    return out


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
    topk: int,
    metric_weights: Dict[str, float],
    workload_weights: Dict[str, float],
    zipf_s: float,
    zipf_single_events: int = 160,
    zipf_mc_events_per_core: int = 48,
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"{base}.csv"
    md_path = out_dir / f"{base}.md"

    rows = generate_rows(
        sets_list=sets_list,
        ways_list=ways_list,
        idx_list=idx_list,
        include_multicore=include_multicore,
        include_zipf=include_zipf,
        ncores=ncores,
        zipf_s=zipf_s,
        zipf_single_events=zipf_single_events,
        zipf_mc_events_per_core=zipf_mc_events_per_core,
    )

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

    top = _topn_by_workload(rows, topn=topn)
    global_top, ranges = compute_global_topk_normalized(
        rows,
        topk=topk,
        metric_weights=metric_weights,
        workload_weights=workload_weights,
    )

    header = "| workload | ncores | sets | ways | idx | mark | dup | hit | miss | repl | c0 | c1 | c2 | c3 |"
    sep = "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
    def fmt(r: dict) -> str:
        return (
            f"| {r['workload']} | {r['ncores']} | {r['sets']} | {r['ways']} | {r['index_mode']} | "
            f"{r['mark']} | {r['dup']} | {r['hit']} | {r['miss']} | {r['replace']} | "
            f"{r['core0_mark']} | {r['core1_mark']} | {r['core2_mark']} | {r['core3_mark']} |"
        )

    md_lines: List[str] = [
        '# Step29 Sweep 参数扫描结果（自动生成）',
        '',
        '全局 Top-K（normalized）：先在每个 workload 内做 min-max 归一化，再做跨 workload 加权合成。',
        'score = Σ wl_weight * ( w_replace*repl_norm + w_miss*miss_norm - w_dup*dup_norm - w_hit*hit_norm )',
        f"指标权重：w_replace={metric_weights['replace']:g}, w_miss={metric_weights['miss']:g}, w_dup={metric_weights['dup']:g}, w_hit={metric_weights['hit']:g}",
        '',
        '## Global Top-K (normalized)',
        '',
        '| rank | sets | ways | idx | score_norm | replΣ | missΣ | dupΣ | hitΣ | wl_cnt |',
        '|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|',
    ]

    for i, r in enumerate(global_top, start=1):
        md_lines.append(
            f"| {i} | {r['sets']} | {r['ways']} | {r['index_mode']} | {r['score_norm']:.6f} | {r['replace_sum']} | {r['miss_sum']} | {r['dup_sum']} | {r['hit_sum']} | {r['workloads']} |"
        )

    md_lines.extend([
        '',
        '## Workload normalization ranges',
        '',
        '说明：下面给出每个 workload 内各指标的 min/max（用于理解归一化尺度）。',
        '',
        '| workload | repl_min | repl_max | miss_min | miss_max | dup_min | dup_max | hit_min | hit_max | wl_weight |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|',
    ])

    for wl, rm in ranges.items():
        w_wl = float(workload_weights.get(wl, 1.0))
        md_lines.append(
            f"| {wl} | {rm['replace'][0]:.0f} | {rm['replace'][1]:.0f} | {rm['miss'][0]:.0f} | {rm['miss'][1]:.0f} | {rm['dup'][0]:.0f} | {rm['dup'][1]:.0f} | {rm['hit'][0]:.0f} | {rm['hit'][1]:.0f} | {w_wl:g} |"
        )

    md_lines.extend([
        '',
        'Top-N 说明：按 (replace 升序, dup 降序, hit 降序, miss 升序) 排序。',
        '',
        '## Top-N 推荐参数（每个 workload）',
        '',
    ])

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
        header,
        sep,
    ])
    md_lines.extend(fmt(r) for r in rows)
    md_lines.append('')

    md_path.write_text('\n'.join(md_lines), encoding='utf-8')
    return csv_path, md_path


def main():
    ap = argparse.ArgumentParser(description='Step29 sweep dedup 批量扫参 + Zipf + 全局 Top-K（normalized）')
    ap.add_argument('--out', default='reports', help='输出目录')
    ap.add_argument('--base', default='step29_sweep_table', help='输出文件 base（不含扩展名）')
    ap.add_argument('--sets', default='2,4,8', help='sets 列表，逗号分隔')
    ap.add_argument('--ways', default='1,2,4', help='ways 列表，逗号分隔')
    ap.add_argument('--index', default='0,1', help='index_mode 列表：0=lowbits,1=xor-fold')
    ap.add_argument('--no-multicore', action='store_true', help='不包含多核 workload')
    ap.add_argument('--no-zipf', action='store_true', help='不包含 Zipf workload')
    ap.add_argument('--ncores', type=int, default=4, help='多核 workload 的核数')
    ap.add_argument('--topn', type=int, default=3, help='每个 workload 的 Top-N')
    ap.add_argument('--topk', type=int, default=5, help='跨 workload 全局 Top-K')
    ap.add_argument('--w-replace', type=float, default=1.0, help='指标权重：replace')
    ap.add_argument('--w-miss', type=float, default=0.2, help='指标权重：miss')
    ap.add_argument('--w-dup', type=float, default=0.1, help='指标权重：dup')
    ap.add_argument('--w-hit', type=float, default=0.05, help='指标权重：hit')
    ap.add_argument('--w-workload', default='', help='workload 权重：a=2.0,b=0.5 ...（未写默认 1.0）')
    ap.add_argument('--zipf-s', type=float, default=1.2, help='Zipf 参数 s（越大越热点）')
    ap.add_argument('--zipf-single-events', type=int, default=160, help='Zipf 单核事件数')
    ap.add_argument('--zipf-mc-events-per-core', type=int, default=48, help='Zipf 多核：每核事件数')
    args = ap.parse_args()

    sets_list = [int(x) for x in args.sets.split(',') if x.strip()]
    ways_list = [int(x) for x in args.ways.split(',') if x.strip()]
    idx_list = [int(x) for x in args.index.split(',') if x.strip()]
    workload_weights = _parse_workload_weights(args.w_workload)
    metric_weights = {'replace': args.w_replace, 'miss': args.w_miss, 'dup': args.w_dup, 'hit': args.w_hit}

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
        topk=args.topk,
        metric_weights=metric_weights,
        workload_weights=workload_weights,
        zipf_s=args.zipf_s,
        zipf_single_events=args.zipf_single_events,
        zipf_mc_events_per_core=args.zipf_mc_events_per_core,
    )
    print(f'OK: wrote {csv_path} and {md_path}')


if __name__ == '__main__':
    main()
