# JasperGC Accelerator — Performance Counters

> v0.1 — Observability only, no register map

## 概述

性能计数器提供 accelerator 内部活动的可见性，用于定位瓶颈。当前为 **observability v0.1**：

- 32-bit saturating 计数器（达到 `0xFFFFFFFF` 后停止计数，不回绕）
- 通过 RTL debug 信号暴露（无寄存器映射/无 APB/AXI-Lite）
- 不改变 ready/valid 时序
- 不作为 PPA / Fmax / throughput signoff

## 计数器列表

### Command 路径

| 计数器 | 宽度 | 触发条件 | 说明 |
|--------|------|----------|------|
| `cmd_accepted` | 32 | `cmd_valid & cmd_ready` | 被加速器接受的命令数 |
| `cmd_backpressure` | 32 | `cmd_valid & !cmd_ready` | 命令因 cmdq 满被阻塞的周期数 |
| `cmd_stall_max` | 32 | `cmd_valid & !cmd_ready` | 连续阻塞的最大周期数（max tracker） |
| `cmd_rejected` | 32 | scheduler reject | 被 scheduler 拒绝的命令数 |

### Completion 路径

| 计数器 | 宽度 | 触发条件 | 说明 |
|--------|------|----------|------|
| `comp_accepted` | 32 | `comp_valid & comp_ready` | 被用户接受 completion 数 |
| `comp_backpressure` | 32 | `comp_valid & !comp_ready` | completion 被用户阻塞的周期数 |
| `comp_stall_max` | 32 | `comp_valid & !comp_ready` | 连续阻塞的最大周期数 |
| `comp_route_mismatch` | 32 | — | **v0.1 NOT WIRED**，恒为 0 |

### Memory 路径

| 计数器 | 宽度 | 触发条件 | 说明 |
|--------|------|----------|------|
| `mem_req_accepted` | 32 | arbiter `mem_req_valid & mem_req_ready` | 发送到 MemoryAccess 的请求数 |
| `mem_rsp_accepted` | 32 | arbiter `mem_rsp_valid & mem_rsp_ready` | 从 MemoryAccess 接收的响应数 |
| `mem_req_backpressure` | 32 | `mem_req_valid & !mem_req_ready` | 请求被 MemoryAccess 阻塞的周期数 |
| `mem_rsp_backpressure` | 32 | `mem_rsp_valid & !mem_rsp_ready` | 响应被 engine 阻塞的周期数 |
| `mem_stall_max` | 32 | `mem_req_valid & !mem_req_ready` | 连续阻塞的最大周期数 |
| `outstanding_block` | 32 | `arb_outstanding & any_engine_req` | 因 single-outstanding 被阻塞的周期数 |

### Per-engine 计数器

| 计数器 | 触发事件 |
|--------|----------|
| `{e}_cmd_accepted` | Engine 从 scheduler 接收命令（`_to_{e}` 脉冲） |
| `{e}_mem_req_accepted` | Engine 的 memory 请求被 arbiter 接受 |
| `{e}_comp_accepted` | Engine 的 completion 被 compq 接受 |
| `{e}_busy` | Engine 处于非 IDLE 状态的周期数 |
| `{e}_mem_stall` | Engine 处于 busy 且 `req_valid & !req_ready` 的周期数 |

其中 `{e} ∈ {scan, sweep, rebuild, compact}`。

### Reject 计数器

| 计数器 | 来源 |
|--------|------|
| `stale_epoch_reject` | scheduler `_reject_stale` |
| `unsupported_reject` | scheduler `_reject_unsupp` |
| `region_busy_reject` | scheduler `_reject_busy` |

## 已知限制

- **comp_route_mismatch**：v0.1 未 wiring，恒为 0。无法区分 completion 来源，不能作为真实 route mismatch 统计
- **outstanding_block**：pulse-mode protocol 下通常为 0（scheduler 串行化），continuous cmd_valid / multi-outstanding 压力留到 FUTURE
- 当前无寄存器映射，不可通过 APB/AXI-Lite 访问
- 不支持计数器 snapshot / clear-on-read
- 不支持事件触发（如 completion 时拍照）
