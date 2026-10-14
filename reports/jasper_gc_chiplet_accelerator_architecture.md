# Jasper-GC Chiplet Accelerator Architecture

> Date: 2026-06-07  
> Status: ARCHITECTURE  
> Mainline: CPU-package / chiplet GC accelerator  

---

## 0. Executive Summary

Jasper-GC Accelerator is refocused to **chiplet GC accelerator** only.  
CXL / DPU / PCIe adapters are downgraded to future adapter boundaries.

| Layer | Accel | Path | Status |
|-------|----|------|--------|
| Hot path | JasperGC Core | WB/RB/forwarding/metadata | ✅ **PASS** (packaging GO) |
| Cold path | JasperGC Chiplet Accelerator | scan/sweep/compact/rebuild | 🔷 **ARCHITECTURE** |
| Future | CXL/DPU/PCIe adapters | memory pool / gateway / batch | ⏳ **FUTURE_BOUNDARY** |

---

## 1. Motivation

JasperGC Core handles **hot path** GC operations:
- WB barrier events (sub-10ns)
- RB/forwarding lookup (low-latency)
- Metadata cache (pipelined)
- Event ordering / epoch / flush
- 1.0 evt/cyc per lane, 2.0 per 2L tile

These do NOT need an accelerator.

**Cold path** operations (scan, sweep, compact, rebuild) are:
- Throughput-oriented (not latency-critical)
- Memory bandwidth-bound
- Beneficial from dedicated hardware
- Good fit for chiplet co-processor

A CPU-package / chiplet accelerator provides:
- Low latency (package-scale, not rack-scale)
- High bandwidth (coherent or near-coherent)
- No PCIe/CXL protocol overhead
- Natural coherency with Core metadata

---

## 2. Project Boundary

### JasperGC Core (unchanged)

| Component | Accelerator involvement |
|-----------|------------------------|
| WB barrier | **NONE** — hot path |
| RB forward | **NONE** — hot path |
| Metadata lookup | **NONE** — hot path |
| Backend merge | **NONE** — hot path |
| Event pipeline | **NONE** — hot path |
| Epoch/flush | Only **epoch validation** for accelerator completion |

### JasperGC Chiplet Accelerator (new)

| Component | Core involvement |
|-----------|---------------------|
| Region scan | Receives SCAN command, returns completion |
| Region sweep | Receives SWEEP command, returns completion |
| Compaction | Receives COMPACT command, returns completion |
| Metadata rebuild | Receives REBUILD command, returns completion |
| Remembered set | Receives CLEAN command, returns completion |
| Cold relocation | Receives RELOCATE command, returns completion |

**Accelerator never intercepts hot path.**  
All accelerator operations are **async non-blocking** from Core perspective.

---

## 3. Chiplet Accelerator Profiles

| Profile | Tasks | Queue Depth | Region Count | Coherency | Adapter | Status |
|---------|-------|-------------|--------------|-----------|---------|--------|
| **chiplet_accel_standard** | scan, sweep, rebuild | 8 | 2 | Coherent | Chiplet | **ARCHITECTURE** |
| **chiplet_accel_server** | scan, sweep, compact, rebuild, relocate, remember | 16 | 4 | Coherent | Chiplet | **MAINLINE_STUDY** |
| **chiplet_accel_extreme** | multi-region all + large object | 32 | 8+ | Coherent | Chiplet | **HOLD / RESEARCH** |

### 3.1 chiplet_accel_standard

| Field | Value |
|-------|-------|
| Tasks | SCAN_REGION, SWEEP_REGION, REBUILD_METADATA |
| Command queue depth | 8 |
| Completion queue depth | 8 |
| Max outstanding commands | 4 |
| Region count | 2 |
| Coherency | Required (coherent access to heap + metadata) |
| Max region size | 256 MB |
| Suitable Core profiles | Standard+, Gateway, small Server |
| Status | **ARCHITECTURE / RTL_PLANNING** |

### 3.2 chiplet_accel_server

| Field | Value |
|-------|-------|
| Tasks | + COMPACT_REGION, CLEAN_REMEMBERED_SET, RELOCATE_COLD_OBJECTS |
| Command queue depth | 16 |
| Completion queue depth | 16 |
| Max outstanding commands | 8 |
| Region count | 4 |
| Coherency | Required |
| Status | **MAINLINE_STUDY** |

