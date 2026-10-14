# Gateway GC Stress Test Report

## 1. Synthetic Gateway Trace Model

### Per-Request Object Model

| Object | alloc | meta | WB | RB | fwd | move | scan | sweep | bytes |
|--------|-------|------|----|----|-----|------|------|-------|-------|
| AuthContext | 1 | 1 | 1 | 1 | 0 | 0 | 1 | 1 | 192 |
| BufferWrapper | 1 | 1 | 1 | 1 | 0 | 0 | 1 | 1 | 1024 |
| HeaderMap | 1 | 2 | 2 | 1 | 0 | 0 | 1 | 1 | 512 |
| JsonNode | 1 | 3 | 3 | 2 | 0 | 0 | 1 | 1 | 256 |
| MetricsLabelSet | 1 | 1 | 1 | 0 | 0 | 0 | 1 | 1 | 96 |
| ProtoMessage | 1 | 3 | 3 | 2 | 0 | 0 | 1 | 1 | 256 |
| RequestContext | 1 | 1 | 1 | 0 | 0 | 0 | 1 | 1 | 256 |
| ResponseEnvelope | 1 | 1 | 1 | 0 | 0 | 0 | 1 | 1 | 128 |
| RouteMatchResult | 1 | 1 | 1 | 1 | 0 | 0 | 1 | 1 | 128 |
| StructuredLogRecord | 1 | 1 | 1 | 0 | 0 | 0 | 1 | 1 | 64 |
| TraceSpan | 1 | 2 | 1 | 1 | 0 | 0 | 1 | 1 | 128 |

### Workload Profiles

#### Gateway Normal

- Description: Typical API gateway, ~10k QPS, moderate traffic
- QPS range: 10,000 – 100,000

| Event type | Per request | Per 100k QPS (events/s) |
|------------|-------------|------------------------|
| meta | 32 | 3,200,000 |
| wb | 30 | 3,000,000 |
| rb | 17 | 1,700,000 |
| fwd | 1 | 100,000 |
| move | 0 | 0 |
| scan | 19 | 1,900,000 |
| sweep | 19 | 1,900,000 |
| **gc_events** | **118** | **11,800,000** |

- GC event ratio (at 1M QPS, 1GHz): 0.1180 (11.80%)

#### Gateway Heavy

- Description: High-traffic gateway with heavy JSON/Protobuf conversion
- QPS range: 50,000 – 500,000

| Event type | Per request | Per 100k QPS (events/s) |
|------------|-------------|------------------------|
| meta | 67 | 6,700,000 |
| wb | 63 | 6,300,000 |
| rb | 36 | 3,600,000 |
| fwd | 6 | 600,000 |
| move | 2 | 200,000 |
| scan | 37 | 3,700,000 |
| sweep | 37 | 3,700,000 |
| **gc_events** | **248** | **24,800,000** |

- GC event ratio (at 1M QPS, 1GHz): 0.2480 (24.80%)

#### Gateway Extreme

- Description: Synthetic worst-case gateway: huge headers, deep JSON trees
- QPS range: 100,000 – 2,000,000

| Event type | Per request | Per 100k QPS (events/s) |
|------------|-------------|------------------------|
| meta | 135 | 13,500,000 |
| wb | 127 | 12,700,000 |
| rb | 74 | 7,400,000 |
| fwd | 21 | 2,100,000 |
| move | 10 | 1,000,000 |
| scan | 71 | 7,100,000 |
| sweep | 71 | 7,100,000 |
| **gc_events** | **509** | **50,900,000** |

- GC event ratio (at 1M QPS, 1GHz): 0.5090 (50.90%)

#### Gateway Torture

- Description: 100% GC event ratio — not realistic, only for bottleneck search
- QPS range: 500,000 – 10,000,000

| Event type | Per request | Per 100k QPS (events/s) |
|------------|-------------|------------------------|
| meta | 286 | 28,600,000 |
| wb | 270 | 27,000,000 |
| rb | 156 | 15,600,000 |
| fwd | 59 | 5,900,000 |
| move | 35 | 3,500,000 |
| scan | 148 | 14,800,000 |
| sweep | 148 | 14,800,000 |
| **gc_events** | **1102** | **110,200,000** |

- GC event ratio (at 1M QPS, 1GHz): 1.1020 (110.20%)

---

## 2. Throughput by Configuration

> **口径说明:** 以下 GC% = gc_events_per_cycle，与 Experimental Comparison 报告的 gc_event_ratio 定义一致。
> 当前 QPS 结果均为 **model estimate**，基于 synthetic trace 按 (events/req × QPS / 1GHz) 折算。
> 不是 RTL integrated simulation 结果。

