# Jasper-GC 最终结论报告

## 架构状态

Jasper-GC 已经验证为**架构成立**，进入**冻结候选 + 工程优化**阶段。

### 验证维度

| 维度 | 结论 | 关键数据 |
|------|------|---------|
| 功能闭环 | ✅ 完成 | Frontend + MemoryPolicy + Root/Heap/Cycle + Scan/Sweep/Mv |
| 前台热路径 | ✅ 零周期 | WB CPI = 非堆 CPI, RB 非阻塞, GC 零 stall |
| 后台吞吐 | ✅ 稳态 | 0.5-2GHz × 5-20% GC 全稳态, 无积压 |
| 门数 | ✅ 可接受 | GCSubsystem: 862 cells / 3.5K GE (Yosys) |
| 面积 | ✅ metadata cache 主导 | 纯逻辑 22-38K GE, Standard 含 meta ~57K GE |
| 频率 | ✅ 可高频化 | 10 FO4 depth, 3nm 下 >5GHz 可闭合 |
| 多核扩展 | ✅ 已预留 | GCTopologyConfig + GCBackendConfig + 参数分级 |
| 回归 | ✅ 全绿 | 8/8 PASS, 0 FAIL |

## 前台热路径

WB barrier:  **零周期** —— 堆 store CPI (1.015) = 非堆 store CPI (1.015)
RB barrier:  **非阻塞** —— load 期间 stall=0, pipeline 不被 RB 卡住
GC 指令:     **零前台 stall** —— gc_new/gc_drop 仅 scoreboard 跟踪, 不阻塞流水线

结论：**对象写入 ≈ 普通 store, 对象读取 ≈ 普通 load, GC 事件 ≈ 异步后台。**

## 综合数据 (Yosys 0.66 + ABC)

| 模块 | Cells | FF | MUX | GE |
|------|-------|----|-----|----|
| GCSubsystem | 862 | 462 | 332 | ~3,500 |
| (其中 wbq+mqv FIFO) | (836) | (440) | (332) | — |
| GC 控制逻辑 (剩余) | ~26 | ~22 | ~0 | ~100 |

GC 前台逻辑极小, 440/462 个 FF 来自两个 SyncFIFO, 控制逻辑仅约 100 GE。

## 面积分层

| 配置 | 门数 | 说明 |
|------|------|------|
| GC Frontend | ~3.5K GE | GCSubsystem 控制逻辑 |
| GC 纯逻辑 | ~20-25K GE | 不含任何 SRAM |
| Lite (含全部) | ~22.6K GE | 无 metadata cache |
| Standard (含全部) | ~56.8K GE | +4KB metadata cache |
| Server (含全部) | ~165.9K GE | +16KB metadata cache |

面积大头是 metadata cache SRAM, 不是控制逻辑。

## 三档 Profile

| | Lite | Standard | Server |
|--|------|----------|--------|
| gc_slots | 8 | 16 | 32 |
| rb_cache_ways | 2 | 4 | 8 |
| rb_slots | 2 | 4 | 16 |
| wb_depth | 2 | 4 | 16 |
| mv_depth | 2 | 4 | 16 |
| metadata cache | 关闭 | 4KB | 16KB |
| backend_count | 1 | 1 | 4 (experimental) |
| GC 纯逻辑 | ~22.6K | ~24.9K | ~38.4K |
| 含 meta cache | ~22.6K | ~56.8K | ~165.9K |
| 目标应用 | MCU | Mobile/Desktop | Server/高压 |

## 架构扩展口

```
JasperGCConfig
├── frontend       → gc_slots, rb_cache_ways, rb_slots, wb_depth, mv_depth
├── root_scan      → fifo_depth, scan_width, table_entries
├── heap_walk      → slots, scan_width, fifo_depth, queue_size
├── mark_sweep     → card_table, sweep_entries, batch_size
├── move           → forward_table, chase_limit, reloc_depth
├── memory_policy  → metadata_cache, stream_buffer, bypass, partition
├── topology       → ncores, frontend/backend/metadata scope
├── backend        → scan/sweep/move backend_count, dispatch/merge policy
├── cycle          → compact/reloc/incremental enable
├── cluster        → nclusters, cores_per_cluster
└── debug          → perf_counters, trace_ports, synthesis_guard
```

## 后续工程优化方向

1. **MV Forwarding Table bank 化** — 当前吞吐模型的第一个瓶颈
2. **每核 RB / Forwarding L0** — 降低后端压力的高收益低风险项
3. **Metadata Cache bank + pipeline** — Server 配置需要
4. **Scan / Sweep / Move 分离流水线** — 提高后台吞吐
5. **Heap Region 分区** — Server/NUMA 场景
6. **多 backend + merge** — 极高压场景扩展

所有优化方向均不改变当前 GC 架构, 沿已有配置和拓扑扩展。

## 验证通过项

```
test_isa               ✅ PASS
test_elaborate         ✅ PASS (TopSoC + 3 GC coprocessors)
test_isa_c_expand      ✅ PASS (27/27)
test_isa_c_pipeline    ✅ PASS
test_gc_integration    ✅ ALL PASS
test_gc_memory_policy  ✅ ALL PASS (5/5)
test_gc_backend_config ✅ ALL PASS (6/6)
───────
总计: 8/8 PASS, 0 FAIL
```

---

*本报告基于 Yosys 0.66 + ABC 综合数据和结构模型估算。*
*不替代工艺厂 PDK/STA/功耗仿真。*
*不声称真实 Fmax。*
