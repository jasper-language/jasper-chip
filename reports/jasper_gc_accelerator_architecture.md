# JasperGC Accelerator — Architecture Report

> **UPDATE: Architecture refocused to chiplet accelerator.**  
> See `jasper_gc_chiplet_accelerator_architecture.md` for current mainline.  
> CXL/DPU/PCIe adapters are future boundary only.

## 1. Motivation

The JasperGC Core handles the allocation hot path: write-barrier (WB), read-barrier (RB), forwarding, and metadata lookup. These operations are latency-critical and execute on every pointer-store or heap-load. As heap sizes grow and mutator threads scale, Core footprint and timing closure become challenging.

Cold-path operations — scan, sweep, compaction, and metadata rebuild — do not sit on the mutator fast path. They are throughput-sensitive rather than latency-sensitive, and they operate on coarse region granularity. Dedicated accelerator hardware can:

- Offload cold-path processing from Core, freeing Core issue slots and cache pressure.
- Run cold-path operations in parallel with mutator execution.
- Scale independently of Core tile count.
- Enable configurations (Server, Extreme) that require high-throughput concurrent GC cycles.

## 2. Project Boundary — Core vs Accelerator

```
┌─────────────────────────────────────────────────┐
│                  JasperGC System                 │
├─────────────────────┬───────────────────────────┤
│    Core          │    Accelerator          │
│  (Hot Path)         │  (Cold Path — Coprocessor) │
│                     │                            │
│  • Write Barrier    │  • Scan Engine             │
│  • Read Barrier     │  • Sweep Engine            │
│  • Forwarding       │  • Compact Engine          │
│  • Metadata Lookup  │  • Metadata Rebuild        │
│  • Epoch Tracking   │  • Region Scheduling       │
│  • Root Scanning    │  • Bulk DMA                │
│                     │                            │
│  Latency-critical   │  Throughput-critical       │
│  Per-mutator-op     │  Per-region                │
└─────────────────────┴───────────────────────────┘
```

**The Accelerator does NOT participate in the hot path.** It is an external coprocessing layer that communicates via command/completion queues. The Core retains sole ownership of the hot path and metadata authority; the Accelerator is a trusted but subordinate engine.

## 3. Mainline and Adapter Boundaries

The primary (MAINLINE) integration is via a **CPU-package / chiplet** interface:

| Adapter           | Status                     | Notes                              |
|-------------------|----------------------------|------------------------------------|
| CPU-package/chiplet | MAINLINE                 | Low-latency, coherent, warm+cold   |
| CXL.mem           | FUTURE_EXPERIMENT          | Coherent, server memory pool       |
| DPU/SmartNIC      | FUTURE_GATEWAY_EXPERIMENT  | Gateway offload                    |
| PCIe DMA          | FUTURE_BACKGROUND_BATCH    | Background batch                   |

All non-chiplet adapters are future boundaries only. The chiplet adapter is the sole mainline target.

## 4. Command / Completion Protocol (Overview)

Commands are enqueued by the Core (or driver) into a **Command Queue**. The Accelerator processes commands in order per-region, and writes completions into a **Completion Queue**. Each command carries a `correlation_id` that is mirrored in the completion, enabling out-of-order completion matching.

```
Core                     Accelerator
   │                             │
   │── command ─────────────────>│
   │   (correlation_id, epoch,   │
   │    region, command_type,     │
   │    parameters)               │
   │                             │── execute
   │                             │
   │<──── completion ────────────│
   │   (correlation_id, status,  │
   │    epoch, metadata_delta)    │
```

## 5. Accelerator Profiles

| Profile          | Tasks                          | Queue Depth | DMA Width | Coherency | Adapter Priority  | Status          |
|------------------|--------------------------------|-------------|-----------|-----------|-------------------|-----------------|
| accel_lite       | scan, sweep                    | 4           | 64 B     | IO-coherent | PCIe (future)    | ARCHITECTURE    |
| accel_standard   | scan, sweep, rebuild           | 8           | 128 B    | IO-coherent | chiplet           | ARCHITECTURE    |
| accel_server     | scan, sweep, compact, rebuild  | 16          | 256 B    | Fully coherent | chiplet          | MAINLINE_STUDY  |
| accel_extreme    | multi-region, HBM-aware        | 32          | 512 B    | Fully coherent | chiplet          | RESEARCH/HOLD   |

## 6. Module Architecture