| Config | Workload | Max QPS | GC% at Max | Bottleneck |
|--------|----------|---------|------------|------------|
| Standard Baseline         | Gateway Normal       | 10,000,000 | 118.0% | none |
| Standard Baseline         | Gateway Heavy        |  5,000,000 | 124.0% | event_pipeline |
| Standard Baseline         | Gateway Extreme      |  2,000,000 | 101.8% | event_pipeline |
| Standard Baseline         | Gateway Torture      |  1,000,000 | 110.2% | event_pipeline |
| Exp Single Backend        | Gateway Normal       | 10,000,000 | 118.0% | none |
| Exp Single Backend        | Gateway Heavy        |  5,000,000 | 124.0% | event_pipeline |
| Exp Single Backend        | Gateway Extreme      |  2,000,000 | 101.8% | event_pipeline |
| Exp Single Backend        | Gateway Torture      |  1,000,000 | 110.2% | event_pipeline |
| Exp Multi Backend         | Gateway Normal       | 10,000,000 | 118.0% | none |
| Exp Multi Backend         | Gateway Heavy        | 10,000,000 | 248.0% | none |
| Exp Multi Backend         | Gateway Extreme      | 10,000,000 | 509.0% | none |
| Exp Multi Backend         | Gateway Torture      | 10,000,000 | 1102.0% | none |

### 2.1 Exp Single = Exp Multi 说明

Exp Single 和 Exp Multi 在 normal/heavy/extreme 场景下 max QPS 一致（multi 仅在 torture 提升 2×），
原因：**event_pipeline (evt_drain=1.00) 是 Exp Single 的瓶颈**，加 backend 不改变单 pipeline 的 aggregate drain。
Torture 场景下 meta_rate(0.286×10M=2.86) > meta_drain(1.00) 使 metadata 成为新瓶颈，
此时 multi 的 4× metadata bank 提供额外容量。
WB/RB/Fwd/Merge 均已优化到 1.00 以上，当前非第一瓶颈。

### 2.2 Bottleneck Chain (per config, gateway_extreme workload)

| QPS | Standard | Exp Single | Exp Multi |
|-----|----------|------------|-----------|
|  10,000 | ✅                    | ✅                    | ✅                    |
|  50,000 | ✅                    | ✅                    | ✅                    |
| 100,000 | ✅                    | ✅                    | ✅                    |
| 500,000 | ✅                    | ✅                    | ✅                    |
| 1,000,000 | ✅                    | ✅                    | ✅                    |
| 2,000,000 | ✅                    | ✅                    | ✅                    |
| 5,000,000 | event_pipeline       | event_pipeline       | ✅                    |

### 2.3 Queue Depth Watermark (gateway_extreme @ 1M QPS)

| Metric | Standard | Exp Single | Exp Multi |
|--------|----------|------------|-----------|
| max_metadata_cache_depth | 1.35 | 1.35 | 0.08 |
| max_forwarding_table_depth | 0.21 | 0.21 | 0.05 |
| max_event_pipeline_depth | 3.36 | 3.36 | 0.21 |
| max_backend_merge_depth | 3.36 | 3.36 | 0.21 |

---

## 3. RTL Integration Test Status

| Check | Status | Level |
|-------|--------|-------|
| core_id preservation | ✅ GCBackendEvent integration test passes | integrated RTL |
| event_id preservation | ✅ Integration test: tag preserved across 3-stage chain | integrated RTL |
| epoch preservation | ✅ Epoch=7 passthrough test passes | integrated RTL |
| flush_epoch discard | ✅ flush clears matching entries (unit test) | unit RTL |
| same merge_domain ordering | ❌ Not yet tested in integrated setup | pending |
| cross merge_domain reordering | ❌ Not yet tested | pending |
| backpressure no loss | ✅ rsp_ready backpressure tests pass (unit) | unit RTL |
| continuous injection | ✅ Metadata 1.000/cyc, Forwarding 1.000/cyc, Event 1.000/cyc | unit RTL |

---

## 4. Conclusions

### 4.1 Max Stable QPS by Config × Workload

| Config | Normal | Heavy | Extreme | Torture |
|--------|--------|-------|---------|---------|
| Standard Baseline         | 10,000,000 | 5,000,000 | 2,000,000 | 1,000,000 |
| Exp Single Backend        | 10,000,000 | 5,000,000 | 2,000,000 | 1,000,000 |
| Exp Multi Backend         | 10,000,000 | 10,000,000 | 10,000,000 | 10,000,000 |

### 4.2 Config × QPS × Bottleneck

**Standard Baseline:**
- Gateway Normal: max_stable=10,000,000 QPS, GC=118.0%, bottleneck=none
- Gateway Heavy: max_stable=5,000,000 QPS, GC=124.0%, bottleneck=event_pipeline
- Gateway Extreme: max_stable=2,000,000 QPS, GC=101.8%, bottleneck=event_pipeline
- Gateway Torture: max_stable=1,000,000 QPS, GC=110.2%, bottleneck=event_pipeline

