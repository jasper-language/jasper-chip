# CoherentAccessAdapter v0.1 — Adapter Shim Report

> Date: 2026-06-08
> Status: CLOSED — all adapter tests PASS
>
> **This is an adapter shim (interface bridge), not a coherence protocol.**

## Scope

`CoherentAccessAdapter` bridges the `MemoryRequestArbiter`-compatible
interface (16-bit tag, minimal response) to `CoherentAccess`. It is a
combinational signal mapping wrapper with zero additional pipeline stages.

It does **not** replace `MemoryAccess` in the current top-level active path.
It does **not** wire CoherentAccess into `JasperGCAcceleratorIP`.
It does **not** replace any hardware engine.

## Architecture Position

```
Arbiter mem_* interface (mem_req_valid/ready, mem_req_tag[15:0], ...)
    ↕ (combinational)
CoherentAccessAdapter
    ↕ (combinational)
CoherentAccess (tag_width=16, internal)
```

- Adapter is purely combinational: no state, no FIFO, no pipeline.
- `mem_req_*` signals map directly to `ca.req_*`.
- `ca.rsp_*` signals map directly to `mem_rsp_*` + debug outputs.
- CoherentAccess extra fields (epoch, size, region_id, flags) not driven by
  arbiter are tied to 0.

## Interface

### MemoryRequestArbiter-compatible

| Signal | Direction | Width | Maps to |
|--------|-----------|-------|---------|
| `mem_req_valid` | Input | 1 | `ca.req_valid` |
| `mem_req_ready` | Output | 1 | `ca.req_ready` |
| `mem_req_is_write` | Input | 1 | `ca.req_is_write` |
| `mem_req_addr` | Input | 32 | `ca.req_addr` |
| `mem_req_tag` | Input | 16 | `ca.req_tag` |
| `mem_rsp_valid` | Output | 1 | `ca.rsp_valid` |
| `mem_rsp_ready` | Input | 1 | `ca.rsp_ready` |
| `mem_rsp_tag` | Output | 16 | `ca.rsp_tag` |

### Debug signals (CoherentAccess extra response metadata)

| Signal | Direction | Width | Source |
|--------|-----------|-------|--------|
| `dbg_rsp_error` | Output | 1 | `ca.rsp_error` |
| `dbg_rsp_status` | Output | 3 | `ca.rsp_status` |
| `dbg_rsp_hit` | Output | 1 | `ca.rsp_hit` |
| `dbg_rsp_epoch` | Output | 8 | `ca.rsp_epoch` |

## RTL Changes to CoherentAccess

- `tag_width` default changed from 8 to 16.
- Backward compatible: explicit `tag_width=8` still works.
- No other RTL changes.

## Test Results

| Test | Description |
|------|-------------|
| `test_elab` | Module elaborates |
| `test_read_hit` | Read hit preserves 16-bit tag, dbg_hit=1, dbg_status=0 |
| `test_read_miss` | Read miss preserves 16-bit tag, dbg_hit=0 |
| `test_write` | Write returns OK (dbg_status=0) |
| `test_write_disabled_unsupported` | Disabled write returns UNSUPPORTED (dbg_status=5) |
| `test_tag_16bit_preserved` | 16-bit tag (0xFEED) preserved end-to-end |
| `test_response_backpressure_hold` | rsp_valid holds when rsp_ready=0 |
| `test_request_backpressure` | Queue full → req_ready=0 |
| `test_response_backpressure_hold_data_stable` | Response data/tag/status stable under hold |
| `test_no_loss` | Accepted tag set == response tag set |
| `test_no_missing_response` | No accepted tag missing |
| `test_no_duplicate_response` | No duplicate tags |
| `test_fault_status_on_dbg` | FAULT (4) visible on dbg_rsp_status |
| `test_dbg_rsp_error_follows_status` | dbg_rsp_error=1 for FAULT, 0 for OK |
| `test_dbg_rsp_hit_reports` | dbg_rsp_hit=1 for hit, 0 for miss |
| `test_dbg_rsp_epoch_passthrough` | dbg_rsp_epoch passthrough (driven 0 by adapter) |
| `test_mixed_read_write_sequence` | Interleaved R/W all produce correct responses |

17 tests total.

## Key Status

| Item | Status |
|------|--------|
| CoherentAccess raw 19 tests | ✅ still PASS |
| CoherentAccessAdapter new tests | ✅ all PASS |
| Top-level integration | ❌ Not done — adapter is standalone |
| Active path uses MemoryAccess | ✅ Still true |
| Hardware engines unchanged | ✅ Unchanged |
| Cmdq/scheduler/compq unchanged | ✅ Unchanged |
| CPUlet firmware architecture | ❌ Not introduced |
| Real coherence protocol | ❌ Not implemented |
| Adapter is bridge only | ✅ Combinational signal mapping |
