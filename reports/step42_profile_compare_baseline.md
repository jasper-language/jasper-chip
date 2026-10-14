# Step42 Profile Benchmark

## Workloads

- shared_hot_shift (global_share_p=0.1)
- per_core_partition (global_share_p=0.1)

## Profiles (sorted by worst_score, lower is better)

|rank|profile|worst_score|worst_mode|cost|note|
|---:|---|---:|---|---:|---|
|1|step40_joint|544.00|shared_hot_shift|77.00|Step40 knee: joint scan×sweep worst-case + pareto cost proxy 的折中点|
|2|step30|1042.00|per_core_partition|33.00|Step30 baseline: sweep 参数锁定 + 回归保护（scan 使用 Step33/34 固化默认）|

## Per-workload details

### step40_joint

- scan={'cardset_size': 8, 'fifo_depth': 1, 'consume_every': 2, 'batch_size': 2} sweep={'sets': 16, 'ways': 4, 'index_mode': 0} cost=77.00

|workload|score|cycle|stall_in|sweep.replace|
|---|---:|---:|---:|---:|
|shared_hot_shift|544.00|544|0|0|
|per_core_partition|544.00|544|0|0|

- worst_score improve vs step30: 498.00 (47.79%)


### step30

- scan={'cardset_size': 8, 'fifo_depth': 1, 'consume_every': 2, 'batch_size': 2} sweep={'sets': 8, 'ways': 2, 'index_mode': 1} cost=33.00

|workload|score|cycle|stall_in|sweep.replace|
|---|---:|---:|---:|---:|
|shared_hot_shift|910.00|544|0|183|
|per_core_partition|1042.00|544|0|249|

