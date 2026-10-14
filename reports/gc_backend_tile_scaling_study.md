# Backend Tile Scaling Study

## Objective

Determine the optimal backend tile size for scaling GC throughput. Compare narrow 1-lane replication vs wide 2-lane/4-lane tiles as the basic building block for multi-backend clusters.

## 1. Tile Definitions

### 1L tile (baseline)
- Single lane, 1.0 evt/cyc
- Proven RTL: all 16 test suites pass at 1.000/cyc
- Gates: ~60K GE
- Power @10%: ~1.7 mW

### 2L wide tile
- Dual lane, 2.0 evt/cyc theoretical
- Requires: 2-wide event pipeline, banked metadata (×2), banked forwarding (×2), 2-output merge
- Gates: ~95K GE (shared controller amortized)
- Power @10%: ~2.8 mW

### 4L wide tile
- Quad lane, 4.0 evt/cyc theoretical
- Requires: 4-wide everything, bank conflict arbitration, commit queue
- Gates: ~170K GE
- Power @10%: ~5.0 mW

## 2. Configuration Matrix

| Config | Lanes/tile | Tiles | Total lanes | Total evt/cyc | Gates (K GE) | Power @10% (mW) |
|--------|-----------|-------|-------------|---------------|-------------|-----------------|
| 1L×1 | 1 | 1 | 1 | 1.0 | 60 | 1.7 |
| 1L×2 | 1 | 2 | 2 | 2.0 | 125 | 3.6 |
| 1L×4 | 1 | 4 | 4 | 4.0 | 250 | 7.2 |
| 1L×8 | 1 | 8 | 8 | 8.0 | 500 | 14.4 |
| **2L×1** | **2** | **1** | **2** | **2.0** | **95** | **2.8** |
| **2L×2** | **2** | **2** | **4** | **4.0** | **190** | **5.6** |
| 2L×4 | 2 | 4 | 8 | 8.0 | 380 | 11.2 |
| 4L×1 | 4 | 1 | 4 | 4.0 | 170 | 5.0 |
| 4L×2 | 4 | 2 | 8 | 8.0 | 340 | 10.0 |

## 3. Efficiency Metrics

| Config | GE/evt | mW/evt | Area vs 1L×N | Power vs 1L×N |
|--------|--------|--------|-------------|--------------|
| 1L×1 | 60.0K | 1.70 | baseline | baseline |
| 1L×2 | 62.5K | 1.80 | baseline | baseline |
| 1L×4 | 62.5K | 1.80 | baseline | baseline |
| 1L×8 | 62.5K | 1.80 | baseline | baseline |
| **2L×1** | **47.5K** | **1.40** | **-24%** | **-22%** |
| **2L×2** | **47.5K** | **1.40** | **-24%** | **-22%** |
| 2L×4 | 47.5K | 1.40 | -24% | -22% |
| 4L×1 | 42.5K | 1.25 | -32% | -31% |
| 4L×2 | 42.5K | 1.25 | -32% | -31% |

### Key insight

**2L tile is 24% more area-efficient and 22% more power-efficient than 1L replication at the same total throughput.** 4L tile gains another ~10% but at significantly higher complexity.

## 4. Complexity Assessment

| Config | Fmax risk | Verification | Dispatch | Merge | Bank conflict | Ordering | Backpressure |
|--------|----------|-------------|----------|-------|--------------|----------|-------------|
| 1L×1 | Low | ✅ 16 suites | — | — | None | — | ✅ |
| 1L×2 | Low | Moderate (dispatch) | Simple (hash) | Gather+order | None | Per-domain | ✅ |
| 1L×4 | Low | Moderate | Simple (hash) | Gather+order | None | Per-domain | ✅ |
| 1L×8 | Low | Moderate | Simple (hash) | Gather+order | None | Per-domain | ✅ |
| **2L×1** | **Moderate** | **Hard (new RTL)** | **Per-lane hash** | **2:1 commit queue** | **~25% loss** | **Queue** | **Per-lane skid** |
| **2L×2** | **Moderate** | **Harder** | **Dual: tile+ lane** | **2-level** | **~25% loss** | **2-level** | **2-level** |
| 2L×4 | Moderate | Hardest | 2-level | 2-level | ~25% loss | 2-level | 2-level |
| 4L×1 | High | Very hard | 4-lane hash | 4:1 commit queue | ~50% loss | Complex queue | 4-lane skid |
| 4L×2 | High | Very hard | 2-level | 2-level | ~50% loss | Very complex | 2-level |

### Assessment

