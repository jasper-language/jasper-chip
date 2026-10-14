# Experimental GC vs Standard — Three-Tier Analysis

## Tier 1: Current RTL Baseline

使用当前实际 RTL drain rate，不做假设。

### Throughput by GC Ratio

| GC% | Standard | Exp Single | Exp Multi |
|-----|----------|------------|-----------|
| 5% | ✅ none             | ✅ none             | ✅ none             |
| 10% | ✅ none             | ✅ none             | ✅ none             |
| 15% | ✅ none             | ✅ none             | ✅ none             |
| 20% | ✅ none             | ✅ none             | ✅ none             |
| 25% | ✅ none             | ✅ none             | ✅ none             |
| 30% | ✅ none             | ✅ none             | ✅ none             |
| 35% | ✅ none             | ✅ none             | ✅ none             |
| 40% | ✅ none             | ✅ none             | ✅ none             |
| 50% | ✅ none             | ✅ none             | ✅ none             |
| 60% | ✅ none             | ✅ none             | ✅ none             |
| 80% | ❌ event_pipeline   | ❌ event_pipeline   | ✅ none             |
| 100% | ❌ event_pipeline   | ❌ event_pipeline   | ✅ none             |

### Max Stable GC Ratio

- **Standard Baseline:** max stable = 60% GC  (first bottleneck = event_pipeline)
- **Exp Single Backend Full:** max stable = 60% GC  (first bottleneck = event_pipeline)
- **Exp Multi Backend Full:** max stable = 100% GC  (first bottleneck = none)

> **RTL 修正:** model 原假设 meta_drain=0.20，但 RTL 测试证实
> MetadataCachePipelined 可稳定维持 1.0 req/cycle（连续注入 100 请求 100/100 接受）。
> 因此 meta_drain 从 0.20 修正为 1.00（5× 提升），metadata cache 不再是第一瓶颈。
> 当前真正瓶颈见 Tier 2 分析。

- **Standard Baseline:** max_stable = 60% GC, next bottleneck at 65% GC: event_pipeline
- **Exp Single Backend Full:** max_stable = 60% GC, next bottleneck at 65% GC: event_pipeline
- **Exp Multi Backend Full:** max_stable = 100% GC, next bottleneck at 105% GC: wb_fifo

> **Multi Backend 高压结果（100% GC）仍未完成端到端 integrated RTL 验证。**
> 当前 Exp Multi 100% max_stable 为 model estimate，部分模块有 RTL unit test 覆盖（ForwardingTable 15/15、Metadata 12/12、Event 18/18），
> 但尚未在 cross-module 连续注入下验证 multi-backend dispatch→merge→保序。
> 不等价于 integrated RTL result，更不能作为芯片产品结论。

### Latency Comparison (pipeline depth)

| Metric | Standard | Exp Single | Exp Multi |
|--------|----------|------------|-----------|
| metadata_hit | 1cy | 4cy | 4cy |
| metadata_miss | 2cy | 5cy | 5cy |
| forwarding | 1cy | 1cy | 1cy |
| event_pipeline | 1cy | 1cy | 1cy |
| backend_roundtrip | 1cy | 4cy | 6cy |

> Pipeline 增加单事件延迟但不降低吞吐(每周期可接受新请求)。
> Metadata hit latency 从 1→4 周期是主要延迟增量。

### Area / Gate Delta

| Config | Gates | Δ vs Standard | pct |
|--------|-------|--------------|-----|
| Standard Baseline              | 78,300 |     +0 | +0.0% |
| Exp Single Backend Full        | 81,800 | +3,500 | +4.5% |
| Exp Multi Backend Full         | 93,000 | +14,700 | +18.8% |

### Power Estimate (at 1GHz, 28nm model)

| Config | @10%GC mW | @20%GC mW | @30%GC mW | Energy/evt pJ |
|--------|-----------|-----------|-----------|--------------|
| Standard Baseline              | 3.92 | 6.85 | 9.79 | 24.47 |
| Exp Single Backend Full        | 4.09 | 7.16 | 10.23 | 25.56 |
| Exp Multi Backend Full         | 4.65 | 8.14 | 11.63 | 29.06 |

### RTL Test Status

| Module | Status |
|--------|--------|
| ForwardingTable           | PASS |
| MetadataCache             | PASS |
| Metadata thru             | PASS |
| EventPipeline             | PASS |
| Event thru                | PASS |
| L0 Forwarding             | PASS |
| Slots Bank                | PASS |
| BackendMerge              | PASS |
| HeapRegion                | PASS |
| NumaCtrl                  | PASS |
| Config                    | PASS |
| Integration               | PASS |

---

## Tier 2: Metadata Optimized What-if Model

> **model_only / what_if** — 非 RTL 实测。假设 metadata drain rate 提升后 single backend 的理论上限。

### Assumptions

| Parameter | Standard | What-if 1 | What-if 2 | What-if 3 |
|-----------|----------|-----------|-----------|-----------|
| meta_drain=0.20 | max=25% | BN@30%=metadata_cache | BN@50%=metadata_cache | metadata shift |
| meta_drain=0.40 | max=50% | BN@30%=none | BN@50%=none | event shift |
| meta_drain=0.80 | max=60% | BN@30%=none | BN@50%=none | forwarding shift |
| meta_drain=1.00 | max=60% | BN@30%=none | BN@50%=none | forwarding shift |

