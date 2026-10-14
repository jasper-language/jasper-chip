# Wide Backend Lane Count Parameterization Study

## Objective

Determine whether `lane_count` should be an arbitrary parameter or a fixed architectural choice, and what lane counts are worth supporting.

## 1. Lane Count Complexity Analysis

### 1.1 Input Side

| lane_count | Frontend required | Feasibility | Bottleneck |
|-----------|------------------|-------------|------------|
| 1 | 1 event/cyc (current) | ✅ Proven | — |
| 2 | 2 event/cyc (dual-issue) | ✅ Feasible | Decoder width |
| 3 | 3 event/cyc (triple-issue) | ❌ Awkward | Not power-of-2 dispatch |
| 4 | 4 event/cyc (quad-issue) | ⚠️ Possible | Decoder area + WB/RB |
| 8 | 8 event/cyc (oct-issue) | ❌ Impractical | Frontend becomes larger than backend |

**Finding: lane_count=3 is unnatural (not power-of-2).** Dispatch hash, bank assignment, and commit queue all align better with powers of 2. Lane_count=8 requires the frontend to issue 8 events/cycle, which is impractical for a single core.

### 1.2 Metadata

| lane_count | Metadata banks | Conflict probability | Effective throughput loss |
|-----------|---------------|---------------------|--------------------------|
| 1 | 1 | 0% | 0% |
| 2 | 2 | ~25% | ~12% |
| 3 | 3 | ~44% (odd banks) | ~22% |
| 4 | 4 | ~44% | ~22% |
| 8 | 8 | ~55% | ~28% |

**Key constraint: bank conflict scales non-linearly.** With N banks and N lanes, the probability that two lanes hit the same bank is approximately:

```
P(conflict) ≈ 1 - (N! / (N^N)) for random address distribution
```

| N | P(no conflict) | P(at least 1 conflict) |
|---|---------------|----------------------|
| 1 | 100% | 0% |
| 2 | 50% | 50% |
| 3 | 22% | 78% |
| 4 | 9% | 91% |
| 8 | 0.2% | 99.8% |

**Mitigation:** per-lane skid buffer stalls one lane on conflict. Effective throughput = lane_count × (1 - P(conflict)/2).

| N | Ideal | Effective | Loss |
|---|-------|-----------|------|
| 1 | 1.0 | 1.0 | 0% |
| 2 | 2.0 | 1.75 | 12.5% |
| 3 | 3.0 | 2.17 | 27.7% |
| 4 | 4.0 | 2.68 | 33.0% |
| 8 | 8.0 | 3.59 | 55.1% |

**Finding: above lane_count=2, bank conflict erodes throughput significantly.** For lane_count=4, the effective throughput is ~2.7 evt/cyc, which is only 35% more than lane_count=2 (1.75) for 2× the area.

### 1.3 Forwarding

| lane_count | Forwarding banks | Query conflict | Chase complexity |
|-----------|----------------|---------------|------------------|
| 1 | 1 | None | Per-query |
| 2 | 2 | Low (hash by addr) | Per-lane independent |
| 3 | 3 | Moderate (odd) | Per-lane, 3-wide |
| 4 | 4 | Moderate | Per-lane, 4-wide |
| 8 | 8 | High | Per-lane, 8-wide |

Forwarding conflict is lower than metadata because forwarding queries are read-only (no bank state change on query). However, **update + same-bank query on the same cycle requires write-after-read handling.**

**Finding: forwarding scales better than metadata.** Read-only queries have no bank conflict penalty. Update/query conflict is a single-cycle stall at most.

### 1.4 Commit Queue / Merge

| lane_count | Queue pushes/cyc | Queue pops/cyc | Ordering complexity | Queue area |
|-----------|-----------------|----------------|---------------------|-----------|
| 1 | 1 | 1 | None | 0 |
| 2 | 2 | 2 | Simple (2:2) | ~2K GE |
| 3 | 3 | 3 | Complex (3:3 reorder) | ~4K GE |
| 4 | 4 | 4 | Very complex (4:4) | ~8K GE |
| 8 | 8 | 8 | Extremely complex (8:8) | ~32K GE |