```
┌───────────────────────────────────────────────────────┐
│                 Accelerator                         │
│                                                       │
│  ┌─────────────┐  ┌────────────────────────────────┐  │
│  │ CommandQueue │  │      RegionScheduler           │  │
│  │ (input FIFO) │──│ (region ownership, ordering)   │  │
│  └─────────────┘  └──────────┬─────────────────────┘  │
│                              │                         │
│         ┌────────────────────┼────────────────────┐    │
│         ▼                    ▼                    ▼    │
│  ┌───────────┐  ┌────────────┐  ┌───────────────┐     │
│  │ScanEngine │  │SweepEngine │  │CompactEngine  │     │
│  │(live bit) │  │(free list) │  │(relocate)     │     │
│  └─────┬─────┘  └──────┬─────┘  └───────┬───────┘     │
│        │               │                │             │
│        └───────┬───────┴────────────────┘             │
│                ▼                                      │
│  ┌──────────────────────────┐                         │
│  │  MetadataRebuildEngine   │                         │
│  │  (region metadata fixup) │                         │
│  └───────────┬──────────────┘                         │
│              │                                        │
│              ▼                                        │
│  ┌────────────────┐  ┌────────────────┐              │
│  │  MemoryAccess  │  │ CompletionQueue│               │
│  │  (DMA / RMW)   │  │ (output FIFO)  │              │
│  └────────────────┘  └────────────────┘              │
└───────────────────────────────────────────────────────┘
```

| Module              | Function                                               |
|---------------------|--------------------------------------------------------|
| CommandQueue        | Accepts commands from Core / driver; FIFO ordering   |
| RegionScheduler     | Assigns commands to engines; enforces region ownership  |
| ScanEngine          | Scans region for live objects (mark bit traversal)      |
| SweepEngine         | Reclaims dead objects; rebuilds free-list               |
| CompactEngine       | Relocates live objects; updates forwarding pointers     |
| MetadataRebuildEngine | Rebuilds region metadata after sweep/compact          |
| MemoryAccess        | Handles all memory transactions (DMA, atomic RMW)       |
| CompletionQueue     | Writes completion records back to Core / driver      |

## 7. Core Collaboration Model

- **Asynchronous, non-blocking**: Core posts a command and continues hot-path execution. The accelerator processes the command and posts a completion.
- **Correlation ID matching**: Each command carries a unique `correlation_id` (per-accelerator-instance, per-region). Completions echo this ID.
- **Epoch validation**: Commands include an epoch tag. Accelerator validates it matches current GC epoch before processing. Mismatch causes ABORTED completion.
- **Metadata ownership**: Core retains authoritative metadata. Accelerator caches metadata for the region it is processing and writes back deltas on completion.

## 8. Correctness Rules

### 8.1 Epoch
- Every command includes a monotonically-increasing epoch number.
- Accelerator MUST reject commands whose epoch does not match the current GC cycle.
- Accelerator MUST tag all memory transactions with the command's epoch.

### 8.2 Region Ownership
- A region may be owned by at most one command at a time.
- RegionScheduler enforces mutual exclusion per region.
- Core guarantees no command is issued for a region already in-flight.

### 8.3 Ordering
- Commands for the same region are processed in FIFO order.
- Commands for different regions may be processed in parallel.
- Completion ordering: same-region completions are in-order; cross-region completions may be out-of-order.

### 8.4 Error Handling
| Error               | Completion Status | Recovery                                        |
|---------------------|-------------------|-------------------------------------------------|
| Epoch mismatch      | ABORTED           | Core retries with correct epoch              |
| Region locked       | BUSY              | Core backs off and retries                   |
| Memory access fault | ERROR             | Core marks region, triggers health check     |
| Unsupported command | UNSUPPORTED       | Core falls back to software path             |
| Transient stall     | RETRY             | Core retries (bounded count)                 |

### 8.5 Coherency
- **accel_lite / accel_standard**: IO-coherent DMA. Core publishes region metadata before posting commands.
- **accel_server / accel_extreme**: Fully coherent (chiplet cache-coherent fabric). Accelerator sees Core updates without explicit flushes.

## 9. Adapter Comparison

| Feature                | Chiplet (MAINLINE) | CXL.mem           | DPU/SmartNIC       | PCIe DMA           |
|------------------------|--------------------|--------------------|--------------------|--------------------|
| Status                 | MAINLINE           | FUTURE_EXPERIMENT  | FUTURE_GATEWAY     | FUTURE_BACKGROUND  |
| Latency                | ~50-100 ns         | ~200-400 ns        | ~1-5 µs            | ~1-10 µs           |
| Bandwidth              | 256-512 B/cycle    | 32-64 GT/s         | 100-200 Gbps       | 32-64 GT/s         |
| Coherency              | Full (chiplet)     | CXL.cache          | None (SW managed)  | None (SW managed)  |
| Suitable tasks         | all cold-path      | scan, sweep        | scan (gateway)     | sweep, compact     |
| Unsuitable tasks       | —                  | compact (latency)  | compact, rebuild   | scan (latency)     |
| Protocol complexity    | Low (internal)     | Medium (CXL)       | High (network)     | Medium (PCIe)      |

## 10. Conclusions

1. The Accelerator cleanly separates cold-path throughput from hot-path latency, enabling independent scaling.
2. The chiplet adapter is the MAINLINE boundary; CXL, DPU, and PCIe are future options.
3. Four accelerator profiles span from lite (scan+sweep) to extreme (multi-region HBM-aware).
4. The command/completion protocol with correlation_id and epoch validation provides a robust async collaboration model.
5. Correctness rules (epoch, region ownership, ordering, error handling, coherency) guarantee safety across all profiles.
6. The architecture is at ARCHITECTURE phase; profiles accel_standard and accel_lite are ready for RTL planning.
