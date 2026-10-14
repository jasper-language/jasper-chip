# tools/generate_step30_baseline.py
# -*- coding: utf-8 -*-
"""Step30: 生成“推荐参数 baseline”并回写默认参数文件。

目的：
  1) 让“推荐配置”可复现、可回归：把一次固定种子/固定规模的扫参结果固化为 baseline。
  2) 将推荐配置写入 rtl/gc_params.py，让 TopSoC 默认采用。

注意：baseline 的 workload/事件数刻意选得很小，保证在 CI/离线环境也能跑。
"""

from __future__ import annotations

import json
from pathlib import Path

from tools.sweep_param_sweep_step29 import generate_rows, compute_global_topk_normalized


DEFAULT_SETS_LIST = [2, 4, 8]
DEFAULT_WAYS_LIST = [1, 2]
DEFAULT_IDX_LIST  = [0, 1]

DEFAULT_NCORES = 4
DEFAULT_INCLUDE_MULTICORE = True
DEFAULT_INCLUDE_ZIPF = True

# Zipf 事件数：保持很小，单测/离线环境更快
DEFAULT_ZIPF_S = 1.2
DEFAULT_ZIPF_SINGLE_EVENTS = 32
DEFAULT_ZIPF_MC_EVENTS_PER_CORE = 12

# 默认评分权重（与 Step29 工具默认一致）
DEFAULT_METRIC_WEIGHTS = {
    'replace': 1.0,
    'miss': 0.2,
    'dup': 0.1,
    'hit': 0.05,
}

# workload 权重：默认全 1.0；可在此加大某类 workload 的影响
DEFAULT_WORKLOAD_WEIGHTS = {
    # 例：'zipf_mc_s1p2': 2.0,
}


def write_gc_params(path: Path, *, sets: int, ways: int, index_mode: int) -> None:
    """写入 rtl/gc_params.py（中文注释，研究用）。"""
    text = f'''# rtl/gc_params.py
# -*- coding: utf-8 -*-

"""GC 研究默认参数（Step30 自动生成）

该文件的目标是：让 SoC 默认参数不再靠手填，而是来自一个“可复现的推荐配置”。

生成方式：
  - 运行 `python -m tools.generate_step30_baseline`
  - 脚本会用固定种子/固定规模 workload 做一次小扫参
  - 取归一化全局 Top-1 作为默认 sweep 去重表配置

这套流程可作为研究阶段的“参数锁定 + 回归基线”。
"""

# Sweep(card) 去重表默认参数：
DEFAULT_SWEEP_CARD_TABLE_SIZE = {sets}
DEFAULT_SWEEP_CARD_TABLE_WAYS = {ways}
DEFAULT_SWEEP_CARD_INDEX_MODE = {index_mode}  # 0=lowbits, 1=xor-fold
'''
    path.write_text(text, encoding='utf-8')


def main():
    rows = generate_rows(
        sets_list=DEFAULT_SETS_LIST,
        ways_list=DEFAULT_WAYS_LIST,
        idx_list=DEFAULT_IDX_LIST,
        include_multicore=DEFAULT_INCLUDE_MULTICORE,
        include_zipf=DEFAULT_INCLUDE_ZIPF,
        ncores=DEFAULT_NCORES,
        zipf_s=DEFAULT_ZIPF_S,
        zipf_single_events=DEFAULT_ZIPF_SINGLE_EVENTS,
        zipf_mc_events_per_core=DEFAULT_ZIPF_MC_EVENTS_PER_CORE,
    )

    top, ranges = compute_global_topk_normalized(
        rows,
        topk=1,
        metric_weights=DEFAULT_METRIC_WEIGHTS,
        workload_weights=DEFAULT_WORKLOAD_WEIGHTS,
    )
    best = top[0]

    out_dir = Path('reports')
    out_dir.mkdir(parents=True, exist_ok=True)
    baseline_path = out_dir / 'step30_baseline.json'
    baseline = {
        'version': 'step30',
        'cfg_lists': {
            'sets': DEFAULT_SETS_LIST,
            'ways': DEFAULT_WAYS_LIST,
            'index_mode': DEFAULT_IDX_LIST,
        },
        'ncores': DEFAULT_NCORES,
        'include_multicore': DEFAULT_INCLUDE_MULTICORE,
        'include_zipf': DEFAULT_INCLUDE_ZIPF,
        'zipf': {
            's': DEFAULT_ZIPF_S,
            'single_events': DEFAULT_ZIPF_SINGLE_EVENTS,
            'mc_events_per_core': DEFAULT_ZIPF_MC_EVENTS_PER_CORE,
        },
        'metric_weights': DEFAULT_METRIC_WEIGHTS,
        'workload_weights': DEFAULT_WORKLOAD_WEIGHTS,
        'best_cfg': {
            'sets': int(best['sets']),
            'ways': int(best['ways']),
            'index_mode': int(best['index_mode']),
            'score_norm': float(best['score_norm']),
            'replace_sum': int(best['replace_sum']),
            'miss_sum': int(best['miss_sum']),
            'dup_sum': int(best['dup_sum']),
            'hit_sum': int(best['hit_sum']),
            'workloads': int(best['workloads']),
        },
        'ranges': {
            wl: {m: [float(a), float(b)] for m, (a, b) in ms.items()}
            for wl, ms in ranges.items()
        },
    }
    baseline_path.write_text(json.dumps(baseline, ensure_ascii=False, indent=2), encoding='utf-8')

    # 回写默认参数文件
    write_gc_params(Path('rtl') / 'gc_params.py', sets=int(best['sets']), ways=int(best['ways']), index_mode=int(best['index_mode']))

    print(f"OK: wrote {baseline_path} and rtl/gc_params.py (best={{sets={best['sets']}, ways={best['ways']}, idx={best['index_mode']}}})")


if __name__ == '__main__':
    main()
