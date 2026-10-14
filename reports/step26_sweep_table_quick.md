# Step26 Sweep 参数扫描结果（自动生成）

说明：replace 越小越好；dup 越大越好。多核 workload 会输出每核 mark 计数。

| workload | ncores | sets | ways | idx | mark | dup | hit | miss | repl | c0 | c1 | c2 | c3 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| lowbit_conflict | 1 | 64 | 2 | 1 | 12 | 0 | 0 | 12 | 0 | 12 | 0 | 0 | 0 |
| toggle_2cards | 1 | 64 | 2 | 1 | 2 | 6 | 6 | 2 | 0 | 2 | 0 | 0 | 0 |
| multicore_hot0 | 4 | 64 | 2 | 1 | 28 | 2 | 2 | 28 | 0 | 24 | 2 | 1 | 1 |
| multicore_uniform | 4 | 64 | 2 | 1 | 48 | 0 | 0 | 48 | 0 | 12 | 12 | 12 | 12 |
