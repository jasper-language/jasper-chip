# Jasper-GC External Accelerator Interface

> **STATUS: PLACEHOLDER / RESERVED — NOT IMPLEMENTED**
>
> This document describes a future interface for offloading GC scan/sweep/compaction
> operations to a CXL-attached accelerator or DPU. The interface is **reserved** in the
> current RTL — no logic exists to drive or consume these signals.

---

## Motivation

In future high-core-count or CXL-memory configurations, it may be advantageous to offload
GC scan, sweep, and compaction phases to a dedicated accelerator. This allows:
- GC work to proceed in parallel with mutator execution on the main core
- Dedicated hardware optimized for heap traversal and relocation
- Reduced cache pollution on the primary memory path

## Scope

The external accelerator interface handles **cold path** GC operations:
- Root scanning (parallel)
- Heap walking / object tracing
- Card table scanning and dirty-bit clearing
- Compaction evacuation

**Hot path** operations remain on-chip:
- Object marking (through forwarding table)
- Reference forwarding
- Evacuation write frontier update

## Signal Specification

All signals are synchronous to `gc_clk`. The interface uses a valid/ready handshake
for all command and completion transfers.

### Command Interface

| Signal | Width | Direction | Description |
|--------|-------|-----------|-------------|
| `gc_ext_cmd_valid` | 1 | Input | Command valid |
| `gc_ext_cmd_ready` | 1 | Output | Accelerator ready |
| `gc_ext_cmd_type` | 3 | Input | 0=root_scan, 1=heap_walk, 2=sweep_scan, 3=evacuate, 4=compact, 5–7=reserved |
| `gc_ext_region_base` | 64 | Input | Base address of region to process |
| `gc_ext_region_size` | 32 | Input | Size of region in bytes |
| `gc_ext_epoch` | 8 | Input | Current GC epoch (for ordering) |
| `gc_ext_merge_domain` | 4 | Input | Merge domain ID for result ordering |

### Completion Interface

| Signal | Width | Direction | Description |
|--------|-------|-----------|-------------|
| `gc_ext_completion_valid` | 1 | Output | Completion valid |
| `gc_ext_completion_ready` | 1 | Input | Core ready for completion |
| `gc_ext_completion_status` | 2 | Output | 0=ok, 1=aborted, 2=error, 3=retry |
| `gc_ext_completion_tag` | 8 | Output | Echo of command tag for correlation |
| `gc_ext_completion_count` | 32 | Output | Number of objects processed |

### Memory Interface

The accelerator is expected to access the heap through its own AXI4 or CXL.mem port.
The specific bus protocol is platform-dependent and not fixed at this level.

## Integration

```
┌────────────────────────────┐
│   Core / SoC               │
│  ┌──────────────────┐      │
│  │ Jasper-GC     │      │
│  │  (hot path)      │      │
│  └──────┬───────────┘      │
│         │ gc_ext_*         │
│         ▼                  │
│  ┌──────────────────┐      │
│  │ External         │      │
│  │ Accelerator IF   │      │
│  │ (placeholder)    │      │
│  └──────────────────┘      │
│         │                  │
│         ▼                  │
│  ┌──────────────────┐      │
│  │ CXL / PCIe EP    │      │
│  └──────────────────┘      │
└────────────────────────────┘
           │
           ▼
   CXL-attached GC Accelerator / DPU
```

## Implementation Plan

| Phase | Scope | When |
|-------|-------|------|
| **Phase 0** | Document interface (this file) | Current |
| **Phase 1** | RTL placeholder module with tie-offs | Future |
| **Phase 2** | Basic offload of root scan | Future |
| **Phase 3** | Full sweep/evacuation offload | Future |

Phase 0 is complete. No RTL implementation is scheduled.
