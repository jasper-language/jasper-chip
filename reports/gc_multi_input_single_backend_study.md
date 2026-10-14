# Multi-Input Single-Backend Architecture Study

## Objective

Determine whether a wide single-backend (multi-input + multi-lane + multi-output) can break the 1.0 evt/cyc throughput ceiling, and whether it is more practical than replicating multiple independent backends.

## 1. Candidate Architectures

### A. Current Single Backend (baseline)
| Parameter | Value |
|-----------|-------|
| input_width | 1 |
| output_width | 1 |
| metadata_ports | 1 |
| forwarding_ports | 1 |
| merge_ports | 1 |
| backend_count | 1 |
| **theoretical evt/cyc** | **1.0** |
| **RTL verified** | ✅ 1.000/cyc |
| gates_estimate | ~60K GE |
| power_estimate @10%GC | ~1.7 mW |

### B. Wide Single Backend — 2-lane
| Parameter | Value |
|-----------|-------|
| input_width | 2 |
| output_width | 2 |
| metadata_ports | 2 |
| forwarding_ports | 2 |
| merge_ports | 2 |
| backend_count | 1 |
| **theoretical evt/cyc** | **2.0** |
| gates_estimate | ~95K GE |
| power_estimate @10%GC | ~2.8 mW |

### C. Wide Single Backend — 4-lane
| Parameter | Value |
|-----------|-------|
| input_width | 4 |
| output_width | 4 |
| metadata_ports | 4 |
| forwarding_ports | 4 |
| merge_ports | 4 |
| backend_count | 1 |
| **theoretical evt/cyc** | **4.0** |
| gates_estimate | ~170K GE |
| power_estimate @10%GC | ~5.0 mW |

### D. Multi Backend — 2× (for comparison)
| Parameter | Value |
|-----------|-------|
| input_width | 1 per backend |
| output_width | 1 per backend |
| metadata_ports | 1 per backend |
| forwarding_ports | 1 per backend |
| merge_ports | 2 (dispatch + gather) |
| backend_count | 2 |
| **theoretical evt/cyc** | **2.0** |
| gates_estimate | ~125K GE |
| power_estimate @10%GC | ~3.6 mW |

### E. Multi Backend — 4× (for comparison)
| Parameter | Value |
|-----------|-------|
| backend_count | 4 |
| **theoretical evt/cyc** | **4.0** |
| gates_estimate | ~250K GE |
| power_estimate @10%GC | ~7.2 mW |

## 2. Frontend — Can 2/4 events/cycle be issued?

### Current frontend limits

The frontend (`gc_subsystem.py`) emits GC events under these conditions:
- `gc_fire` = 1 event per cycle max (single GC instruction issue)
- `wb_enq_valid` = 1 event per store (but WB FIFO drains at 1/cycle)
- `fire` (RB inject) = 1 per cycle max

**All three event sources are limited to 1 event/cycle.**

### Wide frontend requirements

To feed a 2-lane backend, the frontend must emit 2 events/cycle:
1. **Multi-issue GC instructions** — decode 2 GC ops per cycle (requires wider decoder)
2. **Dual WB FIFO read** — two WB events drained per cycle (requires dual-port or banked FIFO)
3. **Dual RB inject** — two RB events per cycle (requires dual RB slot allocator)
4. **WB + RB parallelism** — WB and RB can issue in the same cycle (already possible but currently arbitrated)

### Assessment

| Constraint | 2-lane feasible? | 4-lane feasible? |
|-----------|-----------------|-----------------|
| GC instruction multi-issue | Possible (wider decoder) | Hard (4-wide decoder = large) |
| WB FIFO dual read | Possible (banked WB FIFO) | Possible (4-bank) |
| RB dual inject | Possible (2 RB slots/cyc) | Hard (contention) |
| Mixed WB+RB | Already possible | Already possible |
| **Overall frontend** | **Feasible with moderate changes** | **Feasible but decoder cost high** |

**Key finding: Frontend is NOT the bottleneck for 2-lane. For 4-lane, the GC instruction decoder becomes a significant cost.**

## 3. Metadata — Multi-port or Banked?

### Options

| Approach | 2-lane | 4-lane | Area | Conflict risk |
|----------|--------|--------|------|--------------|
| True multi-port SRAM (2R/2W) | ✅ | ❌ (4RW SRAM rare) | Very high | None |
| Banked (address hash) | ✅ 2 banks | ✅ 4 banks | Moderate | Hash collision |
| Banked + replication | ✅ 2 copies | ✅ 4 copies | High | Coherence |

### Assessment

Banked metadata cache is the practical choice. With 2-lane dispatch:
- Lane 0 → bank 0, Lane 1 → bank 1 (address LSB select)
- Bank conflict when both lanes access the same set: 50% probability at uniform random
- Bank conflict penalty: stall one lane for 1 cycle → throughput loss ~25%

For 4-lane: 4 banks, conflict probability ~75% × ~50% = lower per-lane but higher total arbitration cost.

