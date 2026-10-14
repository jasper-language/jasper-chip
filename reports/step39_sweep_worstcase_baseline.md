# Step39 Sweep Worst-case Recommendation (mutator model)

## Base config

- seed=20260103 ncores=4 epochs=2 events/core/epoch=64

- card_space=64 zipf_s=1.07 phase_shift=7

- workload_modes=shared_hot_shift, per_core_partition  global_share_p=0.1


## Fixed scan defaults

- cardset=8 fifo=1 consume=2 batch=2


## Score weights (lower is better)

- score = 1.0*cycle + 8.0*stall_in + 4.0*sweep.replace


## Global Top-K (worst-case=max across workloads)

### #1: sets=16 ways=4 index_mode=0

- worst_score=544.00  worst_mode=shared_hot_shift

  - shared_hot_shift: score=544.00  cycle=544 stall_in=0 replace=0 miss=108 hit=404 dup=0

  - per_core_partition: score=544.00  cycle=544 stall_in=0 replace=0 miss=114 hit=398 dup=0


### #2: sets=16 ways=4 index_mode=1

- worst_score=544.00  worst_mode=shared_hot_shift

  - shared_hot_shift: score=544.00  cycle=544 stall_in=0 replace=0 miss=108 hit=404 dup=0

  - per_core_partition: score=544.00  cycle=544 stall_in=0 replace=0 miss=114 hit=398 dup=0


### #3: sets=16 ways=4 index_mode=2

- worst_score=544.00  worst_mode=shared_hot_shift

  - shared_hot_shift: score=544.00  cycle=544 stall_in=0 replace=0 miss=108 hit=404 dup=0

  - per_core_partition: score=544.00  cycle=544 stall_in=0 replace=0 miss=114 hit=398 dup=0


### #4: sets=32 ways=2 index_mode=0

- worst_score=544.00  worst_mode=shared_hot_shift

  - shared_hot_shift: score=544.00  cycle=544 stall_in=0 replace=0 miss=108 hit=404 dup=0

  - per_core_partition: score=544.00  cycle=544 stall_in=0 replace=0 miss=114 hit=398 dup=0


### #5: sets=32 ways=2 index_mode=1

- worst_score=544.00  worst_mode=shared_hot_shift

  - shared_hot_shift: score=544.00  cycle=544 stall_in=0 replace=0 miss=108 hit=404 dup=0

  - per_core_partition: score=544.00  cycle=544 stall_in=0 replace=0 miss=114 hit=398 dup=0


### #6: sets=32 ways=2 index_mode=2

- worst_score=544.00  worst_mode=shared_hot_shift

  - shared_hot_shift: score=544.00  cycle=544 stall_in=0 replace=0 miss=108 hit=404 dup=0

  - per_core_partition: score=544.00  cycle=544 stall_in=0 replace=0 miss=114 hit=398 dup=0


### #7: sets=32 ways=4 index_mode=0

- worst_score=544.00  worst_mode=shared_hot_shift

  - shared_hot_shift: score=544.00  cycle=544 stall_in=0 replace=0 miss=108 hit=404 dup=0

  - per_core_partition: score=544.00  cycle=544 stall_in=0 replace=0 miss=114 hit=398 dup=0


### #8: sets=32 ways=4 index_mode=1

- worst_score=544.00  worst_mode=shared_hot_shift

  - shared_hot_shift: score=544.00  cycle=544 stall_in=0 replace=0 miss=108 hit=404 dup=0

  - per_core_partition: score=544.00  cycle=544 stall_in=0 replace=0 miss=114 hit=398 dup=0


### #9: sets=32 ways=4 index_mode=2

- worst_score=544.00  worst_mode=shared_hot_shift

  - shared_hot_shift: score=544.00  cycle=544 stall_in=0 replace=0 miss=108 hit=404 dup=0

  - per_core_partition: score=544.00  cycle=544 stall_in=0 replace=0 miss=114 hit=398 dup=0


### #10: sets=8 ways=4 index_mode=1

- worst_score=1072.00  worst_mode=per_core_partition

  - shared_hot_shift: score=932.00  cycle=544 stall_in=0 replace=97 miss=161 hit=351 dup=0

  - per_core_partition: score=1072.00  cycle=544 stall_in=0 replace=132 miss=196 hit=316 dup=0



## Sensitivity (by mean worst_score)

- **sets**: delta=1235.56, best=32, mean_worst_by_value={'4': 2081.3333333333335, '8': 1703.5555555555557, '16': 1313.7777777777778, '32': 845.7777777777778}

- **ways**: delta=1017.00, best=4, mean_worst_by_value={'1': 2001.0, '2': 1473.3333333333333, '4': 984.0}

- **index_mode**: delta=134.67, best=1, mean_worst_by_value={'0': 1531.0, '1': 1396.3333333333333, '2': 1531.0}

