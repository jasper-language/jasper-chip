# tests/test_sweep_param_sweep_step27.py
# -*- coding: utf-8 -*-
"""Step27 新增能力测试：Zipf workload + Top-N 汇总

目的：
  1) 确认 Zipf workload 被纳入报告（CSV/MD 都能看到）。
  2) 确认 Markdown 顶部包含 Top-N 汇总区。

这类测试不验证“哪组参数最好”（那是研究结论），
而是验证工具输出是否存在、结构是否正确。
"""

from __future__ import annotations

from pathlib import Path


def main():
    from tools.sweep_param_sweep_step27 import generate_report

    out_dir = Path('reports')
    base = 'step27_test_table'

    csv_path, md_path = generate_report(
        out_dir=out_dir,
        base=base,
        sets_list=[2],
        ways_list=[1],
        idx_list=[0],
        include_multicore=False,
        include_zipf=True,
        ncores=4,
        topn=1,
        zipf_s=1.2,
        # 单测需要快：把 Zipf 事件数压到很小即可验证输出路径
        zipf_single_events=48,
        zipf_mc_events_per_core=16,
    )

    assert csv_path.exists(), 'CSV report not generated'
    assert md_path.exists(), 'Markdown report not generated'

    md = md_path.read_text(encoding='utf-8')
    assert 'Top-N 推荐参数' in md, 'Top-N section missing'
    assert 'zipf_single' in md or 'zipf_single_s' in md, 'Zipf workload missing in MD'

    csv_txt = csv_path.read_text(encoding='utf-8')
    assert 'zipf_single' in csv_txt or 'zipf_single_s' in csv_txt, 'Zipf workload missing in CSV'

    print('OK: step27 report contains Top-N section and Zipf workloads.')


if __name__ == '__main__':
    main()