### 3.3 chiplet_accel_extreme

| Field | Value |
|-------|-------|
| Tasks | + LARGE_OBJECT_MOVE (multi-region) |
| Command queue depth | 32 |
| Completion queue depth | 32 |
| Max outstanding commands | 16 |
| Region count | 8+ |
| Coherency | Required (HBM-aware) |
| Status | **HOLD / RESEARCH** |

### 3.4 MCU / Lite

MCU and Lite profiles do **NOT** include chiplet accelerator.  
GC pressure is low; area/power is priority.

---

## 4. Unified Command / Completion Protocol

### 4.1 Command Fields

| Field | Width | Description |
|-------|-------|-------------|
| cmd_valid | 1 | Command valid |
| cmd_ready | 1 | Command ready (backpressure) |
| cmd_type | 4 | See command types below |
| cmd_flags | 8 | Type-specific flags |
| region_base | 32 | Region base address |
| region_size | 32 | Region size (bytes) |
| metadata_base | 32 | Metadata region base |
| forwarding_base | 32 | Forwarding table base |
| remembered_set_base | 32 | Remembered set base |
| object_table_base | 32 | Object table base |
| epoch | 8 | Epoch for validation |
| merge_domain | 4 | Merge domain for completion routing |
| priority | 2 | Command priority (0-3) |
| correlation_id | 16 | Unique command identifier |

### PREFETCH_METADATA Advisory

PREFETCH_METADATA is defined as a **background / advisory** command only.
It must NOT bypass Core metadata authority:
- Accelerator may prefetch metadata into its local cache for scan/sweep efficiency
- Core metadata cache remains the authoritative source for hot path lookups
- Accelerator must NOT update or invalidate Core metadata without explicit REBUILD_METADATA command
- Any prefetched metadata in accelerator is considered a hint, not authoritative

### 4.2 Command Types

| Type | Code | chiplet_accel_standard | chiplet_accel_server | chiplet_accel_extreme |
|------|------|----------------------|---------------------|----------------------|
| SCAN_REGION | 0 | ✅ | ✅ | ✅ |
| SWEEP_REGION | 1 | ✅ | ✅ | ✅ |
| COMPACT_REGION | 2 | — | ✅ | ✅ |
| REBUILD_METADATA | 3 | ✅ | ✅ | ✅ |
| CLEAN_REMEMBERED_SET | 4 | — | ✅ | ✅ |
| PREFETCH_METADATA | 5 | OPT | OPT | ✅ |
| RELOCATE_COLD_OBJECTS | 6 | — | ✅ | ✅ |
| LARGE_OBJECT_MOVE | 7 | — | — | ✅ |
| BACKGROUND_GC_PHASE | 8 | — | OPT | ✅ |

### 4.3 Completion Fields

| Field | Width | Description |
|-------|-------|-------------|
| comp_valid | 1 | Completion valid |
| comp_ready | 1 | Completion ready |
| comp_status | 3 | OK / RETRY / BUSY / ABORTED / ERROR / UNSUPPORTED |
| correlation_id | 16 | Matches command |
| epoch | 8 | Echo of command epoch |
| merge_domain | 4 | Echo of command merge_domain |
| bytes_scanned | 32 | Total bytes processed |
| objects_scanned | 32 | Objects examined |
| live_objects | 32 | Live objects found |
| dead_objects | 32 | Dead objects found |
| objects_moved | 32 | Objects relocated |
| bytes_moved | 32 | Bytes relocated |
| metadata_updates | 32 | Metadata entries updated |
| error_code | 8 | Extended error info |

---

## 5. Collaboration Model

```
JasperGC Core                    JasperGC Chiplet Accelerator
        │                                      │
        │  cmd_valid + SCAN_REGION             │
        │ ──────────────────────────────►      │
        │                                      │──► CommandQueue
        │                                      │──► RegionScheduler  
        │                                      │──► ScanEngine
        │                                      │──► SweepEngine
        │                                      │──► CompactEngine (server+)
        │                                      │──► CompletionQueue
        │                                      │
        │        comp_valid + OK               │
        │ ◄──────────────────────────────      │
```

