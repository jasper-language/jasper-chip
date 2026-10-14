# JasperGC Accelerator v0.1 — Design Rationale

## 1. 为什么 Core 处理 hot path，Accelerator 处理 cold path

Jasper-GC 的 hot path（write barrier、read barrier、gc_fire）对延迟极度敏感，必须在 Core 内以最简逻辑完成。Cold path 操作（scan、sweep、rebuild、compact）涉及大量遍历和统计，适合卸载到独立加速器。

分离的好处：

- Core 保持精简和可预测延迟
- Accelerator 可以独立优化和测试
- Accelerator 不影响 hot path 的 WB/RB/fire 时序

## 2. 为什么主线是 CPU-package / chiplet accelerator

Chiplet 是当前最成熟的 GC 加速器部署形式：

- 与 CPU 封装在同一 package 内，延迟可控
- 通过 chiplet 接口（die-to-die）与 Core 通信
- 不需要完整的 CXL/PCIe 协议栈
- v0.1 聚焦 chiplet 场景，后续可扩展到 CXL/DPU/PCIe

## 3. 为什么 CXL/DPU/PCIe 是 FUTURE_BOUNDARY

- CXL.mem 需要 coherent memory 语义支持（先于 CoherentAccess）
- DPU 需要 SmartNIC 集成和独立 DMA 路径
- PCIe 需要完整 PCIe 事务层和 DMA 描述符管理
- 这些适配器层超出当前 accelerator 控制面验证范围

## 4. 为什么 MemoryAccess 先做 READ_ONLY latency/backpressure model

- v0.1 的核心目标是验证 **控制面 + 内存请求/响应路径**
- Write path 需要真正的数据缓冲区、写合并策略、一致性协议
- Latency/backpressure model 足够验证 backpressure、no-loss、arbiter 行为
- 写路径留到 v0.2（伴随 real relocation）

## 5. 为什么先 single-outstanding，而不是 multi-outstanding

- Single-outstanding 将内存仲裁简化为状态机
- 不需要 tag 管理、out-of-order 响应追踪、deadlock 避免
- 验证状态空间更小，适合 v0.1 闭合
- Multi-outstanding 列在下一阶段候选（性能优化需求驱动）

## 6. 为什么先做 3-engine，再接 Compact，再做 4-engine no-loss

渐进式集成策略：

1. **3-engine**（scan/sweep/rebuild）：验证多 engine 共享 scheduler + arbiter + compq 的基础机制
2. **Compact**（4th engine）：验证第 4 个 engine 的完整接入（scheduler routing、arbiter priority、compq mux）
3. **4-engine no-loss**：验证所有 engine 同时处于 memory 模式时的完整路径、仲裁、优先级、背压

每一步都有独立的 no-loss closure。

## 7. 为什么 Compact 先是 READ_ONLY_MODEL

- 真实 compact 需要：对象遍历 → relocation → forwarding-table 更新 → 原子写回
- 写回操作需要 MemoryAccess write path（FUTURE）
- Forwarding-table 更新需要 coherent 访问或 fence
- READ_ONLY_MODEL 允许先闭合 control+memory read path，再处理 write/coherence

## 8. 为什么 v0.1 使用 pulse-mode command protocol

连续 cmd_valid burst 在 pulse-mode 基础上引入以下风险：

- cmdq 重复 push（scheduler 组合逻辑导致 duplicate）
- scheduler 的纯组合特性（无内部命令寄存器）
- sched_hold 与 cmdq pop 的时序耦合

Pulse-mode 通过插入 idle 周期消除了这些风险，验证覆盖了所有 control+memory 路径。Continuous burst 的验证列在 FUTURE。

## 9. 为什么 continuous cmd_valid burst 暂缓

- Continuous burst 需要 scheduler 增加内部命令寄存器（改为 1-deep pipeline stage）
- 当前 scheduler 是纯组合逻辑，`busy=0` 始终
- 改写 scheduler 会影响所有现有验证
- v0.1 优先保证 pulse-mode 下的完整性

## 10. 为什么 performance counters 是 observability，不是 signoff

- v0.1 counters 仅通过 debug signal 暴露，无软件可见 API
- Counters 是 saturating（不回绕），不适用于长期运行监控
- 不可通过 APB/AXI-Lite 读取
- 适用于 RTL 验证阶段的瓶颈定位，不适用于芯片级性能分析

## 11. 为什么 v0.1 后再考虑 CoherentAccess / real relocation

v0.1 已闭合：

- 控制面（cmdq、scheduler、compq）
- 内存读路径（4-engine through arbiter）
- No-loss 验证（pulse-mode protocol）
- 性能计数器基础框架

这些构成了加速器的 **稳定基线**。在此基础上增加：

- **CoherentAccess**：需要 coherent memory interface 和 cache line 管理
- **Real compact relocation**：需要 write path 和 forwarding table
- **Write path**：需要数据缓冲和写合并

每次添加都相当于一个新的语义层，v0.1 为这些扩展提供了已验证的启动平台。
