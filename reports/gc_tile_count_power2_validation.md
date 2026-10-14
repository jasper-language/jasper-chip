# Tile Count 2^N Dimensional Validation

## Objective

Determine whether multi-backend tile_count should be restricted to powers of 2
(1, 2, 4, 8, 16) for profiles, or whether non-2^N counts (3, 5, 6, 7)
are viable.

## 1. Dispatch Complexity

### 1.1 hash_lsb (address bit select)

| tile_count | bits | mapping | hardware |
|-----------|------|---------|----------|
| 1 | 0 | addr[0:0] = 0 | None (no dispatch) |
| 2 | 1 | addr[0] | Wire |
| 3 | ~1.58 | addr % 3 | **Modulo (divider)** |
| 4 | 2 | addr[1:0] | Wire |
| 5 | ~2.32 | addr % 5 | **Modulo (divider)** |
| 6 | ~2.58 | addr % 6 | **Modulo (divider)** |
| 7 | ~2.81 | addr % 7 | **Modulo (divider)** |
| 8 | 3 | addr[2:0] | Wire |
| 16 | 4 | addr[3:0] | Wire |

**Finding:** For non-2^N, hash_lsb requires a hardware modulo (divider) which
adds significant area (~200–500 GE) and timing delay (2–5 mux depths).
For 2^N, only a bit slice is needed → 0 GE, 0 delay.

### 1.2 round_robin

Round-robin dispatch uses a counter. For any tile_count, the counter
wraps at tile_count-1. Wrapping logic:
- 2^N: `Mux(counter == N-1, 0, counter+1)` — standard Mux
- non-2^N: `Mux(counter == N-1, 0, counter+1)` — same Mux

Both work identically. Round-robin has NO 2^N advantage.

### 1.3 region_affinity

Heap region IDs are naturally power-of-2 aligned. With 2^N tiles:
- region_id[N-1:0] directly selects tile
- With non-2^N: region_id % tile_count skews distribution

### 1.4 core_affinity

Cores often come in 2^N groups (1, 2, 4, 8, 16). Tile bindings:
- 8 cores → 2 tiles (4 cores/tile): 2^N alignment
- 8 cores → 3 tiles (2.67 cores/tile): load imbalance

### Dispatch Cost Summary

| Policy | 2^N cost | non-2^N cost | Delta |
|--------|---------|-------------|-------|
| hash_lsb | 0 GE (bit slice) | ~350 GE (modulo) | +350 GE |
| round_robin | negligible | negligible | 0 |
| region_affinity | 0 GE (bit slice) | ~350 GE (modulo) | +350 GE |
| core_affinity | 0 GE (alignment) | structural skew | — |

## 2. Merge Tree Complexity

### 2.1 Balanced vs Unbalanced Trees

| tile_count | tree depth | structure | balance | Notes |
|-----------|-----------|-----------|---------|-------|
| 1 | 0 | — | perfect | No merge needed |
| 2 | 1 | 2→1 | perfect | |
| 3 | 2 | (2→1)+(1→1) | **unbalanced** | 2 tiles merge, 1 bypass |
| 4 | 2 | 4→2→1 | perfect | |
| 5 | 3 | (2+2+1)→(2+1)→1 | **unbalanced** | Odd grouping |
| 6 | 3 | (2+2+2)→(2+1)→1 | unbalanced | |
| 7 | 3 | (2+2+2+1)→(2+1)→1 | unbalanced | |
| 8 | 3 | 8→4→2→1 | perfect | |
| 16 | 4 | 16→8→4→2→1 | perfect | |

### 2.2 Dummy Lane Requirement

For non-2^N merge trees, some merge nodes have only 1 input (bypass).
These require:
- Special bypass muxes
- Asymmetric latency paths
- Reorder buffers to compensate

For 2^N trees, all merge nodes have exactly 2 inputs → uniform latency.

### Merge Tree Cost Summary

