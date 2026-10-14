# JasperGC Accelerator — Overview

## 1. What is JasperGC Accelerator

JasperGC Accelerator is a dedicated hardware engine that offloads cold-path garbage collection operations from the JasperGC Core. It is designed as an external coprocessor that communicates with Core via command/completion queues.

## 2. How It Differs from JasperGC Core

| Aspect              | Core                          | Accelerator                    |
|---------------------|----------------------------------|-----------------------------------|
| Path                | Hot path (WB, RB, forwarding)    | Cold path (scan, sweep, compact)  |
| Sensitivity         | Latency-critical (per mutator op) | Throughput-critical (per region)  |
| Integration         | Tightly coupled in pipeline       | External coprocessor layer        |
| Memory access       | Direct, inline                    | Bulk DMA / coherent fabric access |
| Scaling             | Tied to core tile count           | Independent accelerator instance  |
| Typical queue depth | N/A (inline)                     | 4–32 commands                     |

## 3. When Accelerator Is Needed (Server/Extreme Profiles)

- **Server profile**: Heap >64 GB, >32 mutator threads. Core cannot sustain cold-path throughput without stealing hot-path issue slots.
- **Extreme profile**: Multi-terabyte heaps, HBM tiering, concurrent compaction. Dedicated accelerator engines are required to meet throughput targets.

In Lite and Standard profiles the accelerator is optional — cold-path may be handled by Core software fallback.

## 4. Hot Path vs Cold Path Boundary

```
Hot Path (Core)           Cold Path (Accelerator)
─────────────────            ─────────────────────────
Write Barrier                Scan Region (mark bit scan)
Read Barrier                 Sweep Region (free list rebuild)
Forwarding                   Compact Region (relocate + forward)
Metadata Lookup              Metadata Rebuild
Epoch Management             Bulk Memory Copy / Fill
Root Scanning                Region Validation
```

Accelerator NEVER handles write barriers, read barriers, or per-object forwarding on the hot path.

## 5. Command Types

| Command             | Engine          | Description                          |
|---------------------|-----------------|--------------------------------------|
| SCAN_REGION         | ScanEngine      | Scan region bitmap for live objects  |
| SWEEP_REGION        | SweepEngine     | Reclaim dead objects, rebuild free   |
| COMPACT_REGION      | CompactEngine   | Relocate live objects, update fwd    |
| REBUILD_METADATA    | MetadataRebuild | Rebuild region metadata structures   |
| PREFETCH_REGION     | MemoryAccess    | Prefetch region into cache/HBM       |
| FLUSH_REGION        | MemoryAccess    | Flush dirty region data              |
| QUERY_REGION        | RegionScheduler | Query region state                   |
| ABORT_EPOCH         | (all)           | Abort all commands for an epoch      |
| SYNC_EPOCH          | (all)           | Synchronize to epoch boundary        |

## 6. Architecture Diagram (Text)

```
┌──────────────────────────────────────────────────────────┐
│                    System Interconnect                    │
└──┬─────────────────────────────────────────────────┬─────┘
   │                                                 │
   ▼                                                 ▼
┌──────────────┐                          ┌────────────────────┐
│  JasperGC    │                          │  Accelerator    │
│  Core     │                          │                    │
│              │──── command ────────────>│  ┌──────────────┐  │
│  (hot path)  │                          │  │ CommandQueue │  │
│              │<─── completion ──────────│  └──────┬───────┘  │
│              │                          │         ▼          │
│              │                          │  ┌──────────────┐  │
│              │                          │  │ Scheduler    │  │
│              │                          │  └──┬───┬───┬───┘  │
│              │                          │     ▼   ▼   ▼      │
│              │                          │  ┌───┐ ┌───┐ ┌───┐ │
│              │                          │  │ S │ │ Sw│ │ C │ │
│              │                          │  │ c │ │ e │ │ o │ │
│              │                          │  │ a │ │ e │ │ m │ │
│              │                          │  │ n │ │ p │ │ p │ │
│              │                          │  └───┘ └───┘ └───┘ │
│              │                          │     │    │    │     │
│              │                          │     ▼    ▼    ▼     │
│              │                          │  ┌──────────────┐  │
│              │                          │  │ MemoryAccess │  │
│              │                          │  └──────┬───────┘  │
│              │                          │         ▼          │
│              │                          │  ┌──────────────┐  │
│              │                          │  │ CompleteQueue│  │
│              │                          │  └──────────────┘  │
└──────────────┘                          └────────────────────┘
```

## 7. Profile Summary

| Profile       | Tasks                    | Queue | Coherency      | Adapter    | Status         |
|---------------|--------------------------|-------|----------------|------------|----------------|
| accel_lite    | scan, sweep              | 4     | IO-coherent    | PCIe (fut) | ARCHITECTURE   |
| accel_standard| scan, sweep, rebuild     | 8     | IO-coherent    | chiplet    | ARCHITECTURE   |
| accel_server  | full cold path           | 16    | Fully coherent | chiplet    | MAINLINE_STUDY |
| accel_extreme | multi-region, HBM-aware  | 32    | Fully coherent | chiplet    | RESEARCH/HOLD  |

## 8. Status: ARCHITECTURE

The JasperGC Accelerator is currently in the **ARCHITECTURE** phase. No RTL implementation exists. The design is being refined through profile studies (accel_standard, accel_server) and adapter boundary analysis. RTL development is planned to begin with accel_lite and accel_standard profiles.
