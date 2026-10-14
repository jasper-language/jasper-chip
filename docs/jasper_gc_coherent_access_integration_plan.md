# CoherentAccess Integration Plan

> Date: 2026-06-08  
> Status: **Adapter shim implemented (v0.1); top-level integration still FUTURE**  
> This document defines the future integration point for CoherentAccess as a
> lower-level memory access abstraction under the existing `JasperGCAcceleratorIP`.

## 1. Current Active Path

```
JasperGCAcceleratorIP
  → CommandQueue
  → RegionScheduler
  → ScanEngine / SweepEngine / MetadataRebuildEngine / CompactEngine
  → MemoryRequestArbiter (4-input, single-outstanding, 16-bit tags)
  → MemoryAccess (shift-register latency model, READ_ONLY)
  → CompletionQueue
```

All four engines use a uniform memory request interface:
- `mem_req_valid` / `mem_req_ready`
- `mem_req_is_write` / `mem_req_addr` (32) / `mem_req_tag` (16)
- `mem_rsp_valid` / `mem_rsp_ready` / `mem_rsp_tag` (16)

`MemoryAccess` provides:
- `req_tag`: 16-bit
- `rsp_tag`: 16-bit
- `rsp_read_data`: 32-bit
- `rsp_error`: 1-bit
- `busy`: 1-bit
- Fixed read latency (shift-register pipeline, same for all requests)
- Write requests accepted but ignored (READ_ONLY)

## 2. CoherentAccess Interface Summary

```
Req: req_valid / req_ready / req_is_write / req_addr (32)
     req_write_data (32) / req_tag (8) / req_epoch (8)
     req_size (4) / req_region_id (8) / req_flags (8)
Rsp: rsp_valid / rsp_ready / rsp_read_data (32)
     rsp_tag (8) / rsp_epoch (8) / rsp_status (3) / rsp_error (1) / rsp_hit (1)
```

Key differences from `MemoryAccess`:
| Aspect | MemoryAccess | CoherentAccess |
|--------|-------------|----------------|
| Tag width | 16-bit | 8-bit (configurable) |
| Epoch | none | 8-bit, preserved end-to-end |
| Status codes | `rsp_error` (1-bit) | `rsp_status` (3-bit, 6 defined codes) |
| Hit reporting | none | `rsp_hit` (1-bit) |
| Write path | ignored (READ_ONLY) | modeled (OK or UNSUPPORTED) |
| Latency model | shift-register, fixed per-request | state machine + counter, variable (hit/miss/store) |
| Backpressure | queue (FIFO) + pipe hold | queue (FIFO with bypass) + response hold |
| Extra request fields | `req_burst` (8) | `req_epoch` / `req_size` / `req_region_id` / `req_flags` |
| `busy` | yes | no |
| Additional config | `read_latency` / `write_latency` / `error_rate` | `line_size` / `hit_latency` / `miss_latency` / `store_latency` / `hit_mask` / `enable_write` / `enable_error_injection` |

## 3. Integration Point

CoherentAccess would sit in the same position as MemoryAccess:

```
Engine memory request
  → MemoryRequestArbiter
  → MemoryAccess / CoherentAccess (alternative downstream)
  → response
```

The arbiter's `mem_*` interface is the **integration boundary**. No change
to engines, no change to command/completion path, no change to scheduler.

## 4. Adapter / Shim Requirements

To wire CoherentAccess behind the existing arbiter, an adapter shim is needed:

### Arbiter → CoherentAccess (downstream)

| Arbiter signal | CoherentAccess signal | Mapping |
|---------------|----------------------|---------|
| `mem_req_valid` | `req_valid` | direct |
| `mem_req_ready` | `req_ready` | direct |
| `mem_req_is_write` | `req_is_write` | direct |
| `mem_req_addr[31:0]` | `req_addr[31:0]` | direct |
| `mem_req_tag[15:0]` | `req_tag[7:0]` | **truncate to 8 bits** (or widen CoherentAccess to 16) |
| — | `req_write_data` | connect to 0 (write data not used in v0.1 READ_ONLY path) |
| — | `req_epoch` | connect to 0 (epoch not tracked below arbiter in current path) |
| — | `req_size` | connect to 0 (reserved) |
| — | `req_region_id` | connect to 0 (reserved) |
| — | `req_flags` | connect to 0 (reserved) |

