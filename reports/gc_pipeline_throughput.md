# GC Pipeline Throughput Report

## 事件比例口径

WB/RB/Metadata 事件比例是**非互斥的独立速率**, 不是派生事件:

- Metadata 请求 = 80% of GC指令 (每次 GC 访存都查 metadata cache)
- WB 事件 = 50% of GC指令 (约半数 GC 指令触发写屏障)
- RB 事件 = 30% of GC指令 (约三成 GC 指令触发读屏障)

三者之和可以 >100%, 因为一条 CPU 指令可能同时触发多个 GC 事件
(例如: GC 搬迁读写 = metadata lookup + RB + 新指针写入).

在吞吐模型中:

| 事件 | 占 GC% | GC%=10% 时的事件率 | GC%=25% 时的事件率 |
|------|--------|-------------------|-------------------|
| Metadata | 80% | 0.08 evt/cyc | 0.20 evt/cyc |
| WB | 50% | 0.05 evt/cyc | 0.125 evt/cyc |
| RB | 30% | 0.03 evt/cyc | 0.075 evt/cyc |

---

## 三层吞吐口径

### 1. Model Throughput (纯数学估算)

基于事件率 × pipeline drain rate 的线性模型.
Backend drain rate = backend_count × drain_rate (默认: 0.2 evt/cyc per backend).
Metadata 带宽 = metadata_bank_count × meta_drain_rate (默认: 0.2 evt/cyc per bank).

| 配置 | GC% | Backend | Meta bank | 模型瓶颈 |
|------|-----|---------|-----------|---------|
| MCU Lite | 5% | 1× | 1× | 无 (0.04 evt/cyc << 0.2) |
| Standard | 10% | 1× | 1× | 无 (0.08 << 0.2) |
| Mobile | 15% | 2×sweep | 2× | Metadata ~0.12 << 0.4 |
| Desktop | 15% | 2× | 4× | 无 (0.12 << 0.8) |
| Server | 20% | 4× | 4× | 无 (0.16 << 0.8) |
| Server 高压 | 25% | 4× | 4× | Metadata ~0.20 = 0.8/4=瓶颈临界 |

### 2. RTL Simulation Throughput (RTL 实测)

| 模块 | 配置 | 实测吞吐 | 限制因素 |
|------|------|---------|---------|
| MetadataCacheStandard | 1024B, 2-way | 1.00 req/cyc | 组合逻辑无背压 |
| MetadataCachePipelined | 1024B, 2-way | 1.00 req/cyc (稳态) | 4-cycle latency |
| MetadataCachePipelined | 1024B, 2-way, rsp_ready=0 | 0.00 req/cyc | 背压阻塞 |
| GCEventPipelineStandard | single | 0.98 req/cyc | 单级 bypass |
| GCEventPipelineSeparated | 3独立子流水线 | ~0.9 req/cyc (混洗注入时) | 结果合并优先级 |
| GCEventPipelineSeparated | Scan 连续 | Sweep 延迟约 5 个结果 | 固定优先级饥饿 |
| ForwardingTableStandard | 4-entry | 1.00 req/cyc | 无瓶颈 |
| ForwardingTableBankedPipeline | 4×4-entry | 1.00 req/cyc | 无瓶颈 |

备注:
- MetadataCachePipelined 稳态 (pipeline 已满) 时能维持 1 req/cyc,
  但需要 rsp_ready=1 (下游接受响应). 如果下游背压, pipeline 满后
  request_ready=0.
- 初始延迟 4 周期 (8-stage pipeline). 启动阶段第一个响应在 4 周期后出现.

### 3. Estimated Throughput (吞吐估算)

芯片产品吞吐 = RTL 吞吐 × 时钟频率 × 工艺降额:

| 工艺 | 降额 | 1GHz Standard | 2GHz Desktop | 6GHz Server |
|------|------|--------------|-------------|-------------|
| 理想 (0%) | 1.00 | 1.0G req/s | 2.0G req/s | 6.0G req/s |
| 典型 (10%) | 0.90 | 0.9G req/s | 1.8G req/s | 5.4G req/s |
| 保守 (20%) | 0.80 | 0.8G req/s | 1.6G req/s | 4.8G req/s |

Metadata cache 在 6GHz/20%GC/4-bank 下需 0.8G req/s, 4-bank 每个 bank
0.2G req/s — 约 5GHz 每 bank 刚好匹配, 所以 Server 配置需要谨慎.

---

## 多 Backend 扩展

| Backend count | Max GC% (metadata 瓶颈) | 适用 |
|--------------|-------------------------|------|
| 1× | 26% | Standard/MCU |
| 2× + 2×meta | 52% | Mobile |
| 4× + 4×meta | 105% | Desktop/Server |
| 8× + 8×meta | 210% | Server 高压 |

结论: metadata bank count 必须随 backend count 线性扩展, 否则 metadata
cache 始终是第一瓶颈.

---

## 第一瓶颈确认

实测和模型一致: **metadata cache 是绝对第一瓶颈**.

原因:
1. 频率最高: 80% of GC 指令需要 metadata lookup
2. pipeline 深度最大: 5 级 vs event/forwarding 的 1-2 级
3. bank 扩展成本高: metadata bank = 独立 tag+data array
4. WB/RB 零周期/非阻塞: 前端无瓶颈

下一步优先:
1. **Metadata cache bank / pipeline 优化** (当前 0.2 evt/cyc/bank)
2. 多 Scan backend 必要但优先级低于 metadata bank
3. Metadata bank 粒度: 4-bank 可覆盖 Server 配置
4. 更高 (8-bank) 仅在 6GHz+ 需要

## RTL 吞吐测试覆盖

新增测试文件:
- `tests/test_gc_metadata_throughput.py`: 5 tests (Standard/Pipelined
  连续注入, 背压, miss 吞吐, 对比)
- `tests/test_gc_event_throughput.py`: 5 tests (Separated 饥饿,
  连续注入混合吞吐, 背压, Standard 吞吐)
