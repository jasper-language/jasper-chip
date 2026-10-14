# ChipletLinkModel — Design Plan

> Date: 2026-06-10  
> Status: **DESIGN_PLAN**  
> This document defines the simulation model for a die-to-die chiplet interconnect,
> analogous to `MemoryAccess` (shift-register latency model) and `CoherentAccess`
> (hit/miss coherent model). It is **not a real PHY** — it is a verification-
> oriented RTL module that models latency, bandwidth, and backpressure between
> chiplets.

---

## 1. Motivation

The accelerator's mainline form factor is CPU-package / chiplet (§2 of design
rationale). The accelerator sits on a separate chiplet and communicates with
the host memory subsystem across a die-to-die link. **Every memory request**
from the accelerator engines (scan/sweep/mre/compact) crosses this link.

Without a chiplet link model, verification sees only ideal zero-delay
transport — which hides real-world effects:

- **Latency**: Die-to-die links add 10–100 ns (10–200 cycles at 2 GHz) per
  crossing. This affects engine throughput and pipeline utilization.
- **Bandwidth**: Link width (flit size × frequency) constrains peak throughput.
  Engines that burst reads will stall when link bandwidth is exhausted.
- **Backpressure**: Credit-based or ready/valid backpressure propagates from
  the remote memory controller through the link back to the accelerator.
  The arbiter and engines must tolerate variable response spacing.
- **Flit-level effects**: Partial flit writes, alignment, ECC errors, link
  training transitions (if modeled) are invisible in a zero-delay model.

**What this model enables:**
- Realistic throughput and bottleneck analysis in simulation
- Backpressure stress testing (link full → engine stalls → scheduler pressure)
- Comparison of single-channel vs. multi-channel link configurations
- A drop-in replacement for `MemoryAccess` in chiplet-topology testbenches
- Early driver and firmware development with timing-accurate response timing

---

## 2. Interface Design

The link model must be a **drop-in compatible alternative** to `MemoryAccess`
and `CoherentAccess` — it sits behind `MemoryRequestArbiter` at the same
integration point. This means it uses the same memory-request interface
(valid/ready/addr/tag/is_write), plus additional link-specific signals.

### 2.1 Primary Interface (MemoryRequestArbiter-compatible)

| Signal | Width | Direction | Description |
|--------|-------|-----------|-------------|
| `req_valid` | 1 | in | Request valid from arbiter |
| `req_ready` | 1 | out | Link can accept request |
| `req_is_write` | 1 | in | 0=read, 1=write |
| `req_addr` | 32 | in | Target address |
| `req_tag` | 16 | in | Correlation tag |
| `req_burst` | 8 | in | Burst length (in 32-bit words) |
| `rsp_valid` | 1 | out | Response valid to arbiter |
| `rsp_ready` | 1 | in | Arbiter accepts response |
| `rsp_read_data` | 32 | out | Read data (DEADBEEF pattern in model) |
| `rsp_tag` | 16 | out | Echo of request tag |
| `rsp_error` | 1 | out | Link error |

This matches the `MemoryAccess` interface exactly. No adapter needed for the
arbiter integration.

### 2.2 Link-side Interface (for multi-chiplet topology)

When multiple chiplets are wired together (e.g., accelerator chiplet +
memory chiplet), these signals connect modules in a topology:

| Signal | Width | Direction | Description |
|--------|-------|-----------|-------------|
| `link_tx_flit_valid` | 1 | out | Flit transmitted |
| `link_tx_flit_ready` | 1 | in | Remote accepts flit |
| `link_tx_flit_data` | flit_width | out | Flit payload |
| `link_tx_flit_type` | 2 | out | 0=data, 1=credit, 2=idle, 3=error |
| `link_rx_flit_valid` | 1 | in | Flit received |
| `link_rx_flit_ready` | 1 | out | This side accepts flit |
| `link_rx_flit_data` | flit_width | in | Flit payload |
| `link_rx_flit_type` | 2 | in | Flit type |

These are **optional** — the model can be used in single-ended mode (just
primary interface, internal delay pipeline) or in dual-ended mode (two
`ChipletLinkModel` instances connected back-to-back via link signals for
topology simulation).

### 2.3 Credit Interface

