# Step27 Sweep 参数扫描结果（自动生成）

Top-N 说明：按 (replace 升序, dup 降序, hit 降序, miss 升序) 排序。

## Top-N 推荐参数（每个 workload）

### lowbit_conflict

| rank | sets | ways | idx | mark | dup | repl | hit | miss |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 2 | 1 | 0 | 12 | 0 | 11 | 0 | 12 |

### toggle_2cards

| rank | sets | ways | idx | mark | dup | repl | hit | miss |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 2 | 1 | 0 | 8 | 0 | 7 | 0 | 8 |

### zipf_single_s1p2

| rank | sets | ways | idx | mark | dup | repl | hit | miss |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 2 | 1 | 0 | 40 | 8 | 38 | 8 | 40 |

### zipf_mc_s1p2

| rank | sets | ways | idx | mark | dup | repl | hit | miss |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 2 | 1 | 0 | 55 | 9 | 53 | 9 | 55 |

## 明细全表

说明：replace 越小越好（替换抖动少）；dup 越大越好（同 epoch 去重有效）。

| workload | ncores | sets | ways | idx | mark | dup | hit | miss | repl | c0 | c1 | c2 | c3 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| lowbit_conflict | 1 | 2 | 1 | 0 | 12 | 0 | 0 | 12 | 11 | 12 | 0 | 0 | 0 |
| toggle_2cards | 1 | 2 | 1 | 0 | 8 | 0 | 0 | 8 | 7 | 8 | 0 | 0 | 0 |
| zipf_single_s1p2 | 1 | 2 | 1 | 0 | 40 | 8 | 8 | 40 | 38 | 40 | 0 | 0 | 0 |
| zipf_mc_s1p2 | 4 | 2 | 1 | 0 | 55 | 9 | 9 | 55 | 53 | 16 | 14 | 13 | 12 |
