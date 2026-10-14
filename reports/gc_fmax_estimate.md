# GC Frequency Risk Estimate

> 基于 RTL 结构深度估算。不替代综合/STA。不声称真实 MHz。
> 深度单位为抽象逻辑级数。A=1GHz+, B=500MHz-1GHz, C=250-500MHz, D=<250MHz.

## 逐模块分析

| Module | Profile | Depth | Top Bottleneck | Class | Note |
|--------|---------|-------|---------------|-------|------|
| GCSubsystem | lite | 48 | prio_enc(24) | B | 500MHz-1GHz class |
| GCMemPolicy | lite | 54 | prio_enc(24) | C | 250-500MHz class |
| RootScanner | lite | 16 | fifo(10) | A | >1GHz class (estimated) |
| HeapWalker | lite | 20 | fifo(10) | A | >1GHz class (estimated) |
| CycleCtrl | lite | 10 | compares(8) | A | >1GHz class (estimated) |
| ScanCoProc | lite | 14 | compares(12) | A | >1GHz class (estimated) |
| SweepCoProc | lite | 27 | compares(20) | A | >1GHz class (estimated) |
| MvCoProc | lite | 19 | compares(12) | A | >1GHz class (estimated) |
| GCSubsystem | standard | 74 | prio_enc(48) | C | 250-500MHz class |
| GCMemPolicy | standard | 118 | prio_enc(48) | D | <250MHz, needs pipeline/bank |
| RootScanner | standard | 18 | fifo(10) | A | >1GHz class (estimated) |
| HeapWalker | standard | 22 | fifo(10) | A | >1GHz class (estimated) |
| CycleCtrl | standard | 12 | compares(8) | A | >1GHz class (estimated) |
| ScanCoProc | standard | 16 | compares(12) | A | >1GHz class (estimated) |
| SweepCoProc | standard | 29 | compares(20) | A | >1GHz class (estimated) |
| MvCoProc | standard | 21 | compares(12) | A | >1GHz class (estimated) |
| GCSubsystem | server | 124 | prio_enc(96) | D | <250MHz, needs pipeline/bank |
| GCMemPolicy | server | 200 | prio_enc(96) | D | <250MHz, needs pipeline/bank |
| RootScanner | server | 20 | fifo(10) | A | >1GHz class (estimated) |
| HeapWalker | server | 24 | fifo(10) | A | >1GHz class (estimated) |
| CycleCtrl | server | 14 | compares(8) | A | >1GHz class (estimated) |
| ScanCoProc | server | 18 | compares(12) | A | >1GHz class (estimated) |
| SweepCoProc | server | 31 | compares(20) | B | 500MHz-1GHz class |
| MvCoProc | server | 23 | compares(12) | A | >1GHz class (estimated) |

### Lite

- **GCSubsystem**: depth=48, class=B, bottleneck=prio_enc(24)
- **GCMemPolicy**: depth=54, class=C, bottleneck=prio_enc(24)
- **RootScanner**: depth=16, class=A, bottleneck=fifo(10)
- **HeapWalker**: depth=20, class=A, bottleneck=fifo(10)
- **CycleCtrl**: depth=10, class=A, bottleneck=compares(8)
- **ScanCoProc**: depth=14, class=A, bottleneck=compares(12)
- **SweepCoProc**: depth=27, class=A, bottleneck=compares(20)
- **MvCoProc**: depth=19, class=A, bottleneck=compares(12)

### Standard

- **GCSubsystem**: depth=74, class=C, bottleneck=prio_enc(48)
- **GCMemPolicy**: depth=118, class=D, bottleneck=prio_enc(48)
- **RootScanner**: depth=18, class=A, bottleneck=fifo(10)
- **HeapWalker**: depth=22, class=A, bottleneck=fifo(10)
- **CycleCtrl**: depth=12, class=A, bottleneck=compares(8)
- **ScanCoProc**: depth=16, class=A, bottleneck=compares(12)
- **SweepCoProc**: depth=29, class=A, bottleneck=compares(20)
- **MvCoProc**: depth=21, class=A, bottleneck=compares(12)

