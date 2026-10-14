# tests/test_sweep_param_sweep.py
# -*- coding: utf-8 -*-
#
# Step25 实测：自动生成 sweep 去重表参数扫描报告，并做趋势断言。
#
# 断言策略（尽量稳健，不依赖“精确数值”）：
#   1) lowbit_conflict：xor-fold 索引应显著降低 replace
#   2) lowbit_conflict：ways=2 应比 ways=1 更少 replace（同 sets / index_mode=0）
#

from __future__ import annotations

import csv
from pathlib import Path

from tools.sweep_param_sweep import SweepCfg, generate_report


def load_rows(csv_path: Path):
    with csv_path.open("r", encoding="utf-8") as f:
        r = csv.DictReader(f)
        rows = []
        for row in r:
            # 统一转成 int，方便比较
            for k in ["sets", "ways", "index_mode", "mark", "dup", "hit", "miss", "replace"]:
                row[k] = int(row[k])
            rows.append(row)
        return rows


def pick(rows, workload: str, sets: int, ways: int, index_mode: int):
    for row in rows:
        if row["workload"] == workload and row["sets"] == sets and row["ways"] == ways and row["index_mode"] == index_mode:
            return row
    raise KeyError((workload, sets, ways, index_mode))


def main():
    # 只扫描少量点，保证测试运行快
    cfgs = [
        SweepCfg(sets=4, ways=1, index_mode=0),
        SweepCfg(sets=4, ways=2, index_mode=0),
        SweepCfg(sets=4, ways=2, index_mode=1),
    ]

    csv_path, md_path = generate_report(cfgs, Path("reports"))
    assert csv_path.exists() and md_path.exists(), (csv_path, md_path)

    rows = load_rows(csv_path)

    # 在 lowbit_conflict 下比较
    wl = "lowbit_conflict"
    r_w1 = pick(rows, wl, 4, 1, 0)
    r_w2 = pick(rows, wl, 4, 2, 0)
    r_xf = pick(rows, wl, 4, 2, 1)

    print(f"lowbit_conflict: ways1 replace={r_w1['replace']}, ways2 replace={r_w2['replace']}, xor-fold replace={r_xf['replace']}")

    # 断言 1：ways=2 必须优于 ways=1（替换更少）
    assert r_w2["replace"] < r_w1["replace"], (r_w1, r_w2)

    # 断言 2：xor-fold 必须优于 lowbits（替换更少）
    assert r_xf["replace"] < r_w2["replace"], (r_w2, r_xf)

    print("OK: param sweep report generated and trends look right.")


if __name__ == "__main__":
    main()
