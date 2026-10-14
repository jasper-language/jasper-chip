# Step40 Joint Pareto Baseline

## Summary

- n_total: 96
- n_front: 4
- best_worst_score: 2176.0
- min_cost_on_front: 21.0

## Knee 선택

- method: near_best_cheapest(eps=0.02)
- worst_score: 2176.0
- cost: 77.0
- worst_mode: shared_hot_shift
- scan: {'cardset_size': 8, 'fifo_depth': 1, 'consume_every': 2, 'batch_size': 2}
- sweep: {'sets': 16, 'ways': 4, 'index_mode': 0}

## Pareto Front (Top 12 by worst_score)

1. worst=2176.00, cost=77.0, scan={'cardset_size': 8, 'fifo_depth': 1, 'consume_every': 2, 'batch_size': 2}, sweep={'sets': 16, 'ways': 4, 'index_mode': 0}, worst_mode=shared_hot_shift
2. worst=66784.00, cost=45.0, scan={'cardset_size': 8, 'fifo_depth': 1, 'consume_every': 4, 'batch_size': 2}, sweep={'sets': 8, 'ways': 4, 'index_mode': 0}, worst_mode=per_core_partition
3. worst=156784.00, cost=29.0, scan={'cardset_size': 8, 'fifo_depth': 1, 'consume_every': 4, 'batch_size': 2}, sweep={'sets': 16, 'ways': 1, 'index_mode': 0}, worst_mode=per_core_partition
4. worst=180984.00, cost=21.0, scan={'cardset_size': 8, 'fifo_depth': 1, 'consume_every': 4, 'batch_size': 2}, sweep={'sets': 8, 'ways': 1, 'index_mode': 0}, worst_mode=per_core_partition
