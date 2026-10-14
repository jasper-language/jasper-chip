# JasperGC Accelerator v0.1 — Limitations

> 所有未实现特性均明确标记为 FUTURE，不列入 v0.1 交付范围。

## 功能性限制

| 特性 | v0.1 状态 | 说明 |
|------|-----------|------|
| CoherentAccess | **FUTURE** | 当前 MemoryAccess 不是 coherent memory model |
| Chiplet PHY | **FUTURE** | 当前为 CPU-package 级 RTL，不含 PHY |
| CXL adapter | **FUTURE_BOUNDARY** | 已预留 adapter_type 字段，但未实现适配器逻辑 |
| DPU adapter | **FUTURE_BOUNDARY** | 同上 |
| PCIe adapter | **FUTURE_BOUNDARY** | 同上 |
| Real compact relocation | **FUTURE** | Compact 当前是 READ_ONLY_MODEL |
| Forwarding-table rewrite | **FUTURE** | compaction 需要更新 forwarding metadata |
| MemoryAccess write path | **FUTURE** | 当前仅支持 READ_ONLY |
| Multi-outstanding arbiter | **FUTURE** | 当前 global single-outstanding |
| Out-of-order response | **FUTURE** | 当前 in-order only |
| Per-engine MemoryAccess | **FUTURE** | 当前 4 引擎共享一个 MemoryAccess |
| Continuous cmd_valid burst | **FUTURE** | 当前仅 pulse-mode 闭合 |
| Register map / APB / AXI-Lite | **FUTURE** | 当前无软件可访问寄存器 |
| Performance counters readout | **FUTURE** | 当前仅 debug signal 可见 |
| Production PPA | **FUTURE** | 未做逻辑综合签核 |
| Fmax / STA | **FUTURE** | 未做静态时序分析 |
| CDC / DFT | **FUTURE** | 未做跨时钟域/可测试性设计 |

## 为什么这些现在不做

### 问题空间控制

v0.1 的核心目标是在 **可控的问题空间内** 闭合 accelerator 的控制面和内存模式 active path。添加上述任何特性都会显著扩大验证状态空间：

- CoherentAccess 需要完整的 cache coherence 协议
- Real relocation 需要精确的堆布局跟踪
- Write path 需要验证数据完整性
- Chiplet PHY 需要物理层时序建模

### 阶段性目标

v0.1 的边界定义基于以下阶段性原则：

1. **先控制面，后数据面**：CommandQueue、Scheduler、CompletionQueue 构成控制面；MemoryAccess + engines 构成内存面。数据面（real relocation / write path）留到下一阶段。
2. **先 core，后 adapter**：主线为 CPU-package chiplet；CXL/DPU/PCIe 超出主线边界。
3. **先 single-outstanding，后 multi**：single-outstanding 简化了内存仲裁验证；multi 增加 out-of-order 和死锁问题。
4. **先 pulse-mode，后 continuous burst**：pulse-mode protocol 降低了 scheduler/sched_hold 的验证难度。

### 适配器状态

CXL/DPU/PCIe 适配器已

在设计中被标记为 `FUTURE_BOUNDARY`：
- `AcceleratorAdapterType` 枚举已包含 `CHIPLET`、`CXL`、`DPU`、`PCIE`
- `adapter_type` 信号已连到顶层接口，验证通过
- 适配器 RTL 未实现，仅在 chiplet 模式下验证

## 当前阶段已验证的边界

| 边界 | v0.1 状态 |
|------|-----------|
| Pulse-mode command no-loss | ✅ 闭合 |
| 4-engine single-outstanding | ✅ 闭合 |
| Stale epoch rejection | ✅ 闭合 |
| Unsupported type rejection | ✅ 闭合 |
| Completion backpressure no-loss | ✅ 闭合 |
| Memory req/rsp no-loss | ✅ 闭合 |
| enable_memory=False backward compat | ✅ 闭合 |
| Counting-mode (no memory) | ✅ 闭合 |
