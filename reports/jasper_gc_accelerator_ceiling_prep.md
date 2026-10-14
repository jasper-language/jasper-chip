# Jasper-GC Accelerator Ceiling-Prep Report

> Date: 2026-06-07

## Current State

| Dimension | Current Value | Limitation | Needed For Ceiling |
|-----------|--------------|------------|-------------------|
| CommandQueue depth | 8 (configurable) | Pipeline depth | Adequate for 4 engines |
| CompletionQueue depth | 8 (configurable) | **Bottleneck** — 4 engines share single compq | Per-engine compq or larger depth |
| RegionScheduler region_count | 4 (hardcoded) | Sufficient for 4 engine types | Parameterization |
| ScanEngine instances | 1 | Single-threaded | Multi-instance for parallelism |
| SweepEngine instances | 1 | Single-threaded | Multi-instance |
| MetadataRebuildEngine instances | 1 | Single-threaded | Multi-instance |
| CompactEngine instances | 1 | Single-threaded | Multi-instance |
| Engine model fidelity | Counting/model only | No real heap access | MemoryAccess/CoherentAccess |
| Completion arbitration | Single-output (ce>mre>sweep>scan) | Serializes completions | Multi-output or wider pipeline |
| Command issue | Single-output (scheduler) | Serializes commands | Multi-issue |
| Memory access | None | No data-plane latency model | MemoryAccess abstraction |
| Chiplet link | Not modeled | No bandwidth/power model | Chiplet adapter |
| Coherent access | Not modeled | No cache coherence | CoherentAccess |
| Backpressure from memory | Not modeled | All engines instant completion | MemoryAccess latency model |
| Multi-engine scaling | Not implemented | 1 instance per engine type | Multiple engine instances |
| Throughput counters | Not implemented | No performance measurement | perf_event_count |

## Key Findings

1. **Control-plane ceiling reached.** The scheduler, command queue, completion queue, and arbitration logic are verified.
2. **Data-plane ceiling not measured.** Current engines are counting/model only — no real memory access.
3. **Single CompletionQueue is the bottleneck.** With 4 engines producing completions simultaneously, the shared queue limits throughput.
4. **All engines are single-instance.** True parallelism requires multi-instance engines.
5. **Counting engines provide no real throughput data.** Engine throughput numbers would be meaningless without MemoryAccess latency model.

## Next Phase Recommendations

1. **MemoryAccess abstraction** — model read/write latency for engine operations
2. **Per-engine CompletionQueue** — decouple engine completions from shared bottleneck
3. **Multi-instance engines** — allow multiple ScanEngine/SweepEngine instances
4. **Chiplet link model** — bandwidth/power model for chiplet transport
5. **Throughput counters** — perf_event_count for real measurement

## Current Accelerator Verdict

- Config + validation: RTL_PASS
- CommandQueue: RTL_PASS
- RegionScheduler: RTL_PASS
- CompletionQueue: RTL_PASS (depth bottleneck noted)
- ScanEngine: RTL_PASS (counting/model)
- SweepEngine: RTL_PASS (counting/model)
- MetadataRebuildEngine: RTL_PASS (counting/model)
- CompactEngine: RTL_PASS (counting/model)
- 4-engine arbitration: RTL_PASS
- Region ownership: RTL_PASS
- Support config-driven: RTL_PASS
- Burst throughput: Pipeline-Limited
- MemoryAccess/CoherentAccess: NEXT
- Chiplet PHY: FUTURE
- CXL/DPU/PCIe: FUTURE_BOUNDARY
