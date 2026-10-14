# CoherentAccess v0.1 — Coherent Load/Store Latency Model

> Date: 2026-06-08
> Status: CLOSED — all 19 unit tests PASS
>
> **This is an abstract model, not a full coherence protocol.**

## Scope

CoherentAccess v0.1 is a standalone coherent load/store latency model for the
chiplet accelerator side. It models coherent access latency (hit/miss), response
backpressure, and basic read/write semantics without implementing any real
cache coherence protocol.

## What CoherentAccess v0.1 IS

- **Coherent read with hit/miss latency**: read requests model access latency
  based on whether the address is a coherent-cache "hit" or "miss".
- **Coherent store with latency**: write requests model store latency with
  model-level write semantics (no real memory update).
- **Request queue with backpressure**: configurable-depth FIFO with valid-ready
  handshake; `req_ready=0` when queue full.
- **Response hold under backpressure**: `rsp_valid` holds stable when
  `rsp_ready=0`; response data/tag/status unchanged until consumed.
- **No-loss**: every accepted request produces exactly one response.
  Tag set equality guaranteed: accepted request tags == response tags.
- **Hit/mask deterministic model**: configurable `hit_mask` determines
  hit/miss per line address, enabling reproducible test patterns.
- **Error injection**: `fault_tag` triggers FAULT status on matching requests.
- **Status codes**: OK (0), FAULT (4), UNSUPPORTED (5), plus reserved
  RETRY/PERMISSION_ERROR/STALE for future use.

## What CoherentAccess v0.1 is NOT

- **NOT a full MOESI/MESI protocol**
- **NOT a cache coherence state machine**
- **NOT a snoop filter or invalidation queue**
- **NOT an ownership transfer protocol**
- **NOT a directory protocol**
- **NOT a chiplet PHY model**
- **NOT a Core cache model**
- **NOT a CXL/DPU/PCIe transport**

## Architecture Position / 架构位置

CoherentAccess v0.1 is a **standalone** coherent load/store latency and
backpressure abstraction. It does **not** replace `JasperGCAcceleratorIP`.
It does **not** replace `MemoryAccess` in the current top-level active path.
It does **not** replace `ScanEngine`, `SweepEngine`, `MetadataRebuildEngine`,
or `CompactEngine`. It does **not** introduce a small CPU / firmware execution
model. It is **not** a CPUlet firmware architecture.

Current `JasperGCAcceleratorIP` active path remains:

```
JasperGCAcceleratorIP
  → CommandQueue
  → RegionScheduler
  → Scan/Sweep/Rebuild/Compact hardware engines
  → MemoryRequestArbiter
  → MemoryAccess
  → CompletionQueue
```

CoherentAccess is prepared as a future lower-level memory access abstraction
candidate:

```
Engine memory request
  → MemoryRequestArbiter
  → MemoryAccess / CoherentAccess abstraction
  → response
```

In v0.1, CoherentAccess is standalone and unit-tested only. Top-level
integration is a future phase.

CoherentAccess v0.1 是独立的 coherent load/store 延迟与背压模型。它不替换当前
JasperGCAcceleratorIP 主线，不替换四个硬件 engine，也不引入小 CPU / firmware
架构。当前顶层 active path 仍然使用 MemoryAccess。CoherentAccess 后续可作为
MemoryAccess 下游或替代抽象接入，但当前阶段只做 standalone model。

## Architecture

```
req → [FIFO Queue depth=N] → [Hit/Miss] → [Latency Counter] → rsp
      ▲                           ← hit_latency / miss_latency / store_latency →
      req_ready
```

- **Bypass path**: when queue is empty and pipeline idle, requests bypass the
  queue and go directly to the latency counter (zero-cycle queue entry).
- **Back-to-back processing**: when a response is consumed and queued data
  exists, the next request enters the pipeline in the same cycle (no bubble).

## Configuration Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `line_size` | 64 | Address line size (bytes) |
| `hit_latency` | 2 | Cycles for coherent hit response |
| `miss_latency` | 5 | Cycles for coherent miss response |
| `store_latency` | 1 | Cycles for coherent store |
| `queue_depth` | 4 | Request queue depth |
| `hit_mask` | 0b1010 | Deterministic hit/mask bit pattern |
| `hit_mask_width` | 4 | Number of bits in hit_mask |
| `enable_write` | True | Enable write path (else UNSUPPORTED) |
| `enable_error_injection` | False | Enable FAULT injection |
| `fault_tag` | None | Tag value that triggers FAULT |

## Interface

### Request

| Signal | Direction | Width | Description |
|--------|-----------|-------|-------------|
| `req_valid` | Input | 1 | Request valid |
| `req_ready` | Output | 1 | Request ready (backpressure) |
| `req_is_write` | Input | 1 | 1=write, 0=read |
| `req_addr` | Input | 32 | Request address |
| `req_write_data` | Input | 32 | Write data (model-level) |
| `req_size` | Input | 4 | Access size (reserved) |
| `req_tag` | Input | 8 | Request tag |
| `req_epoch` | Input | 8 | Epoch identifier |
| `req_region_id` | Input | 8 | Region identifier (reserved) |
| `req_flags` | Input | 8 | Flags (reserved) |

