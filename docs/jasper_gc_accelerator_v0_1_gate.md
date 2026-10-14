# JasperGC Accelerator v0.1 — Gate Criteria

> 版本：v0.1 Baseline
> 日期：2026-06-07

## 1. v0.1 Gate 必须满足

| 条件 | 标准 | 状态 |
|------|------|------|
| Control-plane PASS | CommandQueue, RegionScheduler, CompletionQueue 所有单元测试通过 | ✅ |
| 4-engine active path PASS | SCAN/SWEEP/REBUILD/COMPACT 均可通过 scheduler 被引擎接收和执行 | ✅ |
| 4-engine no-loss closure PASS | Pulse-mode protocol 下命令无丢失、完成无丢失、correlation_id 正确 | ✅ |
| Performance counters v0.1 PASS | 9 个计数器测试全部通过，计数器基于真实握手信号 | ✅ |
| Docs complete | 6 个设计文档 + 2 个报告 + gate 文档 + release notes | ✅ |
| No unexpected accelerator failures | 所有 V0_1_GATE 分类的测试全部 PASS | ✅ |
| All FUTURE boundary documented | 18 项未实现特性明确标记为 FUTURE | ✅ |

## 2. v0.1 Gate 不包含

以下特性不在 v0.1 gate 范围内：

| 特性 | 原因 |
|------|------|
| Continuous cmd_valid burst | 当前 scheduler 为纯组合逻辑，continuous burst 会导致 duplicate push；v0.1 仅 pulse-mode 已闭合 |
| Real compact relocation | Compact 是 READ_ONLY_MODEL，不含写回/forwarding |
| MemoryAccess write path | 当前仅 READ_ONLY |
| CoherentAccess | 需要完整的 cache coherence 协议 |
| Chiplet PHY | 超出当前 RTL 原型范围 |
| CXL/DPU/PCIe adapter | FUTURE_BOUNDARY，仅定义 adapter_type 枚举 |
| Multi-outstanding / out-of-order | 当前 global single-outstanding |
| Per-engine MemoryAccess | 4 引擎共享 1 个 MemoryAccess |
| Register map / APB / AXI-Lite | 当前无软件可访问寄存器 |
| Production signoff (PPA/Fmax/STA/CDC/DFT) | 未做综合/时序/DFT |

## 3. 测试分类

所有 accelerator 测试按以下分类：

| 分类 | 说明 | pytest 状态 |
|------|------|-------------|
| **V0_1_GATE** | v0.1 gate 必须通过的测试 | PASS |
| **LEGACY_HOLD** | 历史 stress 测试，使用旧 continuous-pulse 口径，不属于 v0.1 gate | xfail |
| **FUTURE** | 为未来功能预留的测试框架，当前不启用 | skip |
| **OUT_OF_SCOPE** | 非 accelerator 范围（如 gc_backend、gc_fabric） | 不评估 |

### 分类细则

#### V0_1_GATE

- 所有 pulse-mode protocol 下的命令/完成/内存路径测试
- 所有 performance counters 测试
- 所有 no-loss closure 测试
- 所有 rejection 测试（stale epoch、unsupported）

#### LEGACY_HOLD

- `test_jasper_gc_accelerator_4engine_stress.py` 中的 `test_16_mixed` 和 `test_no_missing_16`
- 原因：使用旧 continuous-pulse push（无 idle cycle），连续 16 条命令到 4 个 region 产生 region 别名，造成 BUSY 拒绝
- 这些测试反映了早期的验证方法，不适用于 pulse-mode 协议的门禁标准
- 标记为 `xfail`，不在 v0.1 gate 中计入失败

## 4. Regression 字段说明

`reports/jasper_gc_accelerator_v0_1_regression_matrix.csv` 中的 `gate` 字段：

```
phase,component,test_group,test_name,status,gate,tests,notes
v0.1,scan_engine,engine_unit,test_scan_counting,PASS,V0_1_GATE,1,
v0.1,integ_4engine_old,legacy_stress,test_16_mixed,HOLD,LEGACY_HOLD,1,not part of v0.1 pulse-mode gate
```

## 5. Baseline 声明

- v0.1 baseline 代表 **local regression only**，不是 CI signoff
- 所有测试在开发机（macOS）上运行，使用 Amaranth 0.5.8 模拟器
- 未在 FPGA 或硅片上验证
- 未做形式化验证
- 未做综合/时序分析
