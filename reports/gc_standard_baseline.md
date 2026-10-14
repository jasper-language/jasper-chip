# Standard GC Baseline Report

## 1. Configuration Summary

| Parameter | Value |
|-----------|-------|
| profile | Standard |
| gc_slots | 16 |
| rb_cache_ways | 4 |
| rb_slots | 8 |
| wb_depth | 8 |
| mv_depth | 8 |
| backend_count | 1 |
| metadata_bank_count | 1 |
| forwarding_bank_count | 1 |
| slots_bank_count | 1 |
| forwarding_table_impl | standard |
| metadata_pipeline_impl | standard |
| slots_impl | standard |
| metadata_cache_size | 4096 |
| metadata_cache_ways | 2 |
| metadata_cache_access_granularity | 32 |
| stream_buffer_enable | True |
| stream_buffer_entries | 4 |
| dcache_bypass_enable | True |
| cache_partition_enable | True |
| enable_compact | True |
| enable_reloc | True |
| perf_counters_enable | False |
| trace_ports_enable | False |
| debug | False |
| yosys_cells | 862 |
| yosys_gate_equiv | 3500 |

> **配置来源说明:** 本报告使用 explore/gc-backend-pipeline 当前分支中的 Standard profile 生成。该配置可能不同于 main 分支历史 Standard 参数，因此本报告作为当前 explore 分支的 Standard 对照基线。不等价于真实芯片或 PDK 数据。

**Toolchain:** Amaranth HDL, Yosys 0.66 (generic lib, no PDK)
**Cell count:** 862 cells, ~3500 GE

---

## 2. Throughput Analysis

### Model Assumptions

- Event ratios are **independent** (non-mutually-exclusive)
- Metadata = 80% of GC, WB = 50%, RB = 30%
- Backend drain rate = 0.20 evt/cyc (single backend)
- Metadata drain rate = 0.20 evt/cyc (single bank, 5-stage)
- WB drain rate = 0.50 evt/cyc (FIFO, zero-cycle frontend)
- RB drain rate = 0.33 evt/cyc (non-blocking, 3-cycle lookup)

### Throughput by GC Ratio

| Scenario | GC% | Meta | WB | RB | Total | Steady | First Bottleneck | Max GC% |
|----------|-----|------|----|----|-------|--------|------------------|--------|
| Idle       |     0% | 0.0000 | 0.0000 | 0.0000 | 0.0000 | ✅ | metadata_cache       |    25% |
| Normal     |     5% | 0.0400 | 0.0250 | 0.0150 | 0.0800 | ✅ | metadata_cache       |    25% |
| Standard   |    10% | 0.0800 | 0.0500 | 0.0300 | 0.1600 | ✅ | metadata_cache       |    25% |
| HighLoad   |    20% | 0.1600 | 0.1000 | 0.0600 | 0.3200 | ✅ | metadata_cache       |    25% |
| Stress     |    25% | 0.2000 | 0.1250 | 0.0750 | 0.4000 | ✅ | metadata_cache       |    25% |
| Stress30   |    30% | 0.2400 | 0.1500 | 0.0900 | 0.4800 | ❌ | metadata_cache       |    25% |

### Key Findings

- **Standard (10% GC):** Steady. No bottleneck. Total event rate = 0.1600 < 0.20 drain.
- **HighLoad (20% GC):** ✅ Steady. First bottleneck: metadata_cache.
- **Stress (25% GC):** ✅ Steady. First bottleneck: metadata_cache.
- **Stress30 (30% GC):** ❌ Bottleneck found.
- **Max supported GC ratio:** 25% (limited by metadata_cache)

### Bottleneck Sequence (by increasing GC%)

- **metadata_cache** saturates at ~25% GC

---

## 3. Timing Risk / Fmax

**Note:** These are structural timing estimates, NOT real STA results.
No PDK, no P&R, no clock tree. Yosys synthesis uses generic `_100` cells.

### Risk Classification

- **A:** Low risk — shallow logic, few muxes, no priority chains
- **B:** Moderate risk — multi-way compare, priority encoders < 8 wide
- **C:** High risk — deep mux trees, wide priority encoders
- **D:** Critical — likely to fail timing at target frequency