| tile_count | Merge stages | Balance | Dummy lanes | Asymmetric latency |
|-----------|-------------|---------|-------------|-------------------|
| 1 | 0 | perfect | 0 | none |
| 2 | 1 | perfect | 0 | none |
| 3 | 2 | unbalanced | 1 | yes |
| 4 | 2 | perfect | 0 | none |
| 5 | 3 | unbalanced | 2 | yes |
| 6 | 3 | unbalanced | 1 | yes |
| 7 | 3 | unbalanced | 1 | yes |
| 8 | 3 | perfect | 0 | none |
| 16 | 4 | perfect | 0 | none |

## 3. Bank / Region Alignment

| tile_count | metadata banks | forwarding banks | region alignment |
|-----------|---------------|-----------------|-----------------|
| 1 | 1 | 1 | perfect |
| 2 | 2 | 2 | perfect |
| 3 | 3 | 3 | **skewed** (1/3 each) |
| 4 | 4 | 4 | perfect |
| 5 | 5 | 5 | skewed (1/5 each) |
| 6 | 6 | 6 | skewed (1/6 each) |
| 7 | 7 | 7 | skewed (1/7 each) |
| 8 | 8 | 8 | perfect |
| 16 | 16 | 16 | perfect |

For 2^N, bank address = addr[log2(banks)-1:0] — direct bit slice.
For non-2^N, bank address requires addr % bank_count — modulo.

**Bank conflict probability** follows the same analysis as the lane parameterization
study: 2^N has uniform distribution; non-2^N has modulo bias.

## 4. Throughput Efficiency

### Model

- Each tile: 2.0 evt/cyc (dual-input)
- Dispatch: hash_lsb (2^N) or modulo (non-2^N)
- Merge: balanced tree (2^N) or unbalanced (non-2^N)
- Loss factors: bank conflict (~12.5% for 2-lane), merge imbalance

| tile_count | Ideal | Effective | Efficiency | Loss reason |
|-----------|-------|-----------|------------|-------------|
| 1 | 2.0 | 1.75 | 87.5% | Bank conflict (12.5%) |
| 2 | 4.0 | 3.50 | 87.5% | Bank conflict |
| 3 | 6.0 | ~5.0 | ~83% | Bank conflict + merge skew |
| 4 | 8.0 | 7.00 | 87.5% | Bank conflict |
| 5 | 10.0 | ~8.2 | ~82% | Bank conflict + merge + modulo |
| 6 | 12.0 | ~10.0 | ~83% | Bank conflict + merge skew |
| 7 | 14.0 | ~11.5 | ~82% | Bank conflict + merge skew |
| 8 | 16.0 | 14.00 | 87.5% | Bank conflict |
| 16 | 32.0 | 28.00 | 87.5% | Bank conflict |

**Finding:** Efficiency is dominated by per-tile bank conflict (~12.5% for 2-lane),
not by tile_count. Non-2^N adds ~5% additional loss from merge imbalance and
modulo dispatch overhead. The throughput difference between 2^N and non-2^N
at the same total lane count is small (~5%). However, the verification and
hardware costs are significantly higher for non-2^N.

## 5. Verification Complexity

| tile_count | Unit tests | Dispatch tests | Merge tests | Ordering tests | Total (est.) |
|-----------|-----------|---------------|-------------|---------------|-------------|
| 1 | 7 | 0 | 0 | 1 | 8 |
| 2 | 7 | 2 | 2 | 3 | 14 |
| 3 | 7 | 4 | 5 | 5 | 21 |
| 4 | 7 | 2 | 3 | 3 | 15 |
| 5 | 7 | 6 | 8 | 7 | 28 |
| 6 | 7 | 6 | 7 | 6 | 26 |
| 7 | 7 | 6 | 7 | 6 | 26 |
| 8 | 7 | 3 | 4 | 4 | 18 |
| 16 | 7 | 4 | 5 | 5 | 21 |