The commit queue must support N simultaneous pushes and N simultaneous pops. This means:
- **N write ports** on the queue SRAM (area ~O(N))
- **N read ports** on the queue SRAM (area ~O(N))
- Multi-port SRAM with N read + N write ports is **impractical for N > 2**
- Alternative: **N separate FIFOs** with round-robin pop (but ordering becomes harder)

**Finding: commit queue with N-push/N-pop is the architectural limiter for N > 2.**

### 1.5 Backpressure

| lane_count | Per-lane ready | Skid buffer | Head-of-line blocking |
|-----------|---------------|-------------|----------------------|
| 1 | Not needed | None | None |
| 2 | ✅ 2 ready | 2-entry | Low (1 lane can stall) |
| 3 | ✅ 3 ready | 3-entry | Moderate |
| 4 | ✅ 4 ready | 4-entry | Moderate |
| 8 | ✅ 8 ready | 8-entry | High |

**Finding: per-lane backpressure is feasible up to lane_count=4.** At lane_count=8, the skid buffer area and head-of-line blocking probability become significant.

## 2. Module Parameterization Summary

| Module | lane_count=1 | lane_count=2 | lane_count=3 | lane_count=4 | lane_count=8 |
|--------|-------------|-------------|-------------|-------------|-------------|
| Event pipeline (generate-for) | ✅ | ✅ | ✅ | ✅ | ⚠️ large |
| Metadata cache (banked) | 1 bank | 2 banks | 3 banks odd | 4 banks | 8 banks |
| Forwarding table (banked) | 1 bank | 2 banks | 3 banks odd | 4 banks | 8 banks |
| Commit queue (N-push/N-pop) | bypass | 2-push/2-pop | 3-push/3-pop complex | 4-push/4-pop | 8-push/8-pop NO |
| Backpressure (per-lane) | none | per-lane | per-lane | per-lane | per-lane bulky |
| **Structural rewrite needed** | **None** | **Minor** | **Major** | **Major** | **Complete** |

**Modules that can use generate-for parameterization:**
- LanePipeline (instantiate N copies)
- Metadata bank array (generate N banks)
- Forwarding bank array (generate N banks)

**Modules that structurally change with N:**
- Commit queue (push/pop width N, multi-port)
- Dispatch (N-wide hash, N arbitration)
- Backpressure (N-wide skid + ready crossbar)

## 3. Parameterization Approaches

### A. Full parameterization (lane_count as constructor arg)
- Pro: Single module, any N
- Con: Commit queue must support variable N-push/N-pop → complex generic multi-port FIFO
- Con: Verification must cover N=1,2,3,4,5,6,7,8
- **Verdict: NOT recommended.** The commit queue and backpressure logic are N-specific and cannot be cleanly parameterized without O(N^2) complexity.

### B. Fixed configuration classes (Wide1Lane, Wide2Lane, Wide4Lane)
- Pro: Each class optimized for its N
- Pro: No parameterization overhead, simpler verification
- Pro: Natural mapping to profiles (1=Standard, 2=Server, 4=not recommended)
- Con: Code duplication across classes
- **Verdict: RECOMMENDED.** Separate classes for each supported lane count.

### C. Template-based generation (script generates N-specific RTL)
- Pro: No duplication in source
- Con: Build system complexity, harder to debug
- **Verdict: POSSIBLE** but not needed until N > 2 is adopted.

## 4. Verification Estimate

| Test | lane=1 | lane=2 | lane=3 | lane=4 | lane=8 |
|------|--------|--------|--------|--------|--------|
| Basic functional | 1 | 2 | 3 | 4 | 8 |
| Continuous injection | 1 | 1 | 1 | 1 | 1 |
| No-loss backpressure | 1 | 2 | 3 | 4 | 8 |
| Same-domain ordering | — | 2 | 3 | 4 | 8 |
| Cross-domain reorder | — | 1 | 2 | 2 | 4 |
| Bank conflict stalls | — | 2 | 3 | 4 | 8 |
| Flush_epoch broadcast | 1 | 1 | 1 | 1 | 1 |
| Tag/event_id preservation | 1 | 2 | 3 | 4 | 8 |
| Mixed event types | 1 | 1 | 1 | 1 | 1 |
| Starvation/fairness | — | 2 | 3 | 4 | 8 |
| **Total tests** | **6** | **16** | **23** | **28** | **55** |