### CoherentAccess → Arbiter (upstream)

| CoherentAccess signal | Arbiter signal | Mapping |
|----------------------|----------------|---------|
| `rsp_valid` | `mem_rsp_valid` | direct |
| `rsp_ready` | `mem_rsp_ready` | direct |
| `rsp_tag[7:0]` | `mem_rsp_tag[15:0]` | **zero-extend** (or widen CoherentAccess) |
| `rsp_error` | (arbiter discards) | no mapping needed |
| `rsp_read_data`, `rsp_status`, `rsp_epoch`, `rsp_hit` | (arbiter discards) | no mapping needed |

### Adapter alternatives

**Option A: Truncate/zero-extend tag (minimal adapter)**
- Arbiter uses 16-bit tags; CoherentAccess uses 8-bit tags
- Adapter truncates `req_tag[15:8]` on ingress, zero-extends `rsp_tag[15:8]` on egress
- Constraint: engine tags must fit in 8 bits (current engines use small counter tags, this is fine)
- Pro: zero RTL change to arbiter or engines
- Con: tag width mismatch is fragile, unused upper bits are noise

**Option B: Widen CoherentAccess tag to 16 bits**
- Change `tag_width` default from 8 to 16 in `CoherentAccess.__init__`
- No adapter needed for tag field
- Pro: clean interface match with arbiter
- Con: changes CoherentAccess RTL (minor parameter change)

**Option C: Pass-through adapter (minimal surface area)**
- Create a thin `CoherentAccessAdapter` wrapper that exposes a 16-bit tag
  MemoryAccess-compatible port and shrinks to CoherentAccess internally
- Allows CoherentAccess to keep its default 8-bit tag internally
- Adapter is testable independently

**Recommended: Option B + C** — widen default tag to 16 bits for interface
compatibility AND provide an adapter for any future engine that uses narrower
tags.

✅ **v0.1 adapter shim implemented**: `CoherentAccess` `tag_width` default
changed from 8 to 16 (Option B). `CoherentAccessAdapter` created as thin
combinational wrapper with debug signal passthrough (Option C). See
`rtl/jasper_gc_coherent_access_adapter.py` and
`tests/test_jasper_gc_coherent_access_adapter.py`.

## 5. Interface Semantics Mapping

### Status / Error

Currently `MemoryAccess` exposes only `rsp_error` (1-bit, always 0 in v0.1).
`CoherentAccess` exposes `rsp_status` (3-bit) and `rsp_error` (derived from
`rsp_status >= 2`).

The arbiter does not propagate status/error — each engine reads `mem_rsp_tag`
only. The engines currently assert that responses arrive correctly but do
not check error status at the arbiter-memory boundary.

If CoherentAccess produces FAULT or UNSUPPORTED status, the adapter must
either:
- Map non-OK status to a reserved tag value (error sentinel)
- Assert an error signal that the arbiter or engine can observe
- Or introduce `rsp_status` passthrough through a widened arbiter interface

**Recommendation for initial integration**: propagate `rsp_error` through
arbiter (add `mem_rsp_error` signal to arbiter) and have engines check it.
Keep `rsp_status` passthrough as FUTURE.

### Backpressure

Both `MemoryAccess` and `CoherentAccess` use the same valid/ready handshake
semantics. Backpressure behavior (queue full → `req_ready=0`, response hold
when `rsp_ready=0`) is identical. No adaptation needed.

### No-loss guarantee

