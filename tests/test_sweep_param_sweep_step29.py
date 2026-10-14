# tests/test_sweep_param_sweep_step29.py
# -*- coding: utf-8 -*-
"""Step29 新增能力测试：全局 Top-K（按 workload 归一化 + 加权）

验证点：
  1) Markdown 顶部包含 "Global Top-K (normalized)" 区。
  2) Markdown 包含 "Workload normalization ranges" 区（输出 min/max）。
  3) 每 workload Top-N 仍然存在。
  4) CSV/MD 均能生成。

注意：这里不验证“哪个参数最好”，只验证工具输出结构存在且可复现。
"""

from __future__ import annotations

from pathlib import Path


def main():
    from tools.sweep_param_sweep_step29 import generate_report

    out_dir = Path('reports')
    base = 'step29_test_table'

    csv_path, md_path = generate_report(
        out_dir=out_dir,
        base=base,
        sets_list=[2],
        ways_list=[1],
        idx_list=[0, 1],
        include_multicore=False,
        include_zipf=False,
        ncores=4,
        topn=1,
        topk=2,
        metric_weights={'replace': 1.0, 'miss': 0.2, 'dup': 0.1, 'hit': 0.05},
        workload_weights={},
        zipf_s=1.2,
        # 不启用 zipf，保持单测极快
    )

    assert csv_path.exists(), 'CSV report not generated'
    assert md_path.exists(), 'Markdown report not generated'

    md = md_path.read_text(encoding='utf-8')
    assert 'Global Top-K (normalized)' in md, 'Global normalized Top-K section missing'
    assert 'Workload normalization ranges' in md, 'Normalization ranges section missing'
    assert 'Top-N 推荐参数' in md, 'Per-workload Top-N section missing'

    csv_txt = csv_path.read_text(encoding='utf-8')
    assert 'lowbit_conflict' in csv_txt, 'CSV missing basic workload rows'

    print('OK: step29 report contains normalized Global Top-K and per-workload ranges.')


if __name__ == '__main__':
    main()
