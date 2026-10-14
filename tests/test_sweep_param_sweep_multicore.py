# tests/test_sweep_param_sweep_multicore.py
# -*- coding: utf-8 -*-
#
# Step26 实测：批量扫参工具包含多核 workload，并且 per-core 统计自洽。
#

from __future__ import annotations

import csv
from pathlib import Path

from tools.sweep_param_sweep_step26 import generate_report


def load_rows(csv_path: Path):
    with csv_path.open('r', encoding='utf-8') as f:
        r = csv.DictReader(f)
        rows = []
        for row in r:
            for k in [
                'ncores','sets','ways','index_mode','mark','dup','hit','miss','replace',
                'core0_mark','core1_mark','core2_mark','core3_mark'
            ]:
                row[k] = int(row[k])
            rows.append(row)
        return rows


def pick(rows, workload: str, sets: int, ways: int, index_mode: int):
    for row in rows:
        if row['workload'] == workload and row['sets'] == sets and row['ways'] == ways and row['index_mode'] == index_mode:
            return row
    raise KeyError((workload, sets, ways, index_mode))


def main():
    # 选一组“容量足够大”的配置，避免替换干扰统计（确保 mark=输入 unique 数）。
    # multicore_uniform: 每核 12 个 card，不重复，理论 mark = 48。
    csv_path, md_path = generate_report(
        out_dir=Path('reports'),
        base='step26_sweep_table_quick',
        sets_list=[64],
        ways_list=[2],
        index_modes=[1],
        include_multicore=True,
        ncores=4,
    )
    assert csv_path.exists() and md_path.exists(), (csv_path, md_path)

    rows = load_rows(csv_path)
    r = pick(rows, 'multicore_uniform', 64, 2, 1)

    # 基本自洽：per-core sum == total
    s = r['core0_mark'] + r['core1_mark'] + r['core2_mark'] + r['core3_mark']
    assert s == r['mark'], (r, s)

    # workload 设计：每核 12 个 card（无重复）
    assert r['mark'] == 48, r
    assert r['core0_mark'] == 12, r
    assert r['core1_mark'] == 12 and r['core2_mark'] == 12 and r['core3_mark'] == 12, r
    assert r['dup'] == 0, r
    # table 充足时不应发生替换
    assert r['replace'] == 0, r

    print('OK: step26 multicore workload present and per-core marks are consistent.')


if __name__ == '__main__':
    main()
