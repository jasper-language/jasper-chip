# Accelerator Performance Counters + Observability v0.1

> Date: 2026-06-07
> Status: PASS — 9/9 tests

## What was done

- Created `rtl/jasper_gc_accelerator_perf_counters.py`: independent module with 32-bit saturating counters and max-stall trackers
- All counters are wired to real handshake signals in `JasperGCAcceleratorIP`
- Exposed arbiter debug signals (`dbg_outstanding`, `dbg_out_engine`, `dbg_any_engine_req_valid`)
- Exposed scheduler reject signals (`_reject_stale`, `_reject_unsupp`, `_reject_busy`)

## Counter coverage

| Group | Counters | Wired | Notes |
|-------|----------|-------|-------|
| Command path | cmd_accepted, cmd_backpressure, cmd_stall_max, cmd_rejected | ✅ | Real handshake |
| Completion path | comp_accepted, comp_backpressure, comp_stall_max, comp_route_mismatch | ✅ | route_mismatch not wired (always 0) |
| Memory path | mem_req_accepted, mem_rsp_accepted, mem_req_backpressure, mem_rsp_backpressure, mem_stall_max, outstanding_block | ✅ | Real handshake |
| Per-engine cmd | scan/sweep/rebuild/compact_cmd_accepted | ✅ | Via `_to_` scheduler signals |
| Per-engine mem_req | scan/sweep/rebuild/compact_mem_req_accepted | ✅ | Via arbiter req_valid & req_ready |
| Per-engine comp | scan/sweep/rebuild/compact_comp_accepted | ✅ | Via engine out_valid & out_ready |
| Per-engine busy | scan/sweep/rebuild/compact_busy | ✅ | Via engine.busy |
| Per-engine mem_stall | scan/sweep/rebuild/compact_mem_stall | ✅ | busy & req_valid & !req_ready |
| Reject type | stale_epoch_reject, unsupported_reject, region_busy_reject | ✅ | Via scheduler reject signals |

## Test results (9 new tests, all PASS)

| Test | Status |
|------|--------|
| Single SCAN counters | ✅ PASS |
| Four engine per-engine counters | ✅ PASS |
| mem_req_accepted == mem_rsp_accepted | ✅ PASS |
| cmd_accepted normal operation | ✅ PASS |
| comp_accepted normal operation | ✅ PASS |
| outstanding_block wired | ✅ PASS |
| stale_epoch_reject increments (mem_req=0) | ✅ PASS |
| unsupported_reject increments (mem_req=0) | ✅ PASS |
| enable_memory=False → mem counters = 0 | ✅ PASS |

## Limitations (explicitly documented)

- **Counters are observability only** — no register map, no APB/AXI-Lite access;
- **comp_route_mismatch not wired** — cannot distinguish completion source at this level;
- **outstanding_block** requires continuous cmd_valid scenario to fire (scheduler serializes in pulse-mode); wired but may read 0 in normal tests;
- **MemoryAccess remains latency/backpressure model** — counters reflect model, not real DRAM/HBM;
- **Compact remains READ_ONLY_MODEL** — relocation counters not meaningful;
- **Not CoherentAccess, not chiplet PHY, not multi-outstanding** — all FUTURE;
- **Counters are 32-bit saturating** — stop at 0xFFFFFFFF, do not wrap;
- **Not a performance signoff** — counters identify bottlenecks, not PPA/Fmax conclusions.