### Current RTL Max Stable (meta_drain=1.00, validated)

- **Standard Baseline:** max_stable=60% GC, next bottleneck: event_pipeline
- **Exp Single Backend Full:** max_stable=60% GC, next bottleneck: event_pipeline
- **Exp Multi Backend Full:** max_stable=100% GC, next bottleneck: none

> Standard=60% | Exp Single=60% | Exp Multi=100%
> Exp Multi 100% 为 model estimate，未完成 integrated RTL 验证

### What-if: hypothetical meta_drain values

| meta_drain | Standard | Exp Single | Exp Multi | note |
|------------|----------|------------|-----------|------|
| 0.20 | 25% | 25% | 100% | model only |
| 1.00 | 60% | 60% | 100% | RTL validated |
| 2.00 | 60% | 60% | 100% | model only |
| 4.00 | 60% | 60% | 100% | model only |

### Key Findings

1. Current RTL (meta_drain=1.00): Standard=60%, Exp Single=60%, Exp Multi=100%
2. Standard 稳态 60% GC；65% 时 event_pipeline 成为第一瓶颈（evt_drain=0.50 < total_rate）
3. Exp Single 相对 Standard 约 1.0×（60% → 60%），瓶颈同样为 event_pipeline
3. Exp Multi 达到 100% GC（model estimate），未完成 integrated RTL 验证
4. 如果 meta_drain 仅 0.20（旧假设），Standard=25%、Exp Single=25%、Exp Multi=40%
5. 所以 meta_drain 从 0.20→1.00 是真实的 RTL 提升，不是模型假设
6. Metadata pipeline 优化值得回流 Standard —— 降低 timing risk，无需增加 bank
## Tier 3: Future Integrated Test Placeholder

### Unit RTL — 已完成

- [x] MetadataCachePipelined: continuous injection at 1 req/cyc ✅
- [x] MetadataCachePipelined: fill queue (2-entry depth) ✅
- [x] MetadataCachePipelined: rsp_ready backpressure ✅
- [x] MetadataCachePipelined: GCBackendEvent input/output ✅
- [x] Cross-module: core_id / event_id / epoch / sequence preservation ✅
- [x] Cross-module: flush_epoch epoch invalidation ✅

### Cross-module / Integrated — 待完成

- [ ] EventPipeline → MetadataCache → ForwardingTable → BackendMerge
     连续注入吞吐测试（当前仅有 basic integration test）
- [ ] Multi-backend dispatch → merge → core_id 端到端保序
- [ ] merge_domain ordering（同 domain 保序、跨 domain 乱序）
- [ ] 以上全部通过后，what-if 模型结果才能升级为 integrated RTL result

当前状态：
- GCBackendEvent 接口已就绪 + 4 模块已接入 ✅
- Cross-module integration test (3-stage chain) 已通过 ✅
- MetadataCachePipelined unit throughput 已测试 (5 tests) ✅
- Cross-module 连续注入吞吐测试尚未完成 ❌

---

## Conclusions

### Q1: Standard 当前 max_stable 是多少？

**60% GC。** 稳态 60% GC；65% 时 event_pipeline 成为第一瓶颈（Standard evt_drain=0.50 < total_rate）。
Meta_drain=1.00（RTL 实测 1.0 req/cycle）后 metadata 不再是瓶颈。

### Q2: Exp Single 当前 max_stable 是多少？

**60% GC，相对 Standard 约 1.0×（60% → 60%）。** 第一瓶颈为 event_pipeline。
Optimized Exp Single 通过 FIFO depth 4 + pipeline 将 forwarding/event/merge 全部推到 1.00 evt/cyc，不再受 Standard 0.50 限制。

### Q3: Exp Multi 当前 max_stable 是多少？

**100% GC（model estimate）。** 多 backend + 多 bank 显著提升上限。
> 但 Exp Multi 100% 为 model / estimate / partial RTL，不是 integrated RTL 结论。
> ForwardingTable(15/15)、Metadata(12/12)、Event(18/18) 有独立 RTL 覆盖，
> 但 multi-backend dispatch→merge 端到端高压测试尚未通过 integrated RTL 验证。

### Q4: Metadata 优化是否值得回流 Standard？

**是。** Metadata pipeline 化的好处是降低组合逻辑深度（timing risk），
且 bank_count=1 时面积增量可忽略 (~2K GE)。Single backend + pipelined metadata 可作为 Standard+ 配置。

### Q5: MCU / Mobile / Desktop / Server 推荐配置？

- **MCU (GC<5%):** Standard baseline（当前 60% 能力远超需求）
- **Mobile (GC≈10%):** Standard+（pipelined metadata, 充裕）
- **Desktop (GC≈15–20%):** Exp Single Backend Full（60% headroom，远高于需求）
- **Server (GC>20%):** Exp Multi Backend Full（100% model, integrated RTL pending）

---
*Report generated by tools/gc_experimental_comparison.py*
*Tier 1: current_rtl_result | Tier 2: model_only_result | Tier 3: integrated_rtl_required*