# JasperGC Accelerator — Memory 模型

> v0.1 — Latency/backpressure READ_ONLY model

## 1. MemoryAccess

当前 `MemoryAccess` 是 **latency/backpressure 模型**，不是真实 DRAM/HBM。

### 特性

- 可配置读延迟 (`read_latency`)：4 个请求-响应周期
- 可配置队列深度 (`queue_depth`)：8
- 请求队列（FIFO）+ 移位寄存器流水线
- 响应支持 hold（`rsp_ready=0` 时保持输出）
- **READ_ONLY**：仅支持读请求，忽略写请求
- 不模拟真实内存时序（refresh / page activate / bank conflict）

### 边界

- 不是 CoherentAccess
- 不是 chiplet PHY
- 不模拟真实 DRAM 带宽
- 不模拟 NUMA 延迟
- 不模拟 ECC / RAS

### 用途

- 验证 request/response 路径的正确性
- 验证 backpressure 下的 no-loss
- 验证 single-outstanding 串行化行为
- 验证 4-engine 共享 MemoryAccess 的仲裁和路由

## 2. MemoryRequestArbiter

| 参数 | 值 |
|------|-----|
| 输入数 | 4（compact / mre / sweep / scan） |
| 优先级 | compact > mre > sweep > scan |
| 并发 | global single-outstanding |
| 响应路由 | 基于 `out_engine`（在请求接受时锁存） |

### 优先级规则

```
compact > mre > sweep > scan
```

- 当多个 engine 同时 `req_valid=1` 时，高优先级请求被接受
- 已接受请求的响应路由由 `out_engine` 寄存器决定（在请求接受时锁存）
- Priority **不会覆盖**已接受请求的路由
- 不使用 `last_sel` 进行响应路由

### Single-outstanding 行为

- 仅当 `outstanding=0` 时可接受新请求
- `outstanding` 在请求接受时置 1，在响应接受时清 0
- 当前是 **global single-outstanding**（所有 engine 共享一个 outstanding 槽位）
- Multi-outstanding / out-of-order 为 **FUTURE**

## 3. Compact 内存模型

`CompactEngine` 在 v0.1 中为 **READ_ONLY_MODEL**：

- 进入 MemoryAccess active path
- 每个 step 执行一次 `mem_req → mem_rsp`（类似 SCAN）
- **不执行真实对象 relocation**（不写回移动后的位置）
- **不更新 forwarding table**
- **不修改真实 heap layout**
- `comp_bytes_moved` / `comp_objects_moved` 为估算值，不反映真实移动

## 4. 当前限制

- MemoryAccess 不验证真实内存一致性
- 不支持写回
- 不支持原子操作
- 不支持 cache coherence
- 不支持 out-of-order 响应
