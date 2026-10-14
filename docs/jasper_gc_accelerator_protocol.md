# JasperGC Accelerator — Command/Completion 协议

> v0.1 — Pulse-mode command protocol

## 1. Command 接口

| 信号 | 方向 | 宽度 | 说明 |
|------|------|------|------|
| `cmd_valid` | → accel | 1 | 命令有效 |
| `cmd_ready` | accel → | 1 | 加速器可接受命令 |
| `cmd_type` | → accel | 4 | 命令类型（见下方） |
| `cmd_correlation_id` | → accel | 16 | 用户关联 ID，原样返回到 completion |
| `cmd_epoch` | → accel | 8 | GC epoch 号，用于 stale epoch 检测 |
| `cmd_merge_domain` | → accel | 4 | 合并域标识 |
| `cmd_region_base` | → accel | 32 | 目标 region 基地址 |
| `cmd_region_size` | → accel | 32 | 目标 region 大小 |
| `cmd_priority` | → accel | 2 | 命令优先级 |
| `cmd_flags` | → accel | 8 | 扩展标志 |

### cmd_type 编码

| 值 | 类型 | v0.1 支持 |
|----|------|-----------|
| 0 | SCAN_REGION | ✅ |
| 1 | SWEEP_REGION | ✅ |
| 2 | COMPACT_REGION | ✅（READ_ONLY_MODEL） |
| 3 | REBUILD_METADATA | ✅ |
| 4 | CLEAN_REMEMBERED_SET | ❌ → UNSUPPORTED |
| 5 | PREFETCH_METADATA | ❌ → UNSUPPORTED |
| 6-8 | 预留 | ❌ → UNSUPPORTED |

## 2. Completion 接口

| 信号 | 方向 | 宽度 | 说明 |
|------|------|------|------|
| `comp_valid` | accel → | 1 | completion 有效 |
| `comp_ready` | → accel | 1 | 用户可接受 completion |
| `comp_status` | accel → | 3 | 完成状态（见下方） |
| `comp_correlation_id` | accel → | 16 | 原命令的关联 ID |
| `comp_epoch` | accel → | 8 | 原命令的 epoch |
| `comp_merge_domain` | accel → | 4 | 原命令的 merge domain |
| `comp_bytes_scanned` | accel → | 32 | 扫描字节数 |
| `comp_objects_scanned` | accel → | 32 | 扫描对象数 |
| `comp_live_objects` | accel → | 32 | 存活对象数 |
| `comp_dead_objects` | accel → | 32 | 死亡对象数 |
| `comp_bytes_moved` | accel → | 32 | 移动字节数（Compact READ_ONLY_MODEL 下为估算） |
| `comp_objects_moved` | accel → | 32 | 移动对象数 |
| `comp_metadata_updates` | accel → | 32 | metadata 更新数 |
| `comp_error_code` | accel → | 8 | 错误码 |

### comp_status 编码

| 值 | 状态 | 说明 |
|----|------|------|
| 0 | OK | 命令成功完成 |
| 1 | RETRY | 建议重试 |
| 2 | BUSY | region 繁忙 |
| 3 | ABORTED | stale epoch 中止 |
| 4 | ERROR | 内部错误 |
| 5 | UNSUPPORTED | 不支持的命令类型 |

## 3. Command 协议规则

### Pulse-mode（v0.1 唯一支持模式）

v0.1 使用 **pulse-mode command protocol**：

- 每条 command 使用 **单周期 `cmd_valid` 脉冲**；
- `cmd_valid` 置 1 一个周期后即清零；
- 等待 `cmd_ready` 置 1 后再发送下一条命令（中间至少一个 idle 周期）；
- 当前 no-loss closure 和所有验证均在此协议下完成。

```
# pulse-mode 时序示意
Cycle: 0  1  2  3  4  5  6  7
cmd_v: 1  0  1  0  1  0  1  0
cmd_r: 1  1  1  1  1  1  1  1
```

### continuous cmd_valid burst（FUTURE）

**continuous cmd_valid burst**（即 `cmd_valid` 连续保持 1、不插入 idle 周期）当前未闭合，标记为 **FUTURE**。原因：

- 当前 Scheduler 为纯组合逻辑（无内部命令寄存器），命令输入采用单周期脉冲协议；
- continuous cmd_valid 会导致 cmdq 重复 push 问题；
- 4-engine no-loss closure 未在 continuous cmd_valid 下验证。

## 4. Rejection 规则

### Stale epoch

- 当 `cmd_epoch < current_epoch` 时，命令被 **ABORTED**（status=3）；
- Rejected 命令 **不会进入 MemoryAccess**；
- Rejected 命令 **不会锁定 region**。

### Unsupported type

- 当 `cmd_type` 不被支持的 engine 处理时，命令被 **UNSUPPORTED**（status=5）；
- Rejected 命令 **不会进入 MemoryAccess**。

### Region busy

- 当目标 region 已被锁定且当前命令类型与锁类型冲突时，命令被 **BUSY**（status=2）；
- EXCLUSIVE 命令（SWEEP / REBUILD / COMPACT）需要 region 空闲；
- SHARED 命令（SCAN）可与其他 SCAN 共存；
- Region unlock 仅在 engine completion 被 CompletionQueue 接受后触发。

## 5. 数据路径

```
Host → cmdq → scheduler → engine → MemoryAccess(arbiter) → engine → compq → Host
                ↑                                  ↓
          region_lock                          mem_rsp_route
```

- cmdq 缓冲命令
- scheduler 验证 epoch / 权限 / region 锁
- engine 执行操作（可选经过 MemoryAccess）
- compq 汇总 completion
