# tests/test_step30_baseline.py
# -*- coding: utf-8 -*-
"""Step30：baseline 回归测试（固定种子/固定规模）

目的：
  1) 确认 reports/step30_baseline.json 存在。
  2) 用同样的配置重新计算一次 Top-1，确保推荐配置不漂移（否则说明工具逻辑或 RTL 行为变了）。
  3) 确认 rtl/gc_params.py 与 TopSoC 默认参数跟 baseline 一致。

说明：baseline 规模很小，只用于回归“推荐配置是否改变”。
"""

from __future__ import annotations

import json
from pathlib import Path
import warnings

try:
    # Amaranth 0.5+ 推荐位置
    from amaranth.hdl import UnusedElaboratable
except Exception:  # pragma: no cover
    # 兼容老版本
    from amaranth.hdl.ir import UnusedElaboratable


def main():
    baseline_path = Path('reports') / 'step30_baseline.json'
    assert baseline_path.exists(), 'step30 baseline json missing'

    baseline = json.loads(baseline_path.read_text(encoding='utf-8'))
    cfg_lists = baseline['cfg_lists']
    metric_w = baseline['metric_weights']
    wl_w = baseline.get('workload_weights', {})
    best0 = baseline['best_cfg']

    from tools.sweep_param_sweep_step29 import generate_rows, compute_global_topk_normalized

    rows = generate_rows(
        sets_list=cfg_lists['sets'],
        ways_list=cfg_lists['ways'],
        idx_list=cfg_lists['index_mode'],
        include_multicore=bool(baseline['include_multicore']),
        include_zipf=bool(baseline['include_zipf']),
        ncores=int(baseline['ncores']),
        zipf_s=float(baseline['zipf']['s']),
        zipf_single_events=int(baseline['zipf']['single_events']),
        zipf_mc_events_per_core=int(baseline['zipf']['mc_events_per_core']),
    )
    top, _ranges = compute_global_topk_normalized(
        rows,
        topk=1,
        metric_weights=metric_w,
        workload_weights=wl_w,
    )
    best1 = top[0]

    assert int(best1['sets']) == int(best0['sets'])
    assert int(best1['ways']) == int(best0['ways'])
    assert int(best1['index_mode']) == int(best0['index_mode'])

    # 同时要求默认参数文件与 SoC 默认值一致
    from rtl.gc_params import (
        DEFAULT_SWEEP_CARD_TABLE_SIZE,
        DEFAULT_SWEEP_CARD_TABLE_WAYS,
        DEFAULT_SWEEP_CARD_INDEX_MODE,
    )
    assert DEFAULT_SWEEP_CARD_TABLE_SIZE == int(best0['sets'])
    assert DEFAULT_SWEEP_CARD_TABLE_WAYS == int(best0['ways'])
    assert DEFAULT_SWEEP_CARD_INDEX_MODE == int(best0['index_mode'])

    from rtl.top_soc import TopSoC
    # 只检查默认参数值，不需要真正跑仿真；过滤 Amaranth 的 UnusedElaboratable 警告。
    warnings.filterwarnings('ignore', category=UnusedElaboratable)
    soc = TopSoC()
    assert soc.sweep_card_table_size == int(best0['sets'])
    assert soc.sweep_card_table_ways == int(best0['ways'])
    assert soc.sweep_card_index_mode == int(best0['index_mode'])

    print('OK: step30 baseline stable and defaults match (gc_params + TopSoC).')


if __name__ == '__main__':
    main()