- Core sends command → does NOT wait
- Core continues hot path processing
- Accelerator processes cold path asynchronously
- Accelerator returns completion with correlation_id
- Core matches correlation_id to pending command
- Core validates epoch before accepting completion
- Stale epoch completions are dropped / retried

**Hot path never stalls waiting for accelerator.**

### Dependency Model

```
Core hot path ──→ NO dependency on Accelerator (can run without accelerator)
Core/driver ──→ submits commands to Accelerator
Accelerator ──→ depends on Core/driver for command submission
Accelerator ──→ never blocks Core hot path
Collaboration ──→ async non-blocking command/completion protocol
```

Key rules:
1. Core hot path (WB/RB/forwarding/metadata) functions identically with or without accelerator
2. Accelerator receives commands from Core/driver, processes asynchronously
3. Accelerator returns completions; Core matches via correlation_id
4. Accelerator does NOT initiate any operation — always command-driven
5. If accelerator is absent, slow or unresponsive, Core hot path is unaffected

---

## 6. Adapter Boundary (Future Only)

| Adapter | Status | Detail |
|---------|--------|--------|
| **Chiplet** (CPU-package) | ✅ **MAINLINE** | This document |
| CXL.mem | ⏳ **FUTURE_SERVER_MEMORY_POOL_EXPERIMENT** | Adapter boundary only |
| DPU / SmartNIC | ⏳ **FUTURE_GATEWAY_EXPERIMENT** | Adapter boundary only |
| PCIe DMA | ⏳ **FUTURE_BACKGROUND_BATCH_EXPERIMENT** | Adapter boundary only |

CXL, DPU, and PCIe adapters share the same command/completion protocol  
but require transport-specific adapter logic. Not implemented in current scope.

---

## 7. Correctness Rules

### 7.1 Epoch

- Command carries epoch from Core
- Accelerator echoes epoch in completion
- Core validates: `completion.epoch >= current_epoch`? accept : drop/retry
- After `flush_epoch`, completions with `epoch < flush_epoch` are stale

### 7.2 Region Ownership

| Operation | Lock type |
|-----------|-----------|
| SCAN_REGION | Shared (multiple concurrent scans allowed) |
| SWEEP_REGION | Exclusive |
| COMPACT_REGION | Exclusive |
| REBUILD_METADATA | Exclusive |
| CLEAN_REMEMBERED_SET | Shared (with scan) |
| RELOCATE_COLD_OBJECTS | Exclusive |
| LARGE_OBJECT_MOVE | Exclusive |

### 7.3 Ordering

- Commands may execute out-of-order
- Completion correlation_id matches command
- Same-region exclusive operations are serialized by RegionScheduler
- Cross-region operations are independent

### 7.4 Error Handling

| Status | Meaning | Action |
|--------|---------|--------|
| OK | Success | Accept |
| RETRY | Transient failure | Re-submit |
| BUSY | Resource conflict | Backoff + retry |
| ABORTED | Epoch mismatch / flush | Discard |
| ERROR | Permanent failure | Log + report |
| UNSUPPORTED | Command not supported | Report capability |

---

## 8. Conclusions

| # | Question | Answer |
|---|----------|--------|
| 1 | Accelerator mainline? | ✅ **CPU-package / chiplet** |
| 2 | MCU/Lite need accelerator? | ❌ **NO** |
| 3 | Chiplet profiles defined? | ✅ **3 profiles** (standard/server/extreme) |
| 4 | Profile boundaries? | ✅ Tasks, queue depth, region count differ |
| 5 | Accelerator tasks? | Cold path: scan/sweep/compact/rebuild/relocate |
| 6 | Core tasks? | Hot path: WB/RB/forwarding/metadata (unchanged) |
| 7 | CXL/DPU/PCIe? | ⏳ **Future adapter boundary only** |
| 8 | Core packaging affected? | ❌ **NO** — Core packaging remains GO |
| 9 | RTL planning ready? | ✅ **RTL_PLANNING** for chiplet_accel_standard |

```
JasperGC Core:          ✅ PASS (packaging GO)
JasperGC Chiplet Accelerator: 🔷 ARCHITECTURE (RTL_PLANNING)
CXL / DPU / PCIe:          ⏳ FUTURE_BOUNDARY
```