Both modules guarantee `accepted == response` tag set equality. The arbiter's
single-outstanding + `out_engine` routing ensures correct response routing
regardless of which memory model is downstream. No adaptation needed.

## 6. Impact on Existing Components

| Component | Impact | Notes |
|-----------|--------|-------|
| CommandQueue | **None** | Above integration point |
| RegionScheduler | **None** | Above integration point |
| ScanEngine / SweepEngine / MRE / CompactEngine | **Minimal** | Engine memory interface unchanged; may need to handle `rsp_error` |
| MemoryRequestArbiter | **Minimal** | May need `mem_rsp_error` passthrough if CoherentAccess reports FAULT |
| MemoryAccess | **None** | Remains active model; CoherentAccess is alternative |
| CompletionQueue | **None** | Below integration point |
| Performance counters | **None** | Counters sample arbiter debug signals, not memory model |
| Profiles / Config | **None** | `memory_model` selection is FUTURE |

## 7. Write Path

Current `MemoryAccess` is READ_ONLY — write requests are accepted but ignored.
CoherentAccess supports write with either OK or UNSUPPORTED status.

In the current v0.1 active path, no engine issues write requests to memory:
- Scan: read-only
- Sweep: read-only (dead object accounting, no writeback)
- MetadataRebuild: read-only
- Compact: READ_ONLY_MODEL (no relocation, no writeback)

When write path is needed (future compact relocation), the engine must issue
write requests. CoherentAccess's write support provides a testable path:

```
Engine (write req) → Arbiter → CoherentAccess → write complete (status=OK)
```

For now, write path remains model-level only. No real memory update occurs.

## 8. Why Not Integrate in v0.1

1. **No functional requirement**: all four engines operate correctly with
   `MemoryAccess`. CoherentAccess offers hit/miss modeling that no engine
   currently uses.

2. **No write path requirement**: compact is READ_ONLY_MODEL. No engine
   issues write requests. CoherentAccess write support is unused.

3. **Arbiter interface stability**: the arbiter uses 16-bit tags and minimal
   response signals. Introducing `rsp_status` / `rsp_epoch` / `rsp_hit` would
   widen the arbiter interface, increasing verification surface.

4. **Test coverage**: CoherentAccess is covered by 19 unit tests as a
   standalone module. Integration tests require additional arbiter-level
   and top-level test cases for tag/signal mapping.

5. **Scope discipline**: integration would blur the boundary between
   "memory model" and "coherent access model" before either is fully
   characterized.

## 9. Integration Test Plan (Future Phase)

When integration begins, the following tests must be added:

- **Arbiter + CoherentAccess adapter** — verify tag width conversion
- **Arbiter + CoherentAccess no-loss closure** — accepted == response tag set
- **Arbiter + CoherentAccess backpressure** — queue full + response hold
- **Arbiter + CoherentAccess FAULT propagation** — `rsp_error` reaches engine
- **CoherentAccess behind 4-engine top** — mixed engine traffic
- **CoherentAccess write path from engine** — engine issues write via arbiter
- **Regression: MemoryAccess vs CoherentAccess** — same test suite on both

## 10. Summary

| Item | Status |
|------|--------|
| CoherentAccess standalone model | ✅ RTL_PASS (19 unit tests) |
| CoherentAccessAdapter shim | ✅ RTL_PASS (17 adapter tests) |
| Interface comparison with MemoryAccess | ✅ documented in §2 |
| Adapter shim requirements | ✅ documented in §4 |
| Impact on existing components | ✅ documented in §6 |
| Write path mapping | ✅ documented in §7 |
| Why not integrate now | ✅ documented in §8 |
| Integration test plan | ✅ documented in §9 |
| RTL changes to CoherentAccess | `tag_width` default 8→16 |
| Replace hardware engines | **No** |
| CPUlet firmware architecture | **No** |
| Real coherence protocol | **No — still load/store latency model** |
| Top-level integration | **Not started — future phase** |
| Adapter is bridge, not CPUlet | ✅ Yes |