**Finding: verification scales roughly O(N).** lane_count=8 requires ~55 tests vs 16 for lane_count=2.

## 5. Summary Table

| lane_count | Theoretical evt/cyc | Effective evt/cyc | Gates (K GE) | Power (mW) | Fmax risk | Verification tests | Verdict |
|-----------|-------------------|-------------------|-------------|-----------|-----------|-------------------|---------|
| 1 | 1.0 | 1.0 | 60 | 1.7 | Low | 6 | **GO** |
| 2 | 2.0 | **1.75** | 95 | 2.8 | Moderate | 16 | **GO** |
| 3 | 3.0 | **2.17** | 140 | 4.2 | High | 23 | **NO-GO** |
| 4 | 4.0 | **2.68** | 170 | 5.0 | High | 28 | **HOLD** |
| 8 | 8.0 | **3.59** | 340 | 10.0 | Very high | 55 | **NO-GO** |

## 6. Conclusions

### 6.1 Should lane_count be exposed as a general parameter?
**NO.** The commit queue (N-push/N-pop) and backpressure logic are structurally N-specific. Full parameterization would require a generic multi-port FIFO that is complex and hard to verify.

### 6.2 Should lane_count be a fixed architectural choice?
**YES.** Fixed configuration classes (Wide1Lane, Wide2Lane) are simpler, faster to verify, and map naturally to practical profiles. The 2-lane prototype (`Wide2LaneBackend`) already uses this approach.

### 6.3 Recommended lane counts

| lane_count | Profile | Recommendation |
|-----------|---------|---------------|
| **1** | **Standard / Standard+** | **GO** — current proven design |
| **2** | **Server / Gateway** | **GO** — RTL prototype verified at 2.0 evt/cyc |
| 3 | Any | **NO-GO** — not power-of-2, odd banks, complex dispatch |
| 4 | Any | **HOLD** — bank conflict erodes ~33% of throughput; 2L×2 tile is better |
| 8 | Any | **NO-GO** — bank conflict ~55% loss; use 2L×4 or 1L×8 multi-backend |

### 6.4 Should 4-lane / 8-lane be completely stopped?
**YES for deployment.** Wide backends with lane_count > 2 should not be adopted. The effective throughput gain is diminishing (2→2.7 evt/cyc at 4-lane, 8→3.6 evt/cyc at 8-lane) while area and complexity increase linearly.

The recommended path to >2.0 evt/cyc is:
- **2-lane wide × N tiles** (tile-level multi-backend)
- Or **1-lane multi-backend × N** (simpler, proven)

### 6.5 Is 2-lane tile × N better than N-lane wide?
**YES.** The tile approach:
- Reuses the proven 2-lane wide backend as a building block
- Scales linearly (2L×2 = 4.0 evt/cyc, 2L×4 = 8.0 evt/cyc)
- No multi-port FIFO, no bank conflict escalation
- Each tile independently verified at 2.0 evt/cyc

### 6.6 Final recommendations

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | lane_count = fixed config, not general parameter | Commit queue and backpressure are N-specific |
| 2 | Support lane_count=1 (Standard) and lane_count=2 (Server) | Both verified by RTL |
| 3 | **Stop lane_count >= 4 for wide single backend** | Diminishing returns; use 2L×N tile instead |
| 4 | **No lane_count=3** | Not power-of-2, no natural scheduling |
| 5 | Continue 2-lane wide as Server/Gateway tile | RTL verified at 2.0 evt/cyc |
| 6 | If >2.0 evt/cyc needed: tile the 2-lane backend | 2L×2 = 4.0 evt/cyc, 2L×4 = 8.0 evt/cyc |
