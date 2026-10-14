# Step28 Sweep 参数扫描结果（自动生成）

全局 Top-K：对所有 workload 的统计做加权汇总，得到综合 score（越小越好）。
score = w_replace*Σreplace + w_miss*Σmiss - w_dup*Σdup - w_hit*Σhit
默认权重：w_replace=1, w_miss=0.2, w_dup=0.1, w_hit=0.05

## 全局 Top-K 推荐参数（跨 workload）

| rank | sets | ways | idx | score | replΣ | missΣ | dupΣ | hitΣ | wl_cnt |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 2 | 1 | 1 | 11.900 | 10 | 14 | 6 | 6 | 2 |
| 2 | 2 | 1 | 0 | 22.000 | 18 | 20 | 0 | 0 | 2 |

Top-N 说明：按 (replace 升序, dup 降序, hit 降序, miss 升序) 排序。

## Top-N 推荐参数（每个 workload）

### lowbit_conflict

| rank | sets | ways | idx | mark | dup | repl | hit | miss |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 2 | 1 | 1 | 12 | 0 | 10 | 0 | 12 |

### toggle_2cards

| rank | sets | ways | idx | mark | dup | repl | hit | miss |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 2 | 1 | 1 | 2 | 6 | 0 | 6 | 2 |

## 明细全表

说明：replace 越小越好（替换抖动少）；dup 越大越好（同 epoch 去重有效）。

| workload | ncores | sets | ways | idx | mark | dup | hit | miss | repl | c0 | c1 | c2 | c3 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| lowbit_conflict | 1 | 2 | 1 | 0 | 12 | 0 | 0 | 12 | 11 | 12 | 0 | 0 | 0 |
| lowbit_conflict | 1 | 2 | 1 | 1 | 12 | 0 | 0 | 12 | 10 | 12 | 0 | 0 | 0 |
| toggle_2cards | 1 | 2 | 1 | 0 | 8 | 0 | 0 | 8 | 7 | 8 | 0 | 0 | 0 |
| toggle_2cards | 1 | 2 | 1 | 1 | 2 | 6 | 6 | 2 | 0 | 2 | 0 | 0 | 0 |