**Metadata is NOT the bottleneck for 2-lane.** For 4-lane, bank conflicts may limit effective throughput to ~3.0 evt/cyc.

## 4. Forwarding — Multi-port or Banked?

### Current forwarding table

`ForwardingTableStandard` has a single query/response port. The `ForwardingTableBankedPipeline` already supports bank_count = N.

For wide backend:
- Lane 0 → forwarding bank 0
- Lane 1 → forwarding bank 1
- Each bank is independent (different address spaces)
- No cross-bank coherence needed (old_ptr → new_ptr mappings are per-object)

### Chase depth in multi-lane

Chase depth (resolving A→B→C) is per-query, per-lane. No cross-lane dependency:
- Lane 0: query A → returns B (then lane 0 chases B if depth>1)
- Lane 1: simultaneously queries C → returns D
- No ordering constraint between lanes

### Flush in multi-lane

`flush_epoch` must invalidate entries in ALL banks simultaneously. This is a broadcast operation, not a serial bottleneck.

**Forwarding is well-suited to multi-lane. Bank conflict is low (address hash independent between lanes).**

## 5. Event Pipeline — Shared Pipeline or Per-Lane?

### Options

| Approach | 2-lane | 4-lane | Complexity | Balance |
|----------|--------|--------|------------|---------|
| Shared pipeline, multi-issue | Complex | Very complex | High | Perfect |
| Per-lane pipeline | ✅ Duplicate | ✅ Duplicate | Low | Depends on dispatch |
| Per-type lanes (scan/sweep/move) | ✅ 3 lanes | ✅ 3 lanes | Low | May underutilize |

### Assessment

**Per-lane event pipeline is the simplest correct approach:**
- Each lane has its own `_PipelineStage` (FIFO depth 4 + aging merge)
- Events are dispatched to lanes by a hash (event_id % lane_count) or by type
- Each lane produces results independently
- No cross-lane event ordering needed (merge_domain + sequence handles ordering at the output)

The existing `GCEventPipelineSeparated` can be adapted: instead of 3 sub-pipelines (scan/sweep/move), have N sub-pipelines (lane 0..N-1), each handling ALL event types.

### Event type balance

At 2-lane, each lane handles ~50% of events. At 4-lane, ~25%. With uniform hash dispatch, load balance within ±10%.

**Event pipeline is NOT a bottleneck for multi-lane. Per-lane duplication is straightforward.**

## 6. Backend Merge — Ordering and Commitment

### The hardest problem

Multi-lane produces results that must be committed in order (within the same merge_domain). The merge unit receives 2/4 results per cycle and must emit them in (merge_domain, epoch, sequence) order.

### Merge strategies

| Strategy | 2-lane | 4-lane | Area | Latency |
|----------|--------|--------|------|---------|
| Per-domain reorder buffer | ✅ | ✅ | ~1K GE/domain | 1-4 cycles |
| Output commit queue | ✅ | ✅ | ~2K GE | 1-2 cycles |
| Strict lane ordering | ❌ defeats purpose | ❌ | 0 | 0 |

**Recommended approach: output commit queue.**
Each lane produces (result, merge_domain, epoch, sequence). Results enter a shared commit queue. The queue emits results in (domain, epoch, sequence) order. Since each lane produces results in order (within its own pipeline), and the dispatch hash preserves ordering within a domain, the commit queue only needs to handle interleaving, not full reordering.

### Commit queue sizing

| Lanes | Queue depth | Area | Max out-of-order |
|-------|-------------|------|------------------|
| 2 | 8 | ~2K GE | 4 entries |
| 4 | 16 | ~4K GE | 8 entries |

**Backend merge is feasible for 2-lane. For 4-lane, queue depth and area double.**

## 7. Backpressure

### Per-lane ready vs global ready

| Approach | Fairness | Complexity | Head-of-line blocking |
|----------|----------|------------|----------------------|
| Global ready (all lanes or none) | Low | Low | Yes — one slow lane blocks all |
| Per-lane ready | High | Moderate | No |
| Credit-based | High | High | No |

**Recommended: per-lane ready + input skid buffer.**
- Each lane has its own `rsp_ready[p]` handshake
- The frontend has a small skid buffer (depth 2-4) to hold events when a lane is blocked
- If the skid buffer overflows, the frontend stalls globally

### No-loss guarantee

The existing `BackendMergeSingle` backpressure bug (fixed) demonstrated that no-loss backpressure requires:
1. Each stage's `ready` must reflect true acceptance capacity
2. Each stage's `valid` must be held until `ready` is asserted
3. FIFO-based buffering at each stage absorbs bursts

For multi-lane, the same principles apply per lane. No additional correctness risk.

**Backpressure is solvable for 2-lane and 4-lane with known techniques.**

## 8. Area and Power Estimates

### Model
```
base_area = 60K GE (single backend)
base_power = 1.7 mW @10% GC
```

### Estimates

