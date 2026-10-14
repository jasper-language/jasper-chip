# GCSweepCoProc Dual-Engine Architecture

## 1. Problem

The current single-engine design (`gc_sweep_coproc.py`, pipelined variant
`gc_sweep_coproc_pipelined.py`) uses a round-robin arbiter that selects at
most **1 command per cycle** across all cores. When 4 cores share the engine,
per-core throughput is `1/4 cmd/cyc` in the best case. Even with response FIFO
pipelining (which removes the `~rsp_valid[sel]` backpressure), the engine
remains a single execution slot: **1.0 cmd/cyc maximum aggregate**.

With 4 active cores, each core gets **0.25 cmd/cyc** under continuous demand.

## 2. Proposed Architecture

Deploy **2 independent engines**, each handling a disjoint subset of cores:

```
Core0──┐
Core1──┤  Engine0 (bank0) ──┐
       │                    ├── Response merge → Core0-3
Core2──┤  Engine1 (bank1) ──┘
Core3──┘
```

- **Engine 0** owns cores 0, 1 (even core indices).
- **Engine 1** owns cores 2, 3 (odd core indices).
- Each engine has its own command FIFO bank (2 FIFOs), read ports, write
  ports, round-robin arbiter, `alloc_ptr`, `reloc_pending` state, and
  response FIFO bank.
- The **response merge** is trivial because engine outputs target disjoint
  core IDs — no mux arbitration needed, just wire `eng0.rsp_*` to core
  `{0,1}` and `eng1.rsp_*` to core `{2,3}`.

## 3. Two Design Options

### Option A — Table Banking (Recommended)

Split each table (`rc`, `pin`, `used`) into **2 banks** by `addr[0]`:

| Bit `addr[0]` | Bank  | Owner     | Indices              |
|---------------|-------|-----------|----------------------|
| 0             | Bank0 | Engine 0  | 0, 2, 4, …, 254     |
| 1             | Bank1 | Engine 1  | 1, 3, 5, …, 255     |

Each bank is an independent 128-entry `Memory`. Each engine gets:

- **Read ports** to BOTH banks (2 comb ports: `rc_r+pin_r+used_r` for `idx1`,
  `used2_r` for `idx2`; plus `used_ap_r` for its own `alloc_ptr`).
- **Write port** to its OWN bank only (no write conflict — bank write ports
  are never shared).

**Why this works**: A command from Engine 0 may reference an odd index
(Bank 1). The engine reads that index via the cross-bank read port. It
writes back only if the target address belongs to its bank (even). If the
target is odd, the write goes to Engine 1's bank — but Engine 0 cannot
write Bank 1 in this design.

**Key nuance for GC_NEW / alloc_ptr**:
- `alloc_ptr` advances to the NEXT free index; it may land on either bank.
- Each engine has its own `alloc_ptr` but allocates only in its own bank.
- Alternative: shared `alloc_ptr` with a simple 2-cycle handshake (rarely
  contended).

**Key nuance for RELOC**:
- Step 1 writes destination entry (may be in Engine 0 or 1 bank).
- Step 2 frees source entry (may be in the other bank).
- Since each engine writes only its own bank, a cross-bank RELOC requires
  **inter-engine write delegation**, handled by a small **cross-engine write
  request queue** (depth 2). Engine 0 sends a "write Bank 1" request to
  Engine 1, which executes it on a future cycle.

**Implementation of cross-engine writes**:
```
Engine 0 detects RELOC dst is odd → writes Bank0 normally,
  enqueues xwr_req to Engine 1: {addr, new_rc, new_pin, new_used}

Engine 1 polls xwr_req FIFO before its own RR:
  if xwr_req valid → write Bank1, dequeue (1 cycle)
```

This adds 1–3 cycles latency to cross-bank RELOC but does not stall either
engine's pipeline for ordinary commands.

### Option B — Shared Tables with Arbitration

