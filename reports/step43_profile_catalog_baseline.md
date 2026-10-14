# Step43 Profile Catalog

## Workloads

- shared_hot_shift (global_share_p=0.1)
- per_core_partition (global_share_p=0.1)

## Profiles (sorted by worst_score, lower is better)

|rank|profile|worst_score|worst_mode|cost|
|---:|---|---:|---|---:|
|1|step40_joint|544.00|shared_hot_shift|77.00|
|2|step30|1042.00|per_core_partition|33.00|
|3|step40_pareto1|3242.00|per_core_partition|45.00|
|4|step40_pareto2|3472.00|per_core_partition|29.00|
|5|step40_pareto3|3524.00|per_core_partition|21.00|

## Per-workload details

### step40_joint

- scan={'cardset_size': 8, 'fifo_depth': 1, 'consume_every': 2, 'batch_size': 2} sweep={'sets': 16, 'ways': 4, 'index_mode': 0} cost=77.00

|workload|score|cycle|stall_in|sweep.replace|
|---|---:|---:|---:|---:|
|shared_hot_shift|544.00|544|0|0|
|per_core_partition|544.00|544|0|0|

### step30

- scan={'cardset_size': 8, 'fifo_depth': 1, 'consume_every': 2, 'batch_size': 2} sweep={'sets': 8, 'ways': 2, 'index_mode': 1} cost=33.00

|workload|score|cycle|stall_in|sweep.replace|
|---|---:|---:|---:|---:|
|shared_hot_shift|910.00|544|0|183|
|per_core_partition|1042.00|544|0|249|

### step40_pareto1

- scan={'cardset_size': 8, 'fifo_depth': 1, 'consume_every': 4, 'batch_size': 2} sweep={'sets': 8, 'ways': 4, 'index_mode': 0} cost=45.00

|workload|score|cycle|stall_in|sweep.replace|
|---|---:|---:|---:|---:|
|shared_hot_shift|3142.00|576|252|23|
|per_core_partition|3242.00|576|252|73|

### step40_pareto2

- scan={'cardset_size': 8, 'fifo_depth': 1, 'consume_every': 4, 'batch_size': 2} sweep={'sets': 16, 'ways': 1, 'index_mode': 0} cost=29.00

|workload|score|cycle|stall_in|sweep.replace|
|---|---:|---:|---:|---:|
|shared_hot_shift|3284.00|576|252|94|
|per_core_partition|3472.00|576|252|188|

### step40_pareto3

- scan={'cardset_size': 8, 'fifo_depth': 1, 'consume_every': 4, 'batch_size': 2} sweep={'sets': 8, 'ways': 1, 'index_mode': 0} cost=21.00

|workload|score|cycle|stall_in|sweep.replace|
|---|---:|---:|---:|---:|
|shared_hot_shift|3394.00|576|252|149|
|per_core_partition|3524.00|576|252|214|