| Module | gates | cells | compares | mux | mux_depth | PE width | FIFOs | Risk | Suspect |
|--------|-------|-------|----------|-----|-----------|----------|-------|------|---------|
| GCSubsystem (top)         |  3500 | 862   |   8 |  24 |   2 |   4 |   5 | B    | priority_encoder_gc_slots |
| GCMemoryPolicy            |  1200 | -     |   4 |  12 |   2 |   2 |   2 | A    | none                      |
| MetadataCacheStandard     |  1800 | -     |   4 |   8 |   2 |   2 |   0 | B    | combinational_tag_compare |
| StreamBuffer              |   600 | -     |   2 |   4 |   1 |   0 |   1 | A    | none                      |
| RootScanner               |   800 | -     |   2 |   6 |   2 |   0 |   1 | B    | root_table_compare        |
| HeapWalker                |   900 | -     |   3 |   8 |   2 |   0 |   1 | B    | object_scan_width_mux     |
| CycleController           |   500 | -     |   1 |   4 |   1 |   0 |   0 | A    | none                      |
| ScanCoProc                |  1000 | -     |   3 |  10 |   2 |   0 |   2 | B    | card_table_compare        |
| SweepCoProc               |   800 | -     |   2 |   6 |   1 |   0 |   1 | A    | none                      |
| MvCoProc (ForwardingTable) |   700 | -     |   4 |   8 |   2 |   4 |   0 | B    | forwarding_chase_chain    |

### Frequency Estimate

- **Software model frequency class:** 0.8–1.2 GHz (45nm, generic)
- **Yosys synthesis estimate:** ~0.8–1.0 GHz (no PDK, worst-case PVT margins)
- **Real STA required:** YES — all above are structural estimates

---

## 4. Process Scaling Estimation

**Note:** Theoretical estimates. Area scales ~0.55× per node (not ideal 0.5×).
Frequency scales ~1.20× per node (not ideal 1.4×). SRAM scaling differs from logic.
Replace with PDK macro data for real tape-out estimates.

| Node | GCSubsys | GC Pure | Meta Cache | Total | Frontend | Backend |
|------|----------|---------|------------|-------|----------|---------|
| 45nm |     3500 GE |    22000 GE |    55000 GE |    60000 GE | 1.00 GHz | 0.90 GHz |
| 28nm |     3500 GE |    22000 GE |    55000 GE |    60000 GE | 1.00 GHz | 0.90 GHz |
| 14nm |     1925 GE |    12100 GE |    30250 GE |    33000 GE | 1.20 GHz | 1.08 GHz |
|  7nm |     1059 GE |     6655 GE |    16638 GE |    18150 GE | 1.44 GHz | 1.30 GHz |
|  5nm |      792 GE |     4979 GE |    12447 GE |    13578 GE | 1.57 GHz | 1.42 GHz |
|  3nm |      510 GE |     3205 GE |     8011 GE |     8740 GE | 1.80 GHz | 1.62 GHz |


> **工艺缩放说明:**
> - 45nm / 28nm 数据使用相同估算基数（保守占位），不体现工艺差异
> - 缩放指数 0.55×/代（面积）和 1.20×/代（频率）是理论模型，非 PDK 数据
> - SRAM 缩放系数不能等同逻辑缩放系数（SRAM 密度随代际变化更慢）
> - 所有数据不代表真实 tape-out 面积或频率
> - 真实工艺数据需要 PDK、SRAM macro、布局布线

### Breakdown by Logic Type

- **GC frontend control:** GCSubsystem (scoreboard, RB cache, WB FIFO, GC slots)
- **GC pure logic:** RootScanner, HeapWalker, CycleController, Scan/Sweep/Move coprocs
- **Metadata Cache SRAM:** ~4KB tag+data at 28nm, dominates area at all nodes

---

## 5. Power Estimation

**Note:** Dynamic power only (no leakage). Activity factors are estimated, not from VCD/SAIF. Real power requires PDK, P&R, clock tree, SRAM macros, and workload traces.

Formula: P = α × 0.5 × C × V² × f, with C~0.5fF/GE, V=1.0V, f=1.0GHz

| Load | GC% | Frontend | Meta Cache | StreamBuf | Backend | Total | Energy/evt | α | ActΔ% |
|------|-----|----------|------------|-----------|---------|-------|-----------|------|-------|
| Idle       |   0% | 0.018 mW | 0.138 mW | 0.003 mW | 0.110 mW | 0.268 mW | 0.00 pJ | 0.02 | -90% |
| Normal     |   5% | 0.088 mW | 0.688 mW | 0.015 mW | 0.550 mW | 1.340 mW | 16.75 pJ | 0.10 | -50% |
| Standard   |  10% | 0.175 mW | 1.375 mW | 0.030 mW | 1.100 mW | 2.680 mW | 16.75 pJ | 0.20 | +0% |
| HighLoad   |  20% | 0.306 mW | 2.406 mW | 0.053 mW | 1.925 mW | 4.690 mW | 14.66 pJ | 0.35 | +75% |
| Stress     |  30% | 0.438 mW | 3.438 mW | 0.075 mW | 2.750 mW | 6.700 mW | 13.96 pJ | 0.50 | +150% |