Keep a single `rc`/`pin`/`used` table per memory (256 entries), shared by
both engines. Each engine has its own **comb read ports** (free in Amaranth).
The **write port** is arbitrated:

```
Engine0_wr_request ──┐
                      ├── Arbiter ─→ rc_w.en, pin_w.en, used_w.en
Engine1_wr_request ──┘
```

**Arbiter policy**: rotating priority (engine that won last cycle yields
priority to the other), or fixed priority with a fairness counter.

**Contention analysis**:

| Both engines write same table | Outcome                              |
|------------------------------|--------------------------------------|
| Same cycle                   | Engine A wins, Engine B stalls 1 cyc |
| Contention rate p            | `P(A write) × P(B write)`           |

At 100% utilization per engine, worst-case throughput:

- Both engines write every cycle → effective rate drops to **1.0 cmd/cyc**
  (no better than single engine) on the contended table.
- **In practice**, not every command writes every table:
  - `GC_CLONE` writes only `rc` (no `used`/`pin` contention).
  - `GC_PIN` writes only `pin`.
  - `GC_DROP` writes `rc` and maybe `used`.
- And engines rarely sustain 100% write rate simultaneously.

Nevertheless, **Option B limits peak throughput** under worst-case synthetic
workload.

## 4. Interface Changes

The **external CPU-facing interface is unchanged**:

```python
# Per-core (i = 0..3) — EXACT same signals as single engine:
self.cmd_enq_valid[i]  # input
self.cmd_enq_ready[i]  # output
self.cmd_op[i]         # input (3 bits)
self.cmd_rd[i]         # input (5 bits)
self.cmd_rs1[i]        # input (32 bits)
self.cmd_rs2[i]        # input (32 bits)
self.cmd_tag[i]        # input (8 bits)

self.rsp_valid[i]      # output
self.rsp_tag[i]        # output (8 bits)
self.rsp_rd[i]         # output (5 bits)
self.rsp_data[i]       # output (32 bits)
self.rsp_take[i]       # input

self.trap[i]           # output
self.epoch_tick[i]     # output
self.mv_upd_valid[i]   # output
self.mv_upd_old[i]     # output (32 bits)
self.mv_upd_new[i]     # output (32 bits)
self.mv_upd_ready[i]   # input
```

**Internal routing** (in top-level wrapper):

```python
# Engine 0: cores 0,1
eng0 = GCSweepCoProcEngine(ncores=2, entries=128, ...)
for i in (0, 1):
    connect(eng0, i, top, i)

# Engine 1: cores 2,3
eng1 = GCSweepCoProcEngine(ncores=2, entries=128, ...)
for i in (2, 3):
    connect(eng1, i - 2, top, i)

# Response paths are disjoint — no mux:
self.rsp_valid[0].eq(eng0.rsp_valid[0])
self.rsp_valid[1].eq(eng0.rsp_valid[1])
self.rsp_valid[2].eq(eng1.rsp_valid[0])
self.rsp_valid[3].eq(eng1.rsp_valid[1])
# ... same for all other per-core outputs
```

The CPU sees an opaque 4-core GC coproc and is unaware of the dual-engine
split.

## 5. Throughput Estimate

| Scenario                          | Single Engine | Dual Engine (banked) | Dual Engine (shared arb) |
|-----------------------------------|:-------------:|:--------------------:|:------------------------:|
| 1 core, burst                     | 1.0 cmd/cyc   | 1.0 cmd/cyc          | 1.0 cmd/cyc              |
| 2 cores (0,2 — diff engines)      | 0.5 cmd/cyc   | **2.0 cmd/cyc**      | ≈1.8 cmd/cyc*            |
| 2 cores (0,1 — same engine)       | 0.5 cmd/cyc   | 1.0 cmd/cyc (RR)     | 1.0 cmd/cyc (RR)         |
| 4 cores (0,1 on E0; 2,3 on E1)   | 1.0 cmd/cyc   | **2.0 cmd/cyc**      | ≈1.6 cmd/cyc*            |
| 4 cores write-heavy               | 1.0 cmd/cyc   | 2.0 cmd/cyc          | ≈1.3 cmd/cyc*            |