| Signal | Width | Direction | Description |
|--------|-------|-----------|-------------|
| `tx_credits` | log2(credit_pool+1) | in | Available transmit credits |
| `rx_credits` | log2(credit_pool+1) | out | Remote credits returned |

---

## 3. Parameters

| Parameter | Default | Range | Description |
|-----------|---------|-------|-------------|
| `link_latency` | 32 | 1–256 | Round-trip latency in cycles (die-to-die) |
| `flit_width` | 64 | 32–512 | Flit width in bits |
| `flits_per_cycle` | 1 | 1–4 | Flits transferred per cycle (parallel lanes) |
| `link_queue_depth` | 8 | 2–64 | Queue depth at each link endpoint |
| `credit_pool` | 16 | 2–256 | Initial credit count (if credit-based) |
| `burst_max` | 16 | 1–64 | Maximum burst length in flits |
| `error_rate` | 0.0 | 0.0–1.0 | Flit error injection probability |
| `enable_credit_flow` | True | — | Use credit-based (vs. ready/valid) flow control |
| `enable_partial_flit` | False | — | Model sub-flit writes with alignment |
| `profile` | "standard" | — | Preset latency/bandwidth combination |

### 3.1 Profile Presets

| Profile | Latency (cyc) | Flit width | Flits/cyc | Credit pool | Use case |
|---------|:-----------:|:----------:|:---------:|:-----------:|----------|
| `standard` | 32 | 64 | 1 | 16 | CPU-package die-to-die (default) |
| `low_latency` | 8 | 128 | 1 | 32 | Co-packaged / 3D-stacked |
| `high_bw` | 48 | 256 | 2 | 64 | Multi-channel chiplet link |
| `extreme` | 64 | 512 | 4 | 128 | HBM-attached accelerator |
| `adapter` | 80 | 128 | 1 | 32 | CXL/PCIe adapter placeholder |

The `adapter` profile models the extra latency of a protocol bridge; it is
reserved for FUTURE_BOUNDARY use.

---

## 4. Behavior

### 4.1 Pipeline Model

```
Request accepted
  → Request queue (FIFO, depth = link_queue_depth)
  → Flit assembly (request split into N flits, flits_per_cycle wide)
  → Link pipeline (shift-register, latency = link_latency cycles)
  → Remote endpoint queue
  → Flit reassembly (collect flits into response)
  → Response pipeline (shift-register, latency = link_latency cycles)
  → Response queue
  → Response issued (rsp_valid)
```

The pipeline is symmetric: request traverses the link in `link_latency` cycles,
response returns in `link_latency` cycles, for a **total round-trip of
`2 × link_latency + processing`** cycles.

**Flit decomposition**: A request (addr + tag + flags) is packed into one or
more flits. A response (data + tag + status) is packed similarly. When
`flit_width < 64`, a single request/response may span multiple flits; the
model tracks partial-flit state.

### 4.2 Backpressure Mechanisms

Two modes, selectable via `enable_credit_flow`:

**Mode A: Ready/Valid (simpler)**
- Each queue stage uses standard valid/ready handshake.
- Full queue → upstream `req_ready=0` → arbiter stalls → engine stalls.
- Backpressure propagates instantaneously within the model (no separate
  backpressure latency).

**Mode B: Credit-based flow control (realistic)**
- `credit_pool` initial credits at both ends.
- Each flit transmission consumes one credit.
- Credit return flit (`link_tx_flit_type=1`) is sent when remote processes
  a flit.
- `tx_credits = 0` → stall transmission → backpressure.
- Credit return has its own link latency (`link_latency` cycles), modeling
  real credit round-trip delay.
- This mode exposes **pipeline bubbles** from credit starvation — a key
  real-world effect invisible in simple ready/valid.

### 4.3 Internal State Machine

```
IDLE → (req_valid & req_ready) → FLIT_SEND → (all flits sent) → WAIT_RSP
        ↓                                                        ↓
   (queue full = IDLE)                                    (rsp_valid & rsp_ready)
                                                          → COMPLETE → IDLE
```

Each flit send stage tracks:
- Current flit offset within the request/response
- Credits remaining (in credit mode)
- Error injection (based on `error_rate`, probabilistic)

### 4.4 Error Injection

When `error_rate > 0`:
- A random subset of flits are marked with `link_tx_flit_type=3` (error).
- On error detection at the remote end, the affected request is retired
  with `rsp_error=1`.
