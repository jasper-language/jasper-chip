# Step44 Profile Variance (across seeds)

ref_profile: **step30**\n\n## Workloads

- shared_hot_shift (global_share_p=0.1)
- per_core_partition (global_share_p=0.1)

## Summary (sorted by mean worst_score, lower is better)

|rank|profile|mean|std|min|max|avg_rank|wins_vs_ref|win_rate|
|---:|---|---:|---:|---:|---:|---:|---:|---:|
|1|step40_joint|544.00|0.00|544.00|544.00|1.00|5|100.0%|
|2|step30|1090.40|33.03|1042.00|1132.00|2.00|-|-|
|3|step40_pareto3|3516.40|17.11|3490.00|3536.00|3.00|0|0.0%|

## Per-seed details

### seed=20260102

|profile|worst_score|worst_mode|cost|
|---|---:|---|---:|
|step30|1042.00|per_core_partition|33.00|
|step40_joint|544.00|shared_hot_shift|77.00|
|step40_pareto3|3524.00|per_core_partition|21.00|

### seed=20260103

|profile|worst_score|worst_mode|cost|
|---|---:|---|---:|
|step30|1106.00|per_core_partition|33.00|
|step40_joint|544.00|shared_hot_shift|77.00|
|step40_pareto3|3490.00|per_core_partition|21.00|

### seed=20260104

|profile|worst_score|worst_mode|cost|
|---|---:|---|---:|
|step30|1132.00|per_core_partition|33.00|
|step40_joint|544.00|shared_hot_shift|77.00|
|step40_pareto3|3536.00|per_core_partition|21.00|

### seed=20260105

|profile|worst_score|worst_mode|cost|
|---|---:|---|---:|
|step30|1088.00|per_core_partition|33.00|
|step40_joint|544.00|shared_hot_shift|77.00|
|step40_pareto3|3520.00|per_core_partition|21.00|

### seed=20260106

|profile|worst_score|worst_mode|cost|
|---|---:|---|---:|
|step30|1084.00|per_core_partition|33.00|
|step40_joint|544.00|shared_hot_shift|77.00|
|step40_pareto3|3512.00|per_core_partition|21.00|