*\* Write-port contention loss depends on command mix; shown at ~70%
write-fraction.*

**Key takeaway**: Dual-engine banked (Option A) doubles throughput whenever
at least 2 cores on different engines are active. The shared-arbiter design
(Option B) softens the gain under write-heavy workloads but still beats the
single engine.

## 6. Block Diagram (ASCII Art)

```
┌─────────────────────────────────────────────────────────────┐
│                    Top ─ GCSweepCoProcDual                   │
│                                                              │
│  ┌──────────────────────────┐  ┌──────────────────────────┐  │
│  │      Engine 0            │  │      Engine 1            │  │
│  │                          │  │                          │  │
│  │  ┌────┐  ┌────┐         │  │  ┌────┐  ┌────┐         │  │
│  │  │FIFO│  │FIFO│         │  │  │FIFO│  │FIFO│         │  │
│  │  │c0  │  │c1  │         │  │  │c2  │  │c3  │         │  │
│  │  └─┬─┘  └─┬─┘         │  │  └─┬─┘  └─┬─┘         │  │
│  │    └──┬───┘            │  │    └──┬───┘            │  │
│  │       ▼                │  │       ▼                │  │
│  │  ┌────────┐           │  │  ┌────────┐           │  │
│  │  │ RR arb │           │  │  │ RR arb │           │  │
│  │  └───┬────┘           │  │  └───┬────┘           │  │
│  │       ▼                │  │       ▼                │  │
│  │  ┌────────┐           │  │  ┌────────┐           │  │
│  │  │Execute │           │  │  │Execute │           │  │
│  │  └──┬─┬─┬─┘           │  │  └──┬─┬─┬─┘           │  │
│  │     │ │ │              │  │     │ │ │              │  │
│  │     ▼ ▼ ▼              │  │     ▼ ▼ ▼              │  │
│  │  rc0 pin0 used0        │  │  rc1 pin1 used1        │  │
│  │  (128 entries)         │  │  (128 entries)         │  │
│  │  addr[8:1], even idx   │  │  addr[8:1], odd idx    │  │
│  └─────────┬──────────────┘  └─────────┬──────────────┘  │
│            │                           │                  │
│            ▼                           ▼                  │
│  ┌──────────────────────────────────────────────┐        │
│  │  Response merge (wires, no logic)             │        │
│  │  E0.rsp[0]→core0  E0.rsp[1]→core1           │        │
│  │  E1.rsp[0]→core2  E1.rsp[1]→core3           │        │
│  └──────────────────────────────────────────────┘        │
└─────────────────────────────────────────────────────────────┘
```

## 7. Implementation Plan

### Files to create

| File | Purpose |
|------|---------|
| `rtl/gc_sweep_coproc_banked.py` | Banked table memories (128×16 rc, 128×1 pin, 128×1 used) |
| `rtl/gc_sweep_coproc_engine.py` | Single engine (takes `ncores=2`), reusable by both engines |
| `rtl/gc_sweep_coproc_dual.py`  | Top wrapper: instantiates 2 engines, wires core I/O |
| `tb/test_gc_dual_engine.py`    | Testbench for dual-engine throughput verification |

### Files to modify

| File | Change |
|------|--------|
| `rtl/gc_sweep_coproc_pipelined.py` | Extract engine core into reusable base class |
| (none if starting fresh) | — |

### `gc_sweep_coproc_engine.py` — Signal List

The engine is a **parameterized single engine** identical in behavior to the
pipelined design, but with 2 cores (`ncores=2`) and accesses a banked table
group:

```python
class GCSweepCoProcEngine(Elaboratable):
    def __init__(self, core_base, ncores=2, entries=128, fifo_depth=8,
                 rsp_fifo_depth=8, bank_sel=0):
        # Core-base offset for tags/IDs (0 or 2 in dual config)
        self.core_base = core_base
        self.ncores = ncores          # always 2
        self.entries = entries        # 128 per bank
        self.fifo_depth = fifo_depth
        self.rsp_fifo_depth = rsp_fifo_depth
        self.tag_w = 8
        self.bank_sel = bank_sel      # 0 or 1

        # External command FIFO interface (per core, NOT full 4)
        self.cmd_enq_valid = Array(Signal(name=f"cmd{core_base+i}_valid")
                                   for i in range(ncores))
        self.cmd_enq_ready = Array(Signal(name=f"cmd{core_base+i}_ready")
                                   for i in range(ncores))
        self.cmd_op        = Array(Signal(3, ...) for i in range(ncores))
        self.cmd_rd        = Array(Signal(5, ...) for i in range(ncores))
        self.cmd_rs1       = Array(Signal(32, ...) for i in range(ncores))
        self.cmd_rs2       = Array(Signal(32, ...) for i in range(ncores))
        self.cmd_tag       = Array(Signal(self.tag_w, ...) for i in range(ncores))

        # Response FIFO interface (per core)
        self.rsp_valid     = Array(Signal(name=f"rsp{core_base+i}_valid")
                                   for i in range(ncores))
        self.rsp_tag       = Array(Signal(self.tag_w, ...) for i in range(ncores))
        self.rsp_rd        = Array(Signal(5, ...) for i in range(ncores))
        self.rsp_data      = Array(Signal(32, ...) for i in range(ncores))
        self.rsp_take      = Array(Signal(name=f"rsp{core_base+i}_take")
                                   for i in range(ncores))

        # Sideband outputs
        self.trap          = Array(Signal(name=f"trap{core_base+i}")
                                   for i in range(ncores))
        self.epoch_tick    = Array(Signal(name=f"epoch{core_base+i}_tick")
                                   for i in range(ncores))
        self.mv_upd_valid  = Array(Signal(...) for i in range(ncores))
        self.mv_upd_old    = Array(Signal(32, ...) for i in range(ncores))
        self.mv_upd_new    = Array(Signal(32, ...) for i in range(ncores))
        self.mv_upd_ready  = Array(Signal(reset=1, ...) for i in range(ncores))

        # Cross-engine write request (Option A only)
        # Engine receives writes from the OTHER engine for entries in its bank
        self.xwr_valid     = Signal()     # input
        self.xwr_addr      = Signal(8)    # index in this bank
        self.xwr_rc        = Signal(16)
        self.xwr_pin       = Signal(1)
        self.xwr_used      = Signal(1)
        self.xwr_ready     = Signal()     # output
```

### State Machine Changes (vs. pipelined single engine)

1. **RR arbiter range**: `rr_ptr` cycles over 2 cores instead of 4.
2. **`can_accept`**: checks `have & ~reloc_pending & rsp_fifo_arr[sel].w_rdy`
   (same as pipelined, no change).
3. **Write address mapping**: `idx1`/`idx2` are full 8-bit indices. Before
   write, check `addr[0] == bank_sel`. If mismatch, delegate via
   cross-engine write request queue.
4. **GC_NEW**: `alloc_ptr` produces a new index whose `addr[0]` equals
   `bank_sel`. (Engine 0 always allocates even indices; Engine 1 always
   allocates odd indices.)
5. **RELOC write split**:
   - Step 1 writes destination entry. If `dst_addr[0] == bank_sel` → write
     directly. If not → enqueue to sibling engine's `xwr_valid`.
   - Step 2 frees source entry. Same check.

## 8. Risk Assessment

### Risk 1: Cross-bank RELOC latency

