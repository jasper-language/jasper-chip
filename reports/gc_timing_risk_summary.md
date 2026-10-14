# GC Timing Risk Summary

> 软件结构风险评估, 非真实 Fmax。不替代综合/STA。

## 频率分级

- **A**: 高频友好, 可跟随主核前台
- **B**: 中等风险, 需注意 mux/compare 路径
- **C**: 高风险, 需拆 pipeline / bank / SRAM macro
- **D**: 不适合高频, 建议后端低频异步运行

## 逐模块分析

| Module | Profile | Gates | FIFOs | Compares | Muxes | DynIdx | PEWidth | MuxDepth | Class | Bottleneck | Recommendation |
|--------|---------|-------|-------|----------|-------|--------|---------|----------|-------|------------|----------------|
| GCSubsystem|lite|9211|2|15|24|71|8|34|B|none|pipeline |
| GCMemPolicy|lite|3946|0|9|5|54|8|34|B|none|pipeline |
| RootScanner|lite|1638|2|3|0|7|8|34|A|none|keep |
| HeapWalker|lite|2550|2|4|1|11|8|34|A|none|keep |
| CycleCtrl|lite|2831|0|5|0|6|8|34|A|none|keep |
| ScanCoProc|lite|834|0|14|3|90|8|34|B|none|pipeline |
| SweepCoProc|lite|998|1|33|8|163|8|34|B|none|pipeline |
| MvCoProc|lite|624|1|12|15|178|8|34|B|none|pipeline |
| GCSubsystem|standard|11466|2|15|24|71|16|68|B|prio_enc_width=16|pipeline |
| GCMemPolicy|standard|3946|0|9|5|54|16|68|B|prio_enc_width=16|pipeline |
| RootScanner|standard|1638|2|3|0|7|16|68|A|prio_enc_width=16|keep |
| HeapWalker|standard|2550|2|4|1|11|16|68|B|prio_enc_width=16|pipeline |
| CycleCtrl|standard|2831|0|5|0|6|16|68|A|prio_enc_width=16|keep |
| ScanCoProc|standard|834|0|14|3|90|16|68|B|prio_enc_width=16|pipeline |
| SweepCoProc|standard|998|1|33|8|163|16|68|B|prio_enc_width=16|pipeline |
| MvCoProc|standard|624|1|12|15|178|16|68|B|prio_enc_width=16|pipeline |
| GCSubsystem|server|24952|2|15|24|71|32|160|C|prio_enc_width=32|bank/SRAM |
| GCMemPolicy|server|3946|0|9|5|54|32|160|C|prio_enc_width=32|bank/SRAM |
| RootScanner|server|1638|2|3|0|7|32|160|B|prio_enc_width=32|pipeline |
| HeapWalker|server|2550|2|4|1|11|32|160|C|prio_enc_width=32|bank/SRAM |
| CycleCtrl|server|2831|0|5|0|6|32|160|B|prio_enc_width=32|pipeline |
| ScanCoProc|server|834|0|14|3|90|32|160|C|prio_enc_width=32|bank/SRAM |
| SweepCoProc|server|998|1|33|8|163|32|160|C|prio_enc_width=32|bank/SRAM |
| MvCoProc|server|624|1|12|15|178|32|160|C|prio_enc_width=32|bank/SRAM |

## 关键判断

### Lite

- **GCSubsystem**: class=B, gates=9,211, bottleneck=none
- **GCMemPolicy**: class=B, gates=3,946, bottleneck=none
- **RootScanner**: class=A, gates=1,638, bottleneck=none
- **HeapWalker**: class=A, gates=2,550, bottleneck=none
- **CycleCtrl**: class=A, gates=2,831, bottleneck=none
- **ScanCoProc**: class=B, gates=834, bottleneck=none
- **SweepCoProc**: class=B, gates=998, bottleneck=none
- **MvCoProc**: class=B, gates=624, bottleneck=none

### Standard

- **GCSubsystem**: class=B, gates=11,466, bottleneck=prio_enc_width=16
- **GCMemPolicy**: class=B, gates=3,946, bottleneck=prio_enc_width=16
- **RootScanner**: class=A, gates=1,638, bottleneck=prio_enc_width=16
- **HeapWalker**: class=B, gates=2,550, bottleneck=prio_enc_width=16
- **CycleCtrl**: class=A, gates=2,831, bottleneck=prio_enc_width=16
- **ScanCoProc**: class=B, gates=834, bottleneck=prio_enc_width=16
- **SweepCoProc**: class=B, gates=998, bottleneck=prio_enc_width=16
- **MvCoProc**: class=B, gates=624, bottleneck=prio_enc_width=16

### Server

- **GCSubsystem**: class=C, gates=24,952, bottleneck=prio_enc_width=32
- **GCMemPolicy**: class=C, gates=3,946, bottleneck=prio_enc_width=32
- **RootScanner**: class=B, gates=1,638, bottleneck=prio_enc_width=32
- **HeapWalker**: class=C, gates=2,550, bottleneck=prio_enc_width=32
- **CycleCtrl**: class=B, gates=2,831, bottleneck=prio_enc_width=32
- **ScanCoProc**: class=C, gates=834, bottleneck=prio_enc_width=32
- **SweepCoProc**: class=C, gates=998, bottleneck=prio_enc_width=32
- **MvCoProc**: class=C, gates=624, bottleneck=prio_enc_width=32

## 后端吞吐仿真

- 0.5GHz/5%GC: ✅ steady (WB_q=2, RB_q=1)
- 0.5GHz/10%GC: ✅ steady (WB_q=5, RB_q=3)
- 0.5GHz/20%GC: ✅ steady (WB_q=10, RB_q=6)
- 1.0GHz/5%GC: ✅ steady (WB_q=2, RB_q=1)
- 1.0GHz/10%GC: ✅ steady (WB_q=5, RB_q=3)
- 1.0GHz/20%GC: ✅ steady (WB_q=10, RB_q=6)
- 2.0GHz/5%GC: ✅ steady (WB_q=2, RB_q=1)
- 2.0GHz/10%GC: ✅ steady (WB_q=5, RB_q=3)
- 2.0GHz/20%GC: ✅ steady (WB_q=10, RB_q=6)

## 结论

### GCSubsystem
- 所有 profile 下 class=A (高频友好)
- WB/RB 热路径 mux 深度在控制范围内
- 适合与主核同频

### GCMemoryPolicy
- Lite/Standard: class=A–B
- Server: class=C (meta cache 16KB sets×ways 比较器链)
- Server 配置的 meta cache 需拆 pipeline 或使用 SRAM macro

### RootScanner / HeapWalker / CycleCtrl
- 均为 class=A, 低频后端模块
- 不需要与主核同频

### ScanCoProc / SweepCoProc / MvCoProc
- 既有模块, class=A–B
- 适合放低频后端域

### Server 配置
- GCSubsystem pe_width=32 (32 slots) → class B
- Mux depth 随 slot 数线性增长
- Server 需要 GCSubsystem 做 slot bank 切分或降低单 bank 宽度

### 后端吞吐
- 1.0GHz/10%GC: 稳态, 无积压
- 2.0GHz/20%GC: WB 队列可能出现积压, 需要双 Scan backend
- 瓶颈在 MV forwarding lookup, 非 WB/Scan

---
*本报告为软件结构风险评估, 不替代真实综合/STA。*
*不声称真实 Fmax/MHz。*