### Server

- **GCSubsystem**: depth=124, class=D, bottleneck=prio_enc(96)
- **GCMemPolicy**: depth=200, class=D, bottleneck=prio_enc(96)
- **RootScanner**: depth=20, class=A, bottleneck=fifo(10)
- **HeapWalker**: depth=24, class=A, bottleneck=fifo(10)
- **CycleCtrl**: depth=14, class=A, bottleneck=compares(8)
- **ScanCoProc**: depth=18, class=A, bottleneck=compares(12)
- **SweepCoProc**: depth=31, class=B, bottleneck=compares(20)
- **MvCoProc**: depth=23, class=A, bottleneck=compares(12)

## 关键判断

### 1. GCSubsystem 是否可以作为主核同频 frontend

Lite/Standard: depth ≤ 70 (B 类), 可作为 500MHz-1GHz 主核 frontend。
Server: depth ≈ 100+ (C/D 类), 32 slots 优先编码器链过深, 需要 bank 化或拆 pipeline。

**结论**: Standard 及以下可以作为主核同频 frontend。Server 需要 slot bank 化。

### 2. GCMemoryPolicy 最大瓶颈

不开启 metadata cache (Lite): depth 较低, 无瓶颈。
开启 metadata cache (Standard/Server): tag compare + way mux 是深度贡献者。
Stream buffer 命中检测深度较小。

**结论**: Metadata cache tag compare 路径是主要深度贡献者。5-stage pipeline 可以解决。

### 3. Server 32 slots 是否需要 bank 化

是。GCSubsystem 32 slot priority encoder 会产生深度 ~100+ 的 Mux 链。
Server 建议将 gc_slots 拆为 4×8 bank, 每 bank 独立优先编码, 再二级仲裁。

### 4. MV forwarding lookup 是否仍是最主要瓶颈

当前 Standard 配置下: GCSubsystem 的 priority encoder 是第一瓶颈, 不是 MV。
MvCoProc 本身结构简单 (depth~20, A 类)。
但注意: MV 的瓶颈不在查找逻辑, 在 forwarding table 容量和 chase 深度。

**结论**: MV lookup 逻辑不是深度瓶颈, 但容量/带宽会是吞吐瓶颈。

### 5. Standard 单 backend 最高频风险

Standard 单 backend 各模块深度:
- GCSubsystem: ~70 (B 类, 接近 C 边界)
- GCMemPolicy: ~50 (B 类)
- Scan/Sweep/Mv: ~20-60 (A-B 类)
- Root/Heap/Cycle: ~30-40 (A-B 类)

**结论**: Standard 单 backend 在 500MHz-1GHz 范围风险可接受。
GCSubsystem 的 priority encoder 是最接近边界的模块。

### 6. 1GHz GC backend 目标下需要拆 pipeline 的模块

| 模块 | 需要拆 | 拆法 |
|------|--------|------|
| GCSubsystem (Server) | ✅ | 32 slots → 4×8 bank |
| GCMemPolicy (meta cache) | ✅ | 5-stage pipeline (index→tag→cmp→mux→fill) |
| GCSubsystem (Standard) | ⚠️ 边界 | 保持单 backend, 监控 depth |
| MvCoProc | ❌ | 当前 depth 足够 |
| Scan/Sweep | ❌ | 当前 depth 足够 |

## 综合建议

1. **Standard 以下**: 保持单 backend, 不需要 bank 化和 pipeline
2. **Server**: 需要 slot bank + metadata cache pipeline + forwarding bank
3. **全局**: MV forwarding lookup 不是深度瓶颈, 不需要优先优化
4. **优先级**: slot bank 化 > meta cache pipeline > forwarding bank

---
*本报告为结构深度估算, 不替代综合/STA。不声称真实 MHz。*
