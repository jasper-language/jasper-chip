# tests/test_sweep_param_sweep_step28.py
# -*- coding: utf-8 -*-
"""Step28 新增能力测试：全局 Top-K（综合评分）+ 结构检查

目的：
  1) 确认 Markdown 顶部包含“全局 Top-K”区。
  2) 确认每 workload Top-N 仍然存在。
  3) 确认 CSV/MD 都能生成。

这类测试不验证“哪组参数最好”（那是研究结论），
而是验证工具输出是否存在、结构是否正确。
"""

from __future__ import annotations

from pathlib import Path


def main():
    from tools.sweep_param_sweep_step28 import generate_report

    out_dir = Path('reports')
    base = 'step28_test_table'

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
        w_replace=1.0,
        w_miss=0.2,
        w_dup=0.1,
        w_hit=0.05,
        zipf_s=1.2,
        # 不启用 zipf，保持单测极快
    )

    assert csv_path.exists(), 'CSV report not generated'
    assert md_path.exists(), 'Markdown report not generated'

    md = md_path.read_text(encoding='utf-8')
    assert '全局 Top-K 推荐参数' in md, 'Global Top-K section missing'
    assert '| rank | sets | ways | idx | score' in md, 'Global Top-K table header missing'
    assert 'Top-N 推荐参数' in md, 'Per-workload Top-N section missing'

    csv_txt = csv_path.read_text(encoding='utf-8')
    assert 'lowbit_conflict' in csv_txt, 'CSV missing basic workload rows'

    print('OK: step28 report contains global Top-K and per-workload Top-N.')


if __name__ == '__main__':
    main()