- **1L tile: low risk.** Proven RTL. Dispatch and merge are the only new modules.
- **2L tile: moderate risk.** Bank conflict causes ~25% throughput loss vs ideal. New RTL for wide pipeline, banked metadata, banked forwarding, commit queue.
- **4L tile: high risk.** ~50% throughput loss from bank conflicts. Very wide muxes reduce Fmax. Complex 4:1 commit queue.

## 5. Cluster Affinity

| Config | Multi-core fit | NUMA fit | Gateway fit | Server fit | Mobile fit |
|--------|---------------|----------|-------------|------------|-----------|
| 1L×1 | Per-core | 1 per node | Overkill | Too weak | ✅ |
| 1L×2 | 2 cores share | 2 per node | ✅ | ✅ | Overkill |
| 1L×4 | 4 cores share | 4 per node | ✅ | ✅ | ❌ |
| 1L×8 | 8 cores share | 8 per node | Overkill | ✅ | ❌ |
| 2L×1 | Per-core (wide) | 1 per node | ✅ | Good | Overkill |
| 2L×2 | 2 cores (wide) | 2 per node | ✅ Best | ✅ Best | ❌ |
| 2L×4 | 4 cores (wide) | 4 per node | Overkill | ✅ | ❌ |
| 4L×1 | Per-core (very wide) | 1 per node | Overkill | ✅ | ❌ |
| 4L×2 | 2 cores (very wide) | 2 per node | Overkill | ✅ | ❌ |

## 6. Recommendations

### 6.1 Is 2L wide tile more area-efficient than 2× 1L?

**YES.** 2L×1 = 95K GE vs 1L×2 = 125K GE. **-24% area, -22% power.** The savings come from shared controller, shared cycle logic, and shared frontend interface.

### 6.2 Is 2L×2 better than 1L×4 for 4 evt/cyc?

**YES for area/power (190K vs 250K GE, -24%). NO for verification risk.**
If area/power are the primary constraints, 2L×2 is better. If time-to-market and verification simplicity are primary, 1L×4 is better (reuses proven RTL).

### 6.3 Is 4L tile too complex to be worthwhile?

**YES — HOLD.** The bank conflict loss (~50% effective), very wide muxes, and complex commit queue make 4L unattractive. At 4 evt/cyc, 2L×2 gives the same throughput with much lower risk. At 8 evt/cyc, 1L×8 or 2L×4 are better options.

### 6.4 Is 2L tile suitable as the basic cluster building block?

**YES — but only for area/power-constrained designs.** For most Server/Gateway profiles, the 24% area savings of 2L tile does not justify the new RTL development and verification cost. 1L tile reuse is the safer path.

### 6.5 Should multi-backend use tiles or single-lane backends?

**Recommendation: start with 1L tile replication, evaluate 2L tile later.**

| Phase | Approach | Rationale |
|-------|----------|-----------|
| Phase 1 | 1L×N dispatch + merge | Reuses existing 1.0/cyc RTL, low risk |
| Phase 2 | 2L×1 RTL prototype | Evaluate if 24% area savings worth the complexity |
| Phase 3 | 2L×N tile cluster | If Phase 2 successful, generalize to N tiles |
| Phase 4 | 4L evaluation | Only if 2L hits insufficient throughput per tile |

## 7. Final Conclusion

| Question | Answer |
|----------|--------|
| Recommended tile size | **1L (single lane) — reuse existing RTL** |
| 2L tile worth RTL prototype? | **HOLD** — area savings modest vs verification cost |
| 4L tile worth pursuing? | **NO-GO** — bank conflicts + Fmax + merge complexity |
| Server/Gateway profile | **1L×2 to 1L×4** depending on throughput target |
| Area-efficient alternative | **2L×2** if area is critical (190K vs 250K GE) |
| Next step | Start 1L×N multi-backend dispatch + merge RTL |

## 8. Recommended Server/Gateway Profiles

| Profile | Lanes | Backends | Total evt/cyc | Config | Gates |
|---------|-------|----------|---------------|--------|-------|
| Gateway Normal | 1 | 2 | 2.0 | 1L×2 | 125K |
| Gateway Heavy | 1 | 4 | 4.0 | 1L×4 | 250K |
| Gateway Extreme | 1 | 8 | 8.0 | 1L×8 | 500K |
| Server GC ≤20% | 2 | 1 | 2.0 | 2L×1 | 95K |
| Server GC ≤40% | 2 | 2 | 4.0 | 2L×2 | 190K |
| Server GC ≤80% | 2 | 4 | 8.0 | 2L×4 | 380K |