- The engine/arbiter is expected to retry or escalate.
- Error injection follows a simple cycle-accurate LFSR for deterministic
  reproducibility.

### 4.5 No-Loss Guarantee

Same contract as `MemoryAccess` and `CoherentAccess`: every accepted request
produces exactly one response, and the set of `rsp_tag` values equals the set
of accepted `req_tag` values. Errors produce a response with `rsp_error=1`
but do not drop the response.

---

## 5. Integration

### 5.1 Primary Integration Point (v0.1)

The link model is a drop-in replacement for `MemoryAccess` behind the
`MemoryRequestArbiter`:

```
Engine memory request
  → MemoryRequestArbiter
  → ChipletLinkModel (replaces MemoryAccess)
  → response
```

In `JasperGCAcceleratorIP.elaborate()`, the `MemoryAccess` instantiation is
replaced (or selected via parameter) with `ChipletLinkModel`:

```python
if mem_en:
    arb = MemoryRequestArbiter()
    if use_chiplet_link:
        mem = ChipletLinkModel(link_latency=32, ...)
    else:
        mem = MemoryAccess(read_latency=4, ...)
```

No changes to the arbiter, engines, scheduler, or command/completion path.

### 5.2 Dual-Ended Topology (Future)

For full chiplet-to-chiplet simulation, two `ChipletLinkModel` instances are
connected via `link_tx_*` / `link_rx_*` signals. This enables:

- Accelerator chiplet ↔ Memory controller chiplet
- Multi-hop topologies (accelerator → switch → memory)

### 5.3 Profile selection

The `profile` parameter maps to `chiplet_accel_*` profiles from
`jasper_gc_chiplet_accelerator_profiles.md`:

| Accelerator Profile | Link Profile | Rationale |
|--------------------|-------------|-----------|
| `chiplet_accel_standard` | `standard` | 1L die-to-die, 32 cyc latency |
| `chiplet_accel_server` | `high_bw` | 2L or wider, higher throughput |
| `chiplet_accel_extreme` | `extreme` | Multi-channel, HBM-class |

### 5.4 Configuration via `JasperGCConfig`

The `JasperGCConfig` dataclass would gain optional link parameters:

```python
@dataclass
class JasperGCConfig:
    # ... existing fields ...
    enable_chiplet_link: bool = False
    chiplet_link_latency: int = 32
    chiplet_flit_width: int = 64
    chiplet_link_queue_depth: int = 8
    chiplet_credit_pool: int = 16
    chiplet_profile: str = "standard"
```

Validation: `chiplet_link_latency` must be ≥ 1; `chiplet_flit_width` must be
a power of 2 and ≥ 32; `chiplet_credit_pool` must be ≥ `link_queue_depth`.

---

## 6. Verification Plan

### 6.1 Unit Tests (ChipletLinkModel standalone)

| Test | Description |
|------|-------------|
| `test_basic_read` | Single read request → response after `2 × link_latency` |
| `test_basic_write` | Single write accepted, response with OK status |
| `test_burst_read` | Burst of N flits, all responses received, no-loss checked |
| `test_queue_full_backpressure` | Saturate queue → `req_ready=0` → drain → `req_ready=1` |
| `test_response_hold` | `rsp_ready=0` stalls pipeline, no flit loss |
| `test_credit_starvation` | Send N=credit_pool requests, credit=0 stalls, credit return resumes |
| `test_credit_round_trip` | Verify credit return takes `link_latency` cycles |
| `test_no_loss_closure` | 1000 random requests, verify accepted == response tag set |
| `test_error_injection` | `error_rate > 0`, verify `rsp_error=1` for affected requests |
| `test_partial_flit` | Request smaller than flit, verify correct assembly |
| `test_profile_presets` | Each profile preset produces expected latency/throughput |
| `test_flit_width_variation` | 32/64/128/256-bit flit widths, verify flit count per request |

### 6.2 Integration Tests (ChipletLinkModel + Arbiter)

| Test | Description |
|------|-------------|
| `test_arbiter_chiplet_no_loss` | 4 engines, chiplet link, no-loss closure |
| `test_arbiter_chiplet_backpressure` | Queue full → arbiter stalls → all engines blocked |
| `test_arbiter_chiplet_priority` | Compact stalls during link full → sweep accepted later |
| `test_arbiter_chiplet_burst_interleave` | Mixed short/burst requests, correct routing |
| `test_perf_counters_chiplet` | Arbiter debug signals with chiplet latency |

