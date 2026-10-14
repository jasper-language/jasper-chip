# 2^n Scalability Limit Study

## Objective

Determine the practical limit of 2L tile × 2^n scaling,
and identify the bottlenecks that emerge as n increases.

## 1. Configuration

- Lane per tile: 2
- Tile count: 2^n
- Theoretical throughput: 2 × 2^n = 2^(n+1) evt/cyc
- Tested n: 0–6 (tiles 1–64)

## 2. Scaling Table

| n | Tiles | Ideal (evt/cyc) | RTL | Model | Bottleneck | Status |
|---|-------|-----------------|-----|-------|-----------|--------|
| 0 | 1 | 2.0 | ✅ 2.0 | — | — | **GO** |
| 1 | 2 | 4.0 | ✅ 4.0 | — | — | **GO** |
| 2 | 4 | 8.0 | ✅ 8.0 | — | — | **GO** |
| 3 | 8 | 16.0 | — | ✅ ~14.0 | Merge tree depth | **HOLD** |
| 4 | 16 | 32.0 | — | ✅ ~28.0 | Interconnect BW | **HOLD** |
| 5 | 32 | 64.0 | — | ✅ ~56.0 | Memory BW | **MODEL** |
| 6 | 64 | 128.0 | — | ✅ ~110.0 | DRAM BW | **MODEL** |

## 3. Bottleneck Analysis

### n=0–2 (GO, RTL verified)

| Component | n=0 (1 tile) | n=1 (2 tiles) | n=2 (4 tiles) |
|-----------|-------------|--------------|--------------|
| Dispatcher depth | 0 | 1 | 2 |
| Merge tree depth | 0 | 1 | 2 |
| Merge nodes | 0 | 1 | 3 |
| Metadata banks | 2 | 4 | 8 |
| Forwarding banks | 2 | 4 | 8 |
| Gates estimate | 95K | 190K | 380K |
| Power @10%GC | 2.8 mW | 5.6 mW | 11.2 mW |

### n=3 (8 tiles, HOLD)

| Parameter | Value | Risk |
|-----------|-------|------|
| Merge tree depth | 3 (8→4→2→1) | Moderate |
| Merge latency | ~6 cycles | Ordering window grows |
| Metadata banks | 16 | Bank conflict ~50% |
| Dispatcher hash bits | 3 | Fine |
| Estimated gates | ~760K | Large but feasible |
| Estimated power | ~22.4 mW | High for mobile |

**First bottleneck: merge tree latency.** The 8→4→2→1 merge introduces
~6 cycles of latency. Same-domain ordering requires buffering events
across this window. Reorder buffer depth grows with tile count.

### n=4 (16 tiles, HOLD)

| Parameter | Value | Risk |
|-----------|-------|------|
| Merge tree depth | 4 | High |
| Merge latency | ~8 cycles | Large reorder buffer |
| Interconnect BW | 32 evt/cyc | **System-level bottleneck** |
| Dispatcher | 16-way | Large MUX tree |

**First bottleneck: interconnect bandwidth.** Moving 32 events/cycle
between tiles requires a crossbar or ring interconnect. This is a
system-level problem, not a GC backend problem.

### n=5 (32 tiles, MODEL only)

| Parameter | Value | Risk |
|-----------|-------|------|
| Merge tree depth | 5 | Very high |
| Merge latency | ~10 cycles | Reorder buffer impractically large |
| Memory bandwidth | ~64 GB/s @ 2 GHz | DRAM channel limited |
| Power | ~90 mW | Significant thermal density |

**First bottleneck: memory bandwidth.** At 64 evt/cyc, the system
needs 64 memory accesses per cycle. At 2 GHz: 128 GB/s. This exceeds
a typical DDR5 channel (~50 GB/s). Multiple memory channels needed.

### n=6 (64 tiles, MODEL only)

| Parameter | Value | Risk |
|-----------|-------|------|
| Merge tree depth | 6 | Prohibitive |
| Memory bandwidth | ~256 GB/s @ 2 GHz | 4+ DDR5 channels |
| Power | ~180 mW | Cooling challenge |

**First bottleneck: DRAM bandwidth.** The GC backend is no longer
the bottleneck — the memory system is.

## 4. Bottleneck Transition

As n increases, the bottleneck shifts:

```
n=0–2: GC backend (merge output)
n=3:   Merge tree latency + reorder buffer
n=4:   Interconnect bandwidth
n=5:   Memory bandwidth
n=6+:  DRAM channels / system power
```

**Key insight: The GC backend is NOT the bottleneck for n ≥ 3.**
System-level components (interconnect, memory, power) dominate.

## 5. Recommended Limits

| Limit | n | Tiles | evt/cyc | Rationale |
|-------|---|-------|---------|-----------|
| **Practical** | **0–2** | **1–4** | **2–8** | RTL verified, practical |
| **Research** | **3–4** | **8–16** | **16–32** | Feasible with system work |
| **Model only** | **5–6** | **32–64** | **64–128** | Memory/interconnect bound |

## 6. Conclusions

### Q1: Can 2L × 2^n scale infinitely?
**Architecturally yes, practically no.** The dispatch, merge, and
ordering all scale as O(log n), so the GC backend itself has no
fundamental ceiling. System-level components (interconnect, memory
bandwidth, power) are the real limiters at n ≥ 3.

### Q2: What is the first non-GC-backend bottleneck?
**Interconnect bandwidth at n=4 (16 tiles, 32 evt/cyc).** At this
point, moving results between tiles and to DRAM becomes the dominant
cost.

### Q3: Recommended practical limit?
**n=2 (4 tiles, 8 evt/cyc).** RTL verified, merge tree depth=2,
practical area (~380K GE), reasonable power (~11 mW).

### Q4: Research limit?
**n=3–4 (8–16 tiles, 16–32 evt/cyc).** Feasible with system-level
investment in interconnect and memory hierarchy.

### Q5: Should n be exposed externally?
**NO.** Expose profiles (Gateway, Server, Extreme), not n.
Internally, n = log2(tile_count) as a derived parameter.

### Q6: Is "no fixed ceiling" a valid statement?
**Yes, with caveat:** "GC backend architecture has no fixed structural
ceiling; system-level resources (interconnect, memory bandwidth) are
the practical limiters at large tile counts."

## 7. Recommended Profiles

| Profile | n | Tiles | evt/cyc | Gates | Power | Status |
|---------|---|-------|---------|-------|-------|--------|
| Lite/MCU | — | 1 × 1L | 1.0 | ~40K | ~1 mW | **GO** |
| Standard | 0 | 1 | 2.0 | ~95K | ~2.8 mW | **GO** |
| Gateway | 0 | 1 | 2.0 | ~95K | ~2.8 mW | **GO** |
| Server Base | 1 | 2 | 4.0 | ~190K | ~5.6 mW | **GO** |
| Server | 2 | 4 | 8.0 | ~380K | ~11.2 mW | **GO** |
| Extreme | 3 | 8 | 16.0 | ~760K | ~22.4 mW | **HOLD** |
| R&D | 4+ | 16+ | 32.0+ | ~1.5M+ | ~45 mW+ | **MODEL** |
