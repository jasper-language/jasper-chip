# 4-Engine Memory No-Loss Stress / Closure

> Date: 2026-06-07
> Status: CLOSED — all 30 tests PASS
>
> Compact MemoryAccess Integration v0.1 → 4-engine active path BASIC PASS
> This phase → 4-engine no-loss CLOSURE

## Current Phase Conclusion

- SCAN / SWEEP / REBUILD / COMPACT 四个 region engine 均已通过 enable_memory=True 下的 no-loss closure；
- 4-input MemoryRequestArbiter 已覆盖 priority / outstanding / response hold / route / tag equality / no-missing / no-duplicate / no-overwrite / no-last_sel / single-outstanding 全部 18 项验证；
- 顶层 Mixed Burst 覆盖 **pulse-mode mixed burst**：每条 command 使用单周期 cmd_valid 脉冲并插入 idle cycle，随后统一 drain completion。该测试不是 sequential wait-for-completion，但也不是 continuous cmd_valid burst；
- Stale epoch / unsupported command 已确认被 scheduler 挡在 MemoryAccess 之外；
- Compact 仍明确标注为 READ_ONLY_MODEL；
- `accepted_mem_requests == routed_mem_responses` 在 top-level 统计中确认成立。

## Test Results (30 new tests, all PASS)

| Test Group | Tests | Status |
|-----------|-------|--------|
| Arbiter 4-engine priority | 4 | ✅ RTL_PASS |
| Arbiter outstanding blocks | 1 | ✅ RTL_PASS |
| Arbiter response backpressure | 2 | ✅ RTL_PASS |
| Arbiter response route correctness | 4 | ✅ RTL_PASS |
| Arbiter out_engine stable | 1 | ✅ RTL_PASS |
| Arbiter tag set equality | 1 | ✅ RTL_PASS |
| Arbiter no missing responses | 1 | ✅ RTL_PASS |
| Arbiter no duplicate responses | 1 | ✅ RTL_PASS |
| Arbiter priority no-overwrite route | 1 | ✅ RTL_PASS |
| Arbiter no last_sel routing | 1 | ✅ RTL_PASS |
| Arbiter single outstanding | 1 | ✅ RTL_PASS |
| Top-level single engine memory | 4 | ✅ RTL_PASS |
| Top-level 4-engine mixed burst | 1 | ✅ RTL_PASS |
| Top-level no-loss closure (8 cmd stats) | 1 | ✅ RTL_PASS |
| Top-level stale epoch rejected | 1 | ✅ RTL_PASS |
| Top-level unsupported rejected | 1 | ✅ RTL_PASS |
| Top-level cmd backpressure no-loss | 1 | ✅ RTL_PASS |
| Top-level comp backpressure no-loss | 1 | ✅ RTL_PASS |
| Top-level counting mode backward | 1 | ✅ RTL_PASS |
| Compact READ_ONLY_MODEL explicit | 1 | ✅ RTL_PASS |
| **Total** | **30** | **✅ ALL PASS** |

## Statistics (no-loss closure test)

No-loss closure with 8 commands across 4 engines:
- `injected_commands` = 8, `accepted_commands` = 8
- `completed_commands` = 8, `rejected_commands` = 0
- `in_flight_commands` = 0
- `accepted_mem_requests` = `routed_mem_responses` (confirmed via `dut._arb`)
- `missing_mem_responses` = 0
- `duplicate_mem_responses` = 0
- `completion_route_mismatches` = 0
- `extra_correlation_ids` = 0

## Limitations (explicitly documented)

- **MemoryAccess 仍是 latency/backpressure model**，不是真实 DRAM/HBM；
- **不是 CoherentAccess**；
- **不是 chiplet PHY**；
- **Compact 仍是 READ_ONLY_MODEL**，不是 real object relocation；
- **Arbiter 仍是 global single-outstanding**，限制吞吐；
- **Single-outstanding 意味着 4 个 engine 串行访问 MemoryAccess**，multi-outstanding / out-of-order 是 FUTURE；
- **CompletionQueue 仍为单队列**，4-engine burst 时 completion 可能成为瓶颈；
- **当前 Scheduler 是纯组合/无内部命令寄存器模型**，命令输入采用单周期脉冲协议；
- **continuous cmd_valid burst 尚未闭合**，标记为 **FUTURE**；
- **当前 no-loss closure 是 pulse-mode command protocol 下的 closure**，不是 continuous cmd_valid burst protocol 下的 closure；
- **下一阶段**进入 Accelerator Performance Counters + Observability v0.1。
