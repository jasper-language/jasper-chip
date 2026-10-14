# Step29 Sweep 参数扫描结果（自动生成）

全局 Top-K（normalized）：先在每个 workload 内做 min-max 归一化，再做跨 workload 加权合成。
score = Σ wl_weight * ( w_replace*repl_norm + w_miss*miss_norm - w_dup*dup_norm - w_hit*hit_norm )
指标权重：w_replace=1, w_miss=0.2, w_dup=0.1, w_hit=0.05

## Global Top-K (normalized)

| rank | sets | ways | idx | score_norm | replΣ | missΣ | dupΣ | hitΣ | wl_cnt |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 2 | 1 | 1 | -0.150000 | 10 | 14 | 6 | 6 | 2 |
| 2 | 2 | 1 | 0 | 2.200000 | 18 | 20 | 0 | 0 | 2 |

## Workload normalization ranges

说明：下面给出每个 workload 内各指标的 min/max（用于理解归一化尺度）。

| workload | repl_min | repl_max | miss_min | miss_max | dup_min | dup_max | hit_min | hit_max | wl_weight |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| lowbit_conflict | 10 | 11 | 12 | 12 | 0 | 0 | 0 | 0 | 1 |
| toggle_2cards | 0 | 7 | 2 | 8 | 0 | 6 | 0 | 6 | 1 |

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

| workload | ncores | sets | ways | idx | mark | dup | hit | miss | repl | c0 | c1 | c2 | c3 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| lowbit_conflict | 1 | 2 | 1 | 0 | 12 | 0 | 0 | 12 | 11 | 12 | 0 | 0 | 0 |
| lowbit_conflict | 1 | 2 | 1 | 1 | 12 | 0 | 0 | 12 | 10 | 12 | 0 | 0 | 0 |
| toggle_2cards | 1 | 2 | 1 | 0 | 8 | 0 | 0 | 8 | 7 | 8 | 0 | 0 | 0 |
| toggle_2cards | 1 | 2 | 1 | 1 | 2 | 6 | 6 | 2 | 0 | 2 | 0 | 0 | 0 |