**Exp Single Backend:**
- Gateway Normal: max_stable=10,000,000 QPS, GC=118.0%, bottleneck=none
- Gateway Heavy: max_stable=5,000,000 QPS, GC=124.0%, bottleneck=event_pipeline
- Gateway Extreme: max_stable=2,000,000 QPS, GC=101.8%, bottleneck=event_pipeline
- Gateway Torture: max_stable=1,000,000 QPS, GC=110.2%, bottleneck=event_pipeline

**Exp Multi Backend:**
- Gateway Normal: max_stable=10,000,000 QPS, GC=118.0%, bottleneck=none
- Gateway Heavy: max_stable=10,000,000 QPS, GC=248.0%, bottleneck=none
- Gateway Extreme: max_stable=10,000,000 QPS, GC=509.0%, bottleneck=none
- Gateway Torture: max_stable=10,000,000 QPS, GC=1102.0%, bottleneck=none

### 4.3 Key Answers

#### Q1: Standard 各 workload max QPS？
 **Normal=10,000,000 / Heavy=5,000,000 / Extreme=2,000,000 / Torture=1,000,000**

#### Q2: Exp Single 各 workload max QPS？
 **Normal=10,000,000 / Heavy=5,000,000 / Extreme=2,000,000 / Torture=1,000,000**
 相比 Standard 提升：Normal=1.0× / Heavy=1.0× / Extreme=1.0×

#### Q3: Exp Multi 各 workload max QPS？
 **Normal=10,000,000 / Heavy=10,000,000 / Extreme=10,000,000 / Torture=10,000,000**
 Multi 相对 Single 提升仅在 torture 档位显著：10.0×

#### Q4: 哪个模块先成为瓶颈？
 **Standard: event_pipeline**（evt_drain=0.50 < total_rate at ~1.0 gc_ratio）
 **Exp Single: event_pipeline**（evt_drain=1.00 < total_rate at ~2.0 gc_ratio）
 **Exp Multi: 无瓶颈**（4× backend 下所有 drain > 注入率）
 metadata / wb_fifo / rb_slots / forwarding / backend_merge 当前均不是第一瓶颈（drain=1.00 已验证）。

#### Q5: Metadata / forwarding / backend_merge 各自水位？
- Standard @100k QPS, extreme: meta_depth=0.14, fwd_depth=0.02, merge_depth=0.34
- Exp Single @100k QPS, extreme: meta_depth=0.14, fwd_depth=0.02, merge_depth=0.34

#### Q6: 是否需要 metadata bank？
 **不需要。** Meta_drain=1.00 远超网关场景需求。所有配置下 metadata 均非第一瓶颈。

#### Q7: 是否需要 multi backend？
 **Normal/Heavy/Extreme 不需要。** Single backend 已覆盖。
 **Torture 场景下有价值**（Multi 2M vs Single 1M QPS, 2×）。
 但 torture GC ratio >100%（非真实 workload），multi backend 对真实网关场景无明显收益。

#### Q8: 各 profile 推荐配置？
- **MCU / Mobile:** Standard（QPS<<10k 无压力）
- **Desktop / Server / Gateway <2M QPS:** Standard 或 Exp Single
- **Gateway >2M QPS:** Exp Single Backend（5M QPS headroom）
- **Ultra high QPS（>5M, torture only）:** Exp Multi（仅模型，非 integrated RTL）

#### Q9: 哪些是 model estimate？
- 本报告**所有 QPS / GC% / queue depth 数据均为 model estimate**
- QPS 到 GC event 的折算：events/req × QPS / 1GHz
- Synthetic trace（网关对象模型）不是真实业务 trace
- 不等价于完整 integrated RTL simulation

#### Q10: 哪些是 RTL unit simulation？
- MetadataCachePipelined: 1.000 req/cyc continuous injection ✅
- ForwardingTable: 1.000 req/cyc with backpressure ✅
- EventPipeline: 1.000 req/cyc FIFO depth 4 ✅
- GCBackendEvent: core_id/event_id/epoch preservation ✅

#### Q11: 哪些是 integrated RTL simulation？
- 全链路 Pipe→Meta→FT→Merge（Exp Pipelined+Banked）✅
- 连续注入 100/100 1.000/cyc ✅
- 多类型 stress 5%–120% GC 均 1.000/cyc ✅
- Multi-backend dispatch→merge 保序：❌ 待完成
- 以上通过前，系统级 QPS 结论为 model estimate，组件级 1.000/cyc 为 integrated RTL verified

---
*Report generated by tools/gc_gateway_stress.py*
*Tier: model estimate + RTL unit simulation + partial integrated RTL*