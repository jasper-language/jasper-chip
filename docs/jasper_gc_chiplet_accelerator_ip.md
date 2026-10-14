# Jasper-GC Chiplet Accelerator

> Date: 2026-06-07  
> Status: ARCHITECTURE  

---

## 1. What is Jasper-GC Chiplet Accelerator?

A **cold-path / background GC accelerator** designed for CPU-package or  
chiplet integration with JasperGC Core.

- Processes SCAN, SWEEP, COMPACT, REBUILD, and RELOCATE operations
- Operates asynchronously — never stalls hot path
- Shares unified command/completion protocol with future adapters
- Requires coherent access to heap + metadata regions

## 2. Core vs Accelerator

| Dimension | JasperGC Core | JasperGC Chiplet Accelerator |
|-----------|------------------|--------------------------------|
| Path | Hot | Cold / background |
| Operations | WB, RB, forward, allocate | Scan, sweep, compact, rebuild |
| Latency | Critical (sub-10ns) | Tolerant (μs-ms) |
| Throughput | 1.0 evt/cyc per lane | Region throughput (MB/s) |
| Coherency | Internal | Chiplet-coherent |
| Core → Accelerator | Hot path does NOT depend on accelerator | Submits commands async |
| Accelerator → Core | Depends on Core/driver for command submission | Never blocks Core hot path |
| Collaboration | Async non-blocking via command/completion protocol | correlation_id + epoch matching |

## 3. When is Accelerator Needed?

| Profile | Accelerator | Rationale |
|---------|-------------|-----------|
| MCU / Lite | **NO** | Low GC pressure; area/power priority |
| Standard | Optional | Small heap; scan/sweep are fast enough |
| Standard+ | **chiplet_accel_standard** | Metadata rebuild benefits |
| Gateway | **chiplet_accel_standard** | Region scan under gateway workload |
| Server Base | **chiplet_accel_server** | Compaction + remembered set cleanup |
| Server | **chiplet_accel_server** | Full cold path offload |
| Extreme | **chiplet_accel_extreme** | Multi-region + large object (HOLD) |

## 4. Command Types

| Type | Code | Description |
|------|------|-------------|
| SCAN_REGION | 0 | Scan heap region for live objects |
| SWEEP_REGION | 1 | Collect dead objects, free memory |
| COMPACT_REGION | 2 | Relocate live objects for defragmentation |
| REBUILD_METADATA | 3 | Rebuild metadata cache / forwarding table |
| CLEAN_REMEMBERED_SET | 4 | Clean remembered set entries |
| PREFETCH_METADATA | 5 | Prefetch metadata into cache |
| RELOCATE_COLD_OBJECTS | 6 | Move cold objects to slower tier |
| LARGE_OBJECT_MOVE | 7 | Move large objects (multi-region) |
| BACKGROUND_GC_PHASE | 8 | Multi-phase GC cycle coordination |

## 5. Architecture Diagram (Text)

```
┌─────────────────────────────────────────────────────────────┐
│                  JasperGC Core                           │
│  ┌────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐ │
│  │ Event  │→ │Forwarding│→ │Metadata │→ │ Backend      │ │
│  │ Pipe   │  │ Table    │  │ Cache   │  │ Merge        │ │
│  └────────┘  └──────────┘  └──────────┘  └──────────────┘ │
│       │                                                    │
│       │ cmd_valid (async, non-blocking)                    │
│       ▼                                                    │
│  ┌────────────────────────────────────────────────────┐    │
│  │  JasperGC Chiplet Accelerator                   │    │
│  │  ┌──────────┐ ┌────────────────┐ ┌──────────────┐ │    │
│  │  │ Command  │→│ Region         │→│ Scan         │ │    │
│  │  │ Queue    │ │ Scheduler      │ │ Engine       │ │    │
│  │  └──────────┘ └────────────────┘ └──────────────┘ │    │
│  │                   │                                 │    │
│  │                   ├→ SweepEngine                    │    │
│  │                   ├→ CompactEngine (server+)        │    │
│  │                   ├→ MetadataRebuildEngine          │    │
│  │                   └→ CompletionQueue                │    │
│  │  ┌──────────┐                                       │    │
│  │  │ Memory   │←→ Coherent chiplet access             │    │
│  │  │ Access   │                                       │    │
│  │  └──────────┘                                       │    │
│  └────────────────────────────────────────────────────┘    │
│       ▲                                                    │
│       │ comp_valid (correlation_id)                        │
└─────────────────────────────────────────────────────────────┘
```

## 6. Profile Summary

| Profile | Tasks | Queue Depth | Regions | Status |
|---------|-------|-------------|---------|--------|
| chiplet_accel_standard | scan, sweep, rebuild | 8 | 2 | **ARCHITECTURE** |
| chiplet_accel_server | +compact, relocate, clean | 16 | 4 | **MAINLINE_STUDY** |
| chiplet_accel_extreme | +large object, multi-region | 32 | 8+ | **HOLD** |

## 7. Status

| Layer | Status |
|-------|--------|
| Architecture | ✅ **ARCHITECTURE** |
| Config system | ✅ **RTL_PASS** |
| Interface skeleton | ✅ **RTL_PASS** |
| Command/completion protocol | ✅ **DEFINED** |
| Scan/Sweep/Compact engines | ❌ **NOT IMPLEMENTED** (RTL_PLANNING) |
| Chiplet transport | ❌ **NOT IMPLEMENTED** (future) |
| CXL/DPU/PCIe adapters | ❌ **FUTURE_BOUNDARY** |