---

## 6. Hardware GC vs Software Barrier

**Note:** Rough estimates. Real speedup depends on JIT compiler, mutator behavior, heap size, and barrier implementation details.

| GC% | HW extra (min) | HW extra (max) | SW extra (min) | SW extra (max) | Speedup Range | Energy Save Range |
|-----|---------------|---------------|---------------|---------------|---------------|-------------------|
| 5% | 0.07 /cyc | 0.23 /cyc | 0.36 /cyc | 0.87 /cyc | 1.6×–12.8× | 4.0×–64.1× |
| 10% | 0.14 /cyc | 0.46 /cyc | 0.73 /cyc | 1.73 /cyc | 1.6×–12.8× | 4.0×–64.1× |
| 20% | 0.27 /cyc | 0.92 /cyc | 1.46 /cyc | 3.46 /cyc | 1.6×–12.8× | 4.0×–64.1× |

### Assumptions and Limitations

> **软件 barrier 对比仅做粗略估算，不声明真实 Java/Go/JVM/Golang 结果:**
> - Software WB barrier 假设 3～7 条额外指令（card mark、remember set insert 等）
> - Software RB miss 假设 6～14 条额外指令（load、GC check、forwarding table walk）
> - Software metadata 与 mutator 交织运行，同时竞争 L1 cache
> - Hardware GC 有专用后端，WB 零周期、RB 非阻塞、metadata 专用 pipeline
> - HW 能耗优势来自于后端在更小 datapath 和更低切换频率下运行
> - 真实速度提升取决于 JIT 编译器、mutator 行为、堆大小、barrier 实现细节
> - 此对比仅说明 Jasper 硬件 GC 相比软件 barrier 的理论优势范围，非实测结果

---

## 7. Conclusions

### 7.1 Standard GC — v0.1 Candidate?

**Yes — Standard GC is suitable as a stable baseline.**

- All 8/8 regression tests pass, 0 FAIL
- Single backend covers 0–20% GC without bottlenecks
- Metadata cache is the first bottleneck at ~25% GC
- WB zero-cycle, RB non-blocking semantics are invariant across all configurations

### 7.2 Standard Single Backend — Coverage

- **0–10% GC:** Fully steady (MCU, Lite, Standard profiles)
- **10–20% GC:** Steady for normal workloads; 20% GC is the practical upper bound
- **>25% GC:** Metadata cache saturates at ~25%

### 7.3 First Bottleneck

- **Metadata cache** is the first bottleneck across all configurations
- Saturation at ~25% GC event ratio
- WB and RB rates are well within their drain capacities

### 7.4 Standard GC — Target Applications

- **MCU / IoT:** ✅ Good fit. 在 GC event ratio≈5%、硬件 WB/RB 不阻塞前台、当前 Standard/Lite 参数假设下，MCU/IoT 场景的 GC 前台开销预计较低（<5% GC）。不等价于所有 MCU workload 的绝对结论。
- **Mobile:** ✅ Good fit; GC ~10–15%
- **Small Desktop:** ✅ Adequate; GC ~15%
- **Server / HPC:** ❌ Requires multi-backend for >20% GC

### 7.5 What Belongs to Experimental (not Standard)

- Multi-backend dispatch and merge
- Banked metadata cache pipeline
- Banked forwarding table
- Banked GC slots
- NUMA-aware GC cycle control
- Heap region partitioning
- L0 forwarding cache
- Priority aging in event pipeline

### 7.6 Experimental GC — Comparison Metrics

Experimental variants should be compared against this baseline using:

1. **Sustained throughput** at 10%, 20%, and 30% GC (req/cyc)
2. **Max GC ratio** before any bottleneck
3. **Metadata cache miss handling** (banked vs single)
4. **Sweep/Move starvation** (priority aging vs fixed)
5. **Area overhead** (cell count, gate count)
6. **Timing risk class** changes (A/B/C/D)
7. **Power per GC event** (pJ)

---

*Report generated by tools/gc_standard_baseline.py*
*Date: 2026-06-07*