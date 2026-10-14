# Jasper-GC Core — Overview

> Document version: 1.0 (2026-06-07)
> Status: PREPARATION_OK

---

## 1. What is Jasper-GC?

Jasper-GC is a **unified, configurable core** for hardware-accelerated garbage collection. It is not a family of separate designs — all variants are derived from a single RTL codebase controlled by a hierarchical configuration object (`JasperGCConfig`).

## 2. Profiles Are Parameter Combinations

**Standard**, **Gateway**, **Server**, etc. are **profiles** — named parameter combinations — not separate designs or code branches. A single `JasperGCConfig` object drives elaboration of exactly one module topology per profile. There is no `#ifdef` branching; the config fields select pipeline depth, tile count, dispatch policy, merge policy, and backpressure scheme.

## 3. 1L / 2L / 2L×N Are the Same Design

The 1-lane backend, 2-lane tile, and 2L×N cluster are the **same core instantiated with different configurations**:

| Instantiation | `lane_per_tile` | `tile_count` | Throughput |
|---------------|----------------|--------------|------------|
| 1L (single lane) | 1 | 1 | 1.0 evt/cyc |
| 2L (dual-lane tile) | 2 | 1 | 2.0 evt/cyc |
| 2L×2 (two tiles) | 2 | 2 | 4.0 evt/cyc |
| 2L×4 (four tiles) | 2 | 4 | 8.0 evt/cyc |

No separate codebase exists for any variant.

## 4. Architecture

```
GC Event Pipeline → Forwarding Table → Metadata Cache → Backend Merge
    → [Fabric Dispatch] → Tile 0..N-1 (each: 1L or 2L backend)
    → [Ordered Global Merge] (multi-tile only)
    → [Fabric Coordinator] → GC Result
```

The architecture is a linear pipeline per lane, replicated within a tile, and tiles are replicated within a cluster. The fabric layer (dispatch + ordered global merge) is only instantiated when `tile_count > 1`.

## 5. Key Features

- **No-loss backpressure**: All pipeline stages implement valid/ready handshake. Verified by strict no-loss tests (N=3), bounded no-loss (N=10), and FIFO-full backpressure stress (8 events through depth=2).
- **Round-robin merge fairness**: `rr_start` register prevents domain-0 starvation in ordered global merge. Verified by multi-tile starvation test.
- **Epoch/flush consistency**: Epoch and flush signals propagate through event pipeline, metadata cache, and forwarding table. Cross-module verified.
- **Configurable queue depth**: `pipeline_depth` (4/8), `queue_depth` (8/16/32), FIFO depths all parameterized.

## 6. Verification

| Component | Tests | Status |
|-----------|-------|--------|
| Backend (1L/2L/tile/cluster) | 43+ tests | ✅ All passing |
| Fabric (dispatch/merge/skid/power) | 43 tests | ✅ All passing |
| Total | 86+ tests | ✅ 100% pass |

## 7. Current Status

| Layer | Status |
|-------|--------|
| Backend core (1L/2L/tile/cluster) | **CEILING_REACHED** |
| Fabric (dispatch/merge/skid/power) | **NEAR_FINAL** |
| readiness | **PREPARATION_OK** |

The backend has reached its structural throughput ceiling (1.0 evt/cyc per lane). The fabric is near-final with 43/43 RTL tests passing. Remaining items are documentation, parameter lock-in, and physical design handoff — no further architectural exploration is required.

## 8. Interface

Jasper-GC is core-internal with:
- **Frontend interface**: GC event push from core pipeline (event_valid/ready, event_tag, event_type, epoch)
- **Backend interface**: GC result return to core (result_valid/ready, result_tag, result_status)
- **Memory interface**: AXI4 or equivalent for heap access (metadata read/write, object forward/relocate)
- **External accelerator interface**: Placeholder/reserved for future CXL-attached GC offload (see `jasper_gc_external_interface.md`)