**Key insight:** tile_count=3 has MORE tests than tile_count=4 (21 vs 15)
because of unbalanced merge tree testing. The non-2^N cases don't benefit
from symmetry.

## 6. 2^N Decision Table

| tile_count | Dispatch | Merge | Bank align | Verification | Recommendation |
|-----------|---------|-------|-----------|-------------|---------------|
| **1** | ✅ 0 GE | — | ✅ | 8 tests | **GO** |
| **2** | ✅ 0 GE | ✅ balanced | ✅ | 14 tests | **GO** |
| 3 | ❌ modulo | ❌ unbalanced | ❌ skewed | 21 tests | **NO-GO** |
| **4** | ✅ 0 GE | ✅ balanced | ✅ | 15 tests | **GO** |
| 5 | ❌ modulo | ❌ unbalanced | ❌ skewed | 28 tests | **NO-GO** |
| 6 | ❌ modulo | ❌ unbalanced | ❌ skewed | 26 tests | **INTERNAL** |
| 7 | ❌ modulo | ❌ unbalanced | ❌ skewed | 26 tests | **NO-GO** |
| **8** | ✅ 0 GE | ✅ balanced | ✅ | 18 tests | **GO** |
| **16** | ✅ 0 GE | ✅ balanced | ✅ | 21 tests | **HOLD** (future) |

## 7. Conclusions

### Q1: Should tile_count be RTL-internal parameter?
**YES.** The tile infrastructure supports any tile_count. RTL parameterization
via generate-for loops is straightforward for tiles, dispatch, and merge.

### Q2: Should tile_count be an external (user-visible) parameter?
**NO.** Only 2^N should be exposed as profiles. Non-2^N should be
internal test/development parameters only.

### Q3: Should profiles be restricted to 1/2/4/8/16?
**YES.** These are the natural alignment for:
- Address hash (bit slicing)
- Merge tree (balanced binary)
- Bank count (2^N alignment)
- Core count (2^N core groups)
- Verification symmetry

### Q4: Should non-2^N be NO-GO or INTERNAL_ONLY?
| tile_count | classification |
|-----------|---------------|
| 3 | **NO-GO** — modulo cost, unbalanced merge, 21 tests |
| 5 | **NO-GO** — modulo cost, unbalanced merge, 28 tests |
| 6 | **INTERNAL_ONLY** — for testing, not deployment |
| 7 | **NO-GO** — modulo cost, unbalanced merge, 26 tests |

### Q5: What are the advantages of 2^N over non-2^N?
1. **Zero-cost dispatch** (bit slice vs modulo)
2. **Balanced merge tree** (uniform latency)
3. **Natural bank alignment** (no skew)
4. **Lower verification cost** (symmetry reduces test count by ~30%)
5. **Core affinity alignment** (cores = 2^N)

### Q6: Is 2L tile × 2^N the final scaling path?
**YES.** The combination of proven 2L tile (2.0 evt/cyc) × 2^N tile_count
provides: 2, 4, 8, 16, 32 evt/cyc across 1, 2, 4, 8, 16 tiles.

### Q7: Are non-2^N tile counts worth supporting?
**Not for deployment.** The hardware cost (modulo), verification cost (+30% tests),
and merge tree imbalance do not justify <5% throughput gain vs nearest 2^N.

### Q8: Final Profile Recommendations

| Profile | tile_count | Lane/tile | evt/cyc | Gates | Status |
|---------|-----------|-----------|---------|-------|--------|
| Lite/MCU | 1 | 1 | 1.0 | ~40K | **GO** |
| Standard | 1 | 1 | 1.0 | ~60K | **GO** |
| Gateway | 1 | 2 | 2.0 | ~95K | **GO** |
| Server Base | 2 | 2 | 4.0 | ~190K | **GO** |
| Server | 4 | 2 | 8.0 | ~380K | **GO** |
| Extreme | 8 | 2 | 16.0 | ~760K | **HOLD** |
| R&D | 16 | 2 | 32.0 | ~1.5M | **HOLD** |
