# Yosys Synthesis Report — GCSubsystem (Standard)

> 工具: Yosys 0.66 + ABC (generic stdcells.genlib)
> 设计: GCSubsystem + wbq SyncFIFO + mvq SyncFIFO
> 配置: Standard profile (gc_slots=16, rb_slots=4, rb_cache_ways=4, wb_depth=4, mv_depth=4)

## 综合结果

| 指标 | 数值 |
|------|------|
| 总 cell 数 | 862 |
| 总 FF 数 | 462 |
| 组合逻辑 | ~400 cells |
| MUX 数 | 332 |
| AND/OR/XOR | ~50 |

## Cell 类型分布

| Cell Type | Count |
|-----------|-------|
| DFFE_PP (D flip-flop with enable) | 440 |
| MUX | 332 |
| SDFFE_PP0P (scan DFF) | 14 |
| SDFF_PP0 (scan DFF) | 8 |
| NOT | 10 |
| AND | 21 |
| OR | 8 |
| XOR | 10 |
| XNOR | 5 |
| NAND | 3 |
| NOR | 2 |
| ANDNOT | 4 |
| ORNOT | 2 |

## 估算 ASIC 面积

假设 45nm 工艺标准单元:
- FF ≈ 5 GE (gate equivalent)
- MUX ≈ 3 GE
- AND/OR/XOR ≈ 2 GE
- NOT ≈ 1 GE

估算: 462 × 5 + 332 × 3 + 100 × 2 + 10 × 1 = 2,310 + 996 + 200 + 10 ≈ **~3,500 GE**

注: 这是 GCSubsystem 纯逻辑, 不含 metadata cache SRAM 和 stream buffer SRAM。

## 面积分层

| 层级 | 模块 | 门数 |
|------|------|------|
| GC Frontend | GCSubsystem (本报告) | ~3.5K GE |
| GC 纯逻辑 | + GCMemPolicy + RootScanner + HeapWalker + CycleCtrl + Scan/Sweep/Mv | ~20-25K GE |
| Standard 含 meta | + Metadata Cache 4KB (~32K GE) + Stream Buffer 256B | ~55-60K GE |
| Server 含 meta | + Metadata Cache 16KB (~127K GE) + Stream Buffer 512B | ~150-170K GE |

GCSubsystem 前台仅占 GC 总量的 ~5-10%, 适合高频 frontend。
Metadata Cache SRAM 是最大面积贡献者 (50-70%)。

## 关键结论

1. **862 cells 是纯 GC 前台 barrier 逻辑**, 不含 metadata cache SRAM
2. **462 个 FF 中约 256+184=440 来自两个 SyncFIFO** (wbq + mvq)
3. **332 个 MUX 主要来自 priority encoder 和 scoreboard**
4. Standard 配置 GCSubsystem 综合后约 **~3.5K GE** (ASIC 等效门)
5. **GC 纯逻辑整体 (不含 SRAM): ~20-25K GE**
6. **Standard 含 4KB meta cache: ~55-60K GE**

## 相对频率估计

基于 ABC 综合后的 cell 链深度 (非真实 STA, 无工艺库):
- GCSubsystem 组合逻辑最深层约为 8-10 级 MUX/AND
- 在 45nm 下乐观估计可达 500MHz-1GHz
- 在 28nm 下乐观估计可达 1-2GHz

> 本报告基于 Yosys/ABC 综合数据, 不替代工艺库 STA。
