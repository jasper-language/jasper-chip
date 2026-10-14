# Step35 多核 card 分布 workload baseline

### shared_hot_shift (对照)
- cycle=832
- scan_out=395 (stall=342)
- sweep_mark=176 replace=144
- card_dist: union=63 shared=56 shared_ratio=0.889 avg_jaccard=0.712
- per_core_unique=[51, 48, 50, 49]

### per_core_partition (新增 workload)
- cycle=832
- scan_out=395 (stall=316)
- sweep_mark=259 replace=227
- card_dist: union=64 shared=53 shared_ratio=0.828 avg_jaccard=0.326
- per_core_unique=[34, 34, 38, 33]

> 期望趋势：per_core_partition 的 shared_ratio / avg_jaccard 应明显低于 shared_hot_shift。