### Response

| Signal | Direction | Width | Description |
|--------|-----------|-------|-------------|
| `rsp_valid` | Output | 1 | Response valid |
| `rsp_ready` | Input | 1 | Response ready (backpressure) |
| `rsp_read_data` | Output | 32 | Read data (0xCAFE for reads, 0 for writes) |
| `rsp_tag` | Output | 8 | Echoed request tag |
| `rsp_epoch` | Output | 8 | Echoed request epoch |
| `rsp_status` | Output | 3 | 0=OK, 4=FAULT, 5=UNSUPPORTED |
| `rsp_error` | Output | 1 | 1 for non-OK status |
| `rsp_hit` | Output | 1 | 1=coherent hit, 0=coherent miss |

## Status Codes

| Code | Name | Description |
|------|------|-------------|
| 0 | OK | Request completed successfully |
| 1 | RETRY | Transient failure (reserved, not generated in v0.1) |
| 2 | PERMISSION_ERROR | Permission denied (reserved) |
| 3 | STALE | Stale epoch (reserved) |
| 4 | FAULT | Memory fault (generated via `fault_tag`) |
| 5 | UNSUPPORTED | Operation not supported (generated for write when disabled) |

## Test Results (19 tests, all PASS)

| Test | Description |
|------|-------------|
| `test_elab` | Module elaborates successfully |
| `test_read_hit` | Read to hit address → rsp_hit=1, data=0xCAFE, status=OK |
| `test_read_miss` | Read to miss address → rsp_hit=0 |
| `test_write` | Write with enable → status=OK, read_data=0 |
| `test_write_disabled_unsupported` | Write without enable → status=UNSUPPORTED |
| `test_request_backpressure_queue_full` | Queue fills → req_ready=0 |
| `test_response_backpressure_hold` | rsp_valid holds when rsp_ready=0 |
| `test_response_data_stable` | read_data stable under backpressure |
| `test_response_tag_stable` | tag stable under backpressure |
| `test_read_tag_epoch` | Read preserves tag/epoch |
| `test_write_tag_epoch` | Write preserves tag/epoch |
| `test_accepted_equals_response` | Every accepted tag appears in responses |
| `test_no_missing_response` | No accepted tag missing from responses |
| `test_no_duplicate_response` | No tag appears twice in responses |
| `test_mixed_read_write_sequence` | Interleaved R/W all produce correct responses |
| `test_hit_miss_report` | rsp_hit correct for 4 addresses across mask |
| `test_fault_injection` | fault_tag → FAULT status + rsp_error=1 |
| `test_unsupported_status` | Disabled write → UNSUPPORTED status |
| `test_read_after_write_sequence` | Sequential write then read both complete |

## Key Design Decisions

1. **Independent module, not MemoryAccess fork**: CoherentAccess is a separate
   `Elaboratable` in its own file. This keeps the generic latency model
   (`MemoryAccess`) separate from the coherent access model. Future profile
   selection (`memory_model = "coherent" | "basic" | "future_cxl"`) will
   choose between them at the top level.

2. **Bypass for zero-cycle queue entry**: When the pipeline is idle, requests
   bypass the FIFO queue and enter the latency counter directly. This enables
   1-cycle minimum latency (latency = store_latency=1 → response in 1 cycle).

3. **Back-to-back with `done`+`can_accept`**: The `done` signal (response
   consumed this cycle) feeds into `can_accept`, allowing the next request to
   enter the pipeline in the same cycle the previous response departs.

4. **Deterministic hit/mask via address bits**: The `hit_mask` is a Python
   int; the line address index selects a bit position. This gives fully
   deterministic, reproducible hit/miss behavior across simulation runs.

## Related: CoherentAccessAdapter v0.1

A `CoherentAccessAdapter` shim is available as a combinational bridge
between the `MemoryRequestArbiter`-compatible interface and `CoherentAccess`.
See `rtl/jasper_gc_coherent_access_adapter.py`, 17 adapter unit tests,
and `reports/jasper_gc_coherent_access_adapter_v0_1.md`.

`tag_width` default changed from 8 to 16 for arbiter compatibility.
Backward compatible: `tag_width=8` still works via explicit parameter.

The adapter is **not** wired into `JasperGCAcceleratorIP`. The active path
still uses `MemoryAccess`.

## Limitations (v0.1)

- No atomic operations (RMW/CAS). FUTURE.
- No snoop/invalidation/directory. FUTURE.
- No Core cache state. FUTURE.
- No chiplet PHY. FUTURE.
- No CXL/DPU/PCIe adapters. FUTURE_BOUNDARY.
- `MemoryAccess` still the active memory model in `JasperGCAcceleratorIP`.
  CoherentAccess integration is a future phase.
- No cross-engine sharing model (arbiter not included; engines remain
  single-outstanding through MemoryRequestArbiter).
- CompletionQueue remains single-queue (pre-existing limitation).

## Follow-up Work

1. CoherentAccess adapter integration: wire CoherentAccess into
   `JasperGCAcceleratorIP` as an alternative to MemoryAccess.
2. Migrate Scan/Sweep/MRE/Compact from MemoryAccess to CoherentAccess.
3. Multi-outstanding / out-of-order access model if needed.