**Issue**: When `RELOC src` is in Engine 0's bank and `dst` is in Engine 1's
bank, step 1 must write both banks (dst write via cross-engine request).
Step 2 frees src (Engine 0's bank).

**Impact**: Cross-bank RELOC takes 2–3 extra cycles. During this time, the
requesting engine's `reloc_pending` prevents it from issuing new commands.

**Mitigation**: Cross-bank RELOC is rare (50% probability assuming uniform
address distribution). Even when it happens, only the issuing engine stalls;
the other engine continues at full throughput.

### Risk 2: Table coherency

**Issue**: Both engines read indices from both banks. If only cross-engine
*reads* are allowed but *writes* go only to the owning bank, there is NO
coherency problem — each index has exactly one writer. This is the key
advantage of Option A over Option B.

**Mitigation**: Already inherent in Option A design. For Option B, writes
go through a single arbiter and serialization guarantees coherency.

### Risk 3: `alloc_ptr` starvation

**Issue**: Engine 0 allocates even indices; Engine 1 allocates odd indices.
If one engine's allocator is heavily used, it may exhaust its half of the
address space while the other engine's half is underutilized.

**Impact**: Reduced effective heap utilization (worst case: 128 entries
usable per engine, 256 total — same as single engine's 256).

**Mitigation**: None needed for correctness. A future improvement could add
a cross-engine alloc_ptr borrow mechanism, but the 256-entry table with 2
half-banks is sufficient for most workloads.

### Risk 4: Cross-engine write queue overflow

**Issue**: If Engine 0 sends many cross-bank writes in rapid succession,
Engine 1's `xwr` request FIFO overflows.

**Mitigation**: The `xwr` queue depth is bounded (e.g., 2 entries). Before
Engine 0 issues a cross-bank write, it checks `xwr_ready`. If not ready,
Engine 0 stalls — exactly the same backpressure as write-port contention in
Option B.

### Risk 5: mv_upd sideband duplication

**Issue**: RELOC commits produce one `mv_upd` pulse. In the dual-engine
design, the pulse must be generated by the engine executing the RELOC
(which may be either engine).

**Impact**: The `mv_upd` outputs are already per-core and disjoint. No
duplication or loss — each engine drives its own cores' `mv_upd` signals.

## 9. Key Decisions Summary

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Engine-core mapping** | Engine 0 → cores 0,1; Engine 1 → cores 2,3 | Simple static split; each engine owns 2 cores |
| **Table architecture** | **Option A: Banking by addr[0]** | Eliminates write-port contention; both engines can write every cycle |
| **Per-engine entries** | 128 each (half of 256) | 2× memory but no arbitration logic; each Memory is smaller |
| **alloc_ptr** | Per-engine, own half | Avoids shared-allocator arbitration; each engine only allocates in its bank |
| **Cross-bank RELOC** | Dedicated `xwr` request queue (depth 2) | Simple extension; stalls issuing engine only when queue full |
| **Response merge** | Direct wiring (no mux) | Engine outputs target disjoint core IDs |
| **Reuse strategy** | Single `Engine` class parameterized by `core_base` and `bank_sel` | Minimal code duplication; test once, instantiate twice |

## 10. Expected Throughput vs. Original

```
Throughput (cmd/cyc) vs. number of active cores:

cores│ single-engine  │ dual-engine (banked) │ dual-engine (shared)
     │ (original)     │ (Option A)           │ (Option B)
─────┼────────────────┼──────────────────────┼─────────────────────
  1  │     1.0        │       1.0            │       1.0
  2  │     0.5        │       2.0 (diff eng) │      ≈1.8
  2  │     0.5        │       1.0 (same eng) │       1.0
  3  │     0.75       │       2.0 (2+1)      │      ≈1.7
  4  │     1.0        │       2.0            │      ≈1.6
```

The **banked design (Option A)** achieves **2.0 cmd/cyc aggregate** with 2+
cores on different engines — a **2× improvement** over the single-engine
baseline.