### 6.3 Top-Level Tests (ChipletLinkModel in JasperGCAcceleratorIP)

| Test | Description |
|------|-------------|
| `test_accel_chiplet_scan` | Scan engine through chiplet link, completion observed |
| `test_accel_chiplet_4engine` | All 4 engines through chiplet link, correct completions |
| `test_accel_chiplet_stress` | Back-to-back commands, link saturation, no-loss |
| `test_accel_chiplet_regression` | Same test suite as MemoryAccess, verify passing |

### 6.4 Key Metrics to Verify

| Metric | Expected |
|--------|----------|
| Minimum response latency | `2 × link_latency` cycles |
| Throughput under no backpressure | 1 req per `ceil(req_flits / flits_per_cycle)` cycles |
| Credit-starvation throughput | 0 when `tx_credits=0` |
| No-loss closure | 100% (accepted == response tag set) |
| Error response ratio | Within ±5% of configured `error_rate` |

---

## 7. Relationship to CXL/PCIe FUTURE_BOUNDARY

The chiplet link model is **not** a CXL or PCIe model. It explicitly stops
at the die-to-die interface.

| Aspect | ChipletLinkModel | CXL/PCIe Adapter (FUTURE) |
|--------|-----------------|--------------------------|
| Protocol | Raw flit (valid/ready/data) | CXL.mem / PCIe TLP |
| Latency | Fixed, configurable | Variable (protocol-dependent) |
| Flow control | Credit-based (simple) | CXL credit + retry |
| Error handling | Single-bit error injection | ECC, CRC, replay |
| Transaction layer | None (model skips TL) | Full CXL/PCIe TL |
| Ordering model | Strict FIFO per endpoint | Relaxed / PCIe ordering rules |
| Integration | Behind arbiter (same as MemoryAccess) | External adapter with DMA |

The `adapter` profile (§3.1) provides a placeholder latency value for what
CXL/PCIe overhead might look like, but the model does **not** implement any
protocol-specific behavior. When CXL/PCIe adapters are implemented, the
chiplet link model will still serve as the **local die-to-die transport**
between the accelerator and the adapter PHY:

```
Accelerator → ChipletLinkModel → CXL/PCIe Adapter (FUTURE) → Host
```

The chiplet link between the accelerator die and the adapter die remains
relevant even in a CXL/PCIe configuration.

---

## 8. Implementation Sketch (RTL_PLANNING)

The module will be implemented as `rtl/jasper_gc_chiplet_link.py` with the
following structure:

```python
class ChipletLinkModel(Elaboratable):
    def __init__(self, *,
                 link_latency=32,
                 flit_width=64,
                 flits_per_cycle=1,
                 link_queue_depth=8,
                 credit_pool=16,
                 burst_max=16,
                 error_rate=0.0,
                 enable_credit_flow=True,
                 enable_partial_flit=False,
                 profile="standard"):
        ...
```

Internal sub-blocks:
- `_FlitAssembler` — packs request/response into flits
- `_LatencyPipe` — shift-register delay (same pattern as `MemoryAccess`)
- `_CreditManager` — credit accounting + return flit generation
- `_ErrorInjector` — probabilistic flit error marking

The design follows the same conventions as `MemoryAccess` and
`CoherentAccess`: Amaranth `Signal`-based, sync-domain, using similar
shift-register and FIFO patterns.

---

## 9. Open Questions

1. **Should credit return have its own dedicated flit type, or piggyback on
   data flits?** — Dedicated flit type is simpler and matches dedicated
   credit wires in real D2D links (e.g., BoW, UCIe). Piggybacking adds
   assembly complexity. Recommendation: dedicated flit type for v0.1.
2. **Single outstanding vs. multiple outstanding?** — The model can support
   multiple outstanding requests (unlike the arbiter). The link should
   support `link_queue_depth` outstanding, matching realistic D2D links that
   pipeline transactions.
3. **Flit ordering within a burst?** — Strict ordering (same as MemoryAccess).
   Out-of-order flits add complexity that is not representative of simple
   D2D links.
4. **Link training / initialization?** — Out of scope for v0.1. The model
   starts fully trained. A `link_up` signal could be added later.