| Config | Area | vs Baseline | Power | vs Baseline |
|--------|------|-------------|-------|-------------|
| 1-lane baseline | 60K GE | — | 1.7 mW | — |
| 2-lane wide | 95K GE | +58% | 2.8 mW | +65% |
| 4-lane wide | 170K GE | +183% | 5.0 mW | +194% |
| 2× multi-backend | 125K GE | +108% | 3.6 mW | +112% |
| 4× multi-backend | 250K GE | +317% | 7.2 mW | +324% |

### Key observation

**2-lane wide is significantly more area-efficient than 2× multi-backend (95K vs 125K GE, -24%).**
The savings come from shared controller logic (cycle controller, scoreboard, stats, debug) that would be duplicated in multi-backend.

For 4-lane, the gap narrows (170K vs 250K, -32%) but the complexity advantage of multi-backend (independent, testable, scalable) grows.

## 9. Verification Complexity

| Config | Unit tests | Integration tests | Ordering tests | Backpressure tests |
|--------|-----------|------------------|----------------|-------------------|
| 1-lane | 16 suites ✅ | 5 suites ✅ | ✅ | ✅ |
| 2-lane wide | ~25 suites | ~10 suites | New | New |
| 4-lane wide | ~35 suites | ~15 suites | New | New |
| 2× multi-backend | ~20 suites (reuse) | ~8 suites | New | New |

Multi-backend reuses existing 1-lane backend RTL directly — each backend is independently tested at 1.0/cyc. Wide single-backend requires NEW RTL for each wide module. **Multi-backend has a verification advantage.**

## 10. Wide Single Backend vs Multi Backend — Comparison

| Criterion | Wide Single (2-lane) | Multi Backend (2×) | Winner |
|-----------|---------------------|-------------------|--------|
| Throughput | 2.0 evt/cyc | 2.0 evt/cyc | Tie |
| Area | 95K GE (-24%) | 125K GE | **Wide** |
| Power | 2.8 mW (-22%) | 3.6 mW | **Wide** |
| Fmax | Lower (wider muxes) | Same as 1-lane | **Multi** |
| Block-level reuse | Low (new RTL) | High (reuses 1-lane) | **Multi** |
| Verification | Harder (new modules) | Easier (proven modules) | **Multi** |
| Ordering | Commit queue needed | Backend merge already exists | **Multi** |
| Backpressure | Per-lane skid buffer | Per-backend (proven) | Tie |
| Scalability | Diminishing returns (4-lane: 170K GE for 2× gain) | Linear (4× = 250K GE for 4× gain) | **Multi** |
| Multi-core support | Same die, shared logic | Natural per-core | **Multi** |
| Clock gating | Shared logic harder to gate | Per-backend independent gating | **Multi** |

## 11. Recommendations

### Architecture feasibility
| Lane count | Feasible? | Limiting factor |
|-----------|-----------|----------------|
| 2-lane wide | **GO** | Frontend multi-issue needed, but solvable |
| 4-lane wide | **HOLD** | Decoder cost, bank conflicts, commit queue complexity |
| 4× multi-backend | **GO** | Reuses verified 1-lane, linear scaling |

### Which to prioritize?

**Recommendation: HOLD wide single-backend, prioritize multi-backend.**

Reasons:
1. **2-lane wide saves ~24% area vs 2× multi-backend**, but the area savings are modest (~30K GE)
2. **Multi-backend reuses all existing 1.0/cyc RTL** — zero new module development
3. **Verification complexity is significantly lower** for multi-backend
4. **Multi-backend scales linearly to 4×, 8×** (wide single-backend has diminishing returns)
5. **Multi-backend is more natural for multi-core** (future-proof)

The only scenario where wide single-backend wins is when absolute minimum area/power is required at 2× throughput. For most Server/Gateway profiles, the area/power difference is negligible compared to the verification and scaling advantages of multi-backend.

### Action items

| Priority | Action | Branch |
|----------|--------|--------|
| 1 | Multi-backend dispatch (GC instruction level) | explore/multi-backend-dispatch |
| 2 | Multi-backend merge (gather + order) | explore/multi-backend-merge |
| 3 | Backend-to-core affinity (NUMA-aware) | explore/numa-backend |
| 4 | Wide single-backend 2-lane RTL prototype | explore/wide-2lane (if multi-backend proves insufficient) |

### Final conclusion

| Question | Answer |
|----------|--------|
| Architecture structurally valid? | **Yes, for 2-lane** |
| Worth RTL prototype? | **HOLD — do multi-backend first** |
| 2-lane or 4-lane? | 2-lane, if pursued |
| Better than multi-backend? | **No** — area savings modest, complexity high |
| Continue as exploration item? | **Yes**, but lower priority than multi-backend |
| Next step | Start multi-backend dispatch + merge |

## Files
- `reports/gc_multi_input_single_backend_study.md` (this file)
- `reports/gc_multi_input_single_backend_study.csv`
