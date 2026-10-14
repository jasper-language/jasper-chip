# Jasper-GC Profiles Reference

> Date: 2026-06-07
> Status: PREPARATION_OK (all profiles elaborate; load_aware dispatch on HOLD for Extreme)

---

## Profile Overview

| Profile | Layout | Dispatch | Merge | Backpressure | Use Case |
|---------|--------|----------|-------|-------------|----------|
| Lite | 1L×1 | — | — | — | IoT, embedded |
| Standard | 1L×1 | — | — | — | Desktop, mobile |
| Standard+ | 1L×1 | — | — | — | Server basic, latency-sensitive |
| Gateway | 2L×1 | hash_lsb | ordered (bypass) | per_tile_ready | API gateway, edge |
| Server Base | 2L×2 | core_affinity | ordered | per_tile_skid | Entry server |
| Server | 2L×4 | hybrid | per_domain_queue | backpressure_aware | Production server |
| Extreme | 2L×8 | hybrid | hierarchical | credit_based | Research / R&D |

---

## Lite

**Config**: 1L×1, minimal
**Pipeline depth**: 8 (default)
**Fabric**: None (single tile)
**Features**: Minimal area, no fabric, no clock gating
**Use case**: IoT, embedded, microcontroller-class
**Status**: GO — all RTL verified

## Standard

**Config**: 1L×1, balanced
**Pipeline depth**: 8
**Fabric**: None (single tile)
**Features**: Metadata cache enabled (4 KB), stream buffer (4 entries), D-cache bypass
**Use case**: Desktop, mobile, general-purpose
**Status**: GO — all RTL verified

## Standard+

**Config**: 1L×1, latency-optimized
**Pipeline depth**: 4 (half of Standard)
**Fabric**: None (single tile)
**Features**: Reduced pipeline latency (3 cyc vs 7 cyc) at cost of reduced timing margin
**Use case**: Server basic, latency-sensitive workloads
**Status**: GO — all RTL verified

## Gateway

**Config**: 2L×1
**Pipeline depth**: 8
**Fabric**: hash_lsb dispatch (policy 2), ordered merge (bypass for single tile)
**Backpressure**: per_tile_ready
**Features**: Dual-lane tile, no cluster fabric needed (single tile), hash-based load distribution
**Use case**: API gateway, edge server, throughput-sensitive single-tile applications
**Key limitation**: Single tile only; no multi-tile scaling
**Status**: GO — all RTL verified

## Server Base

**Config**: 2L×2
**Pipeline depth**: 8
**Fabric**: core_affinity dispatch (policy 0), ordered global merge
**Backpressure**: per_tile_skid (SkidBuffer depth=2)
**Features**: Per-tile partition, two-tile cluster, SkidBuffer absorbs backpressure bubbles
**Use case**: Entry-level server, mid-range throughput
**Status**: GO — all RTL verified

## Server

**Config**: 2L×4
**Pipeline depth**: 8
**Fabric**: hybrid dispatch (policy 4: core_affinity with fallback), ordered per_domain_queue merge

Large synthesis note: ready-aware dispatch modes (`BACKPRESSURE_AWARE`, `HYBRID`,
`LOAD_AWARE`) are intended for small and medium RTL fabrics. For
domain-partitioned large profiles (`tile_count > 32`), `JasperGCUnifiedConfig`
forces static `HASH_LSB` routing because ready-aware selection feeds lane
`ready` back into tile selection and can create an unacceptable ready-to-data
combinational path in flat synthesis.
**Backpressure**: backpressure_aware (policy 3: skip blocked tiles)
**Features**: Load-based enable power management, per_domain_queue (depth=8), four-tile cluster
**Use case**: Production server, high-throughput workloads
**Status**: GO — hybrid policy verified, load-based enable RTL_PARTIAL (counter works, fabric integration pending)

## Extreme

**Config**: 2L×8
**Pipeline depth**: 8
**Fabric**: hybrid dispatch (policy 4), hierarchical merge (research)
**Backpressure**: credit_based (research)
**Features**: **_status_hold = TRUE** for all sub-modules — research configuration
**Use case**: Research, future high-end evaluation
**Status**: **HOLD** — load_aware dispatch not RTL-implemented, hierarchical merge and credit_based backpressure are INTENT_ONLY. Not a default profile.

---

## Key Restrictions

| Restriction | Detail |
|-------------|--------|
| `tile_count` = 2^N | Valid: 1, 2, 4, 8, 16. Non-power-of-2 is NOT supported. |
| `lane_per_tile` ∈ {1, 2} | 1 for Lite/Standard/Standard+, 2 for Gateway/Server/Extreme |
| 4L/8L wide | **NOT** a supported path. Bank conflict analysis: 33% loss at 4L, 55% at 8L. |
| load_aware dispatch | **NOT implemented** (HOLD). Policy 5+ reserved for Extreme only. |
| credit_based backpressure | **NOT implemented** (HOLD). Future research for Extreme. |
| hierarchical merge | **NOT implemented** (HOLD). Future research for Extreme. |
