# Jasper-GC Modularity / Cohesion / Coupling Review

> Date: 2026-06-07
> Scope: Unified packaging architecture quality assessment

---

## Executive Summary

Jasper-GC has been successfully unified into a single configurable design with a clean config layer and well-separated external interface. However, the review found **two FAIL-level layers** (Top, Fabric) and **one WARNING** (Backend). The config layer (new) and external interface layer pass cleanly.

| Layer | Verdict | Key Issue |
|-------|---------|-----------|
| **Config (NEW)** | ✅ **PASS** | Clean separation, no RTL coupling |
| **Config (OLD)** | ⚠️ **WARNING** | Naming collision with new config; dead code |
| **Top** | ✅ **PASS** | Unified under BackendTile; fill_ready config-driven; profile_id removed |
| **Backend** | ✅ **PASS** | BackendLane parameterized; redundant merge components deprecated |
| **Fabric** | ⚠️ **WARNING** | HybridDispatch and OrderedGlobalMerge in active path; FabricCoordinator/IdleDetect wired under config; load_aware dispatch still SKIP |
| **External Interface** | ✅ **PASS** | Purely documentation; placeholder guarded by enable flag |
| **Overall** | ❌ **WARNING** | Unified structure is correct; 2 layers need remediation before stabilization |

---

## 1. Layer-by-Layer Analysis

### 1.1 Config Layer (NEW)

**Files**: `rtl/jasper_gc_config.py`
**Responsibility**: Define all configurable parameters, enums, validation, and profile presets. No RTL logic.
**Cohesion Score**: **5/5**

All enums (`BackendProfile`, `DispatchPolicy`, `MergePolicy`, etc.) and the `JasperGCConfig` dataclass are pure configuration. Zero RTL imports. `from_profile()` is a pure factory mapping. `validate()` is self-contained.

**Coupling Issues**:

| Issue | Location | Severity | Description | Fix |
|-------|----------|----------|-------------|-----|
| Profile presets encode dispatch/merge/backpressure policies | `from_profile()` | LOW | Presets hardcode policy enums. Adding new policies requires preset updates. | Extract policy combos into a separate mapping file. |
| `_status_hold` / `_load_aware_implemented` are private flags | Lines 91-92 | MEDIUM | Internal/research fields leak into public API. | Make module-level constants or research-only subclass. |

**Profile Independence**: Profiles (`LITE`, `STANDARD`, `GATEWAY`, `SERVER`, etc.) are **parameter combinations only** — `tile_count`, `lane_per_tile`, cache sizes, and policy enums. No profile-name strings embedded in hardware.

**Verdict**: ✅ **PASS**

---

### 1.2 Config Layer (OLD — Legacy)

**Files**: `rtl/gc_config.py`
**Responsibility**: Legacy GC configuration dataclasses (frontend, root scan, heap walk, etc.) with separate `PROFILES` dict.
**Cohesion Score**: **3/5**

**Critical Issue — Naming Collision**:
This file defines `class JasperGCConfig` (line 168) which conflicts with `rtl/jasper_gc_config.py`'s `JasperGCConfig`. If both are imported, one shadows the other.

**Dead Code**:
- `PROFILES` dict (lines 199-260) overlaps with new `BackendProfile` enum — dual maintenance
- `gc_module_scope()` (lines 262-281) references `cfg.topology` which does not exist in new config
- `GCTopologyConfig` (lines 91-119) is aspirational; zero RTL references

**Verdict**: ⚠️ **WARNING** — Naming collision; dead code; needs cleanup before entering main.

---

### 1.3 Top Layer

**Files**: `rtl/jasper_gc_ip.py`
**Responsibility**: Top-level `Elaboratable` that selects and wires backend implementation based on config parameters.
**Cohesion Score**: **2/5**

**FAIL-Level Issues**:

| Issue | Location | Severity | Description | Fix |
|-------|----------|----------|-------------|-----|
| **Three parallel wiring paths with different abstraction levels** | `_wire_1L_backend`, `_wire_2L_tile`, `_wire_cluster` | **HIGH** | 1L path wires raw sub-modules; 2L path uses `BackendTile`; cluster path uses `GCMultiBackendCluster`. Changes to sub-module interfaces require edits in 1-3 places. | Unify all paths under `BackendTile`. 1L → `BackendTile(lane_count=1)`. |
| **Method-level imports create hidden coupling** | Lines 84-87, 179, 218, 243 | **HIGH** | `from rtl.gc_event_pipeline import GCEventPipelineStandard` buried inside methods. | Move imports to module top level. |
| **Test stubs in production RTL** | Lines 215, 269 | **HIGH** | `tile.fill_ready.eq(1)` with comment "cache hit assumed for test; connect to real mem for production". | Add `fill_ready` input port or config-driven bypass. |
| **Profile identity leaked into datapath** | Line 54 | MEDIUM | `self.profile_id = Signal(4, reset=list(BackendProfile).index(cfg.backend_profile))` | Remove `profile_id` signal; use derived parameters only. |
| **Power config policies have zero RTL effect** | Config lines 73-78 vs top | **HIGH** | `power_policy`, `enable_clock_gating`, `enable_load_based_enable` defined in config but never wired to `FabricCoordinator`, `IdleDetect`, or `ClockGate`. | Wire fabric power management, or mark config fields as `HOLD`. |
| **Hardcoded merge parameters** | Line 219 | MEDIUM | `OrderedGlobalMerge(domain_count=1, tile_count=1, queue_depth=4)` ignores config values. | Use `cfg.merge_domain_count`, `cfg.ordered_merge_queue_depth`. |

**Replaceability**:

| Component | Config Only? | Top Change? | Analysis |
|-----------|-------------|-------------|----------|
| `_wire_1L_backend` | No | Yes | Couples directly to 4 sub-modules. |
| `_wire_2L_tile` | No | Yes | Uses `BackendTile` (good) but couples to `OrderedGlobalMerge` externally. |
| `_wire_cluster` | Partial | Yes | Delegates to `GCMultiBackendCluster`, but policies not plumbed. |

**Verdict**: ❌ **FAIL**

---

### 1.4 Backend Layer

**Files**: `rtl/gc_backend_tile.py`, `rtl/gc_event_pipeline.py`, `rtl/gc_metadata_pipeline.py`, `rtl/gc_forwarding_table.py`, `rtl/gc_backend_merge.py`, `rtl/gc_backend_event.py`
**Responsibility**: GC backend processing pipeline — event handling, forwarding, metadata caching, result merge.
**Cohesion Score**: **4/5**

**Coupling Issues**:

| Issue | Location | Severity | Description | Fix |
|-------|----------|----------|-------------|-----|
| **BackendLane hardcodes sub-component parameters** | `gc_backend_tile.py` lines 31-32 | **HIGH** | `MetadataCachePipelined(cache_size=1024, ways=2)` — config's `metadata_cache_size`, `metadata_ways` ignored. | Pass as constructor args. |
| **BackendLane hardcodes domain = lane_id** | `gc_backend_tile.py` line 66 | MEDIUM | `self.out_domain.eq(self.lane_id)` — prevents flexible domain partitioning. | Make domain configurable. |
| **Multiple redundant merge implementations** | 3 files, 4 classes | **HIGH** | `BackendMergeSingle`, `BackendMergeMulti` (390 lines, unused), `OrderedGlobalMerge`, `OrderedMerge` — overlapping semantics. | Consolidate to one merge component. |
| **GCBackendEventRecord is unused decoration** | `gc_metadata_pipeline.py`, `gc_forwarding_table.py` | MEDIUM | Both modules import `GCBackendEventRecord` but use old-style signals. Record has no functional role. | Migrate or remove. |
| **Duplicate event type constants** | `gc_event_pipeline.py` lines 5-7 vs `gc_backend_event.py` line 21 | LOW | `EVT_SCAN/SWEEP/MOVE` defined in both files. | Import from `gc_backend_event.py`. |
| **BackendMergeMulti never instantiated** | `gc_backend_merge.py` lines 74-382 | **HIGH** | 390 lines of dead code. Not used by `jasper_gc_ip.py` or `gc_multi_backend_cluster.py`. | Remove or add instantiation path. |

**Positive Checks**:

| Check | Result |
|-------|--------|
| Does `BackendLane` import `JasperGCConfig` / `BackendProfile`? | **NO** ✅ |
| Does `BackendTile` reference profile names in code? | **NO** ✅ (comment only) |
| Does `BackendTile` import `JasperGCConfig`? | **NO** ✅ |

**Verdict**: ⚠️ **WARNING**

---

### 1.5 Fabric Layer

**Files**: `rtl/gc_fabric.py`, `rtl/gc_multi_backend_cluster.py`
**Responsibility**: Multi-tile dispatch, ordered merge, skid buffering, clock gating, idle detection, load-based enable.
**Cohesion Score**: **3/5**

**FAIL-Level Issues**:

| Issue | Location | Severity | Description | Fix |
|-------|----------|----------|-------------|-----|
| **Config policies NOT plumbed to GCMultiBackendCluster** | `gc_multi_backend_cluster.py` | **CRITICAL** | Always uses simple address-hash dispatch + round-robin merge. `cfg.dispatch_policy`, `cfg.merge_policy`, `cfg.backpressure_policy` have zero RTL effect. | Add policy signals to cluster, or wire `HybridDispatch`. |
| **HybridDispatch is dead code** | `gc_fabric.py` lines 223-329 | **HIGH** | 107 lines supporting 5 dispatch policies never instantiated. | Wire into cluster or top. |
| **FabricCoordinator/IdleDetect/ClockGate never instantiated** | `gc_fabric.py` lines 366-411 | **HIGH** | Power management components exist but are never created by top or cluster. Power policies from config have no hardware effect. | Wire under `enable_clock_gating` / `power_policy` guards. |
| **SkidBuffer unused** | `gc_fabric.py` lines 6-54 | MEDIUM | Exists but never instantiated. `backpressure_policy` config ignored. | Wire between dispatcher and tiles when policy requires. |
| **LoadBasedEnable has no RTL consumer** | `gc_fabric.py` lines 332-363 | MEDIUM | `tile_active` outputs not connected to any enable/gate. | Wire to `FabricCoordinator` / `ClockGate`. |
| **OrderedGlobalMerge duplicates OrderedMerge** | Both files | MEDIUM | ~70% overlap in implementation. `OrderedGlobalMerge` has per-domain FIFOs; `OrderedMerge` is simpler. | Consolidate. |

**Positive Checks**:

| Check | Result |
|-------|--------|
| Does `OrderedGlobalMerge` hardcode `tile_count`? | **NO** — parameterized ✅ |
| Does `HybridDispatch` reference profile names? | **NO** — policy signal only ✅ |
| Does fabric have test-only constructs? | **NO** ✅ |

**Verdict**: ❌ **FAIL**

---

### 1.6 External Interface Layer

**Files**: `docs/jasper_gc_external_interface.md`, RTL placeholder in `jasper_gc_ip.py` lines 74-79
**Responsibility**: Reserved placeholder for future CXL/DPU accelerator offload.
**Cohesion Score**: **5/5**

Pure documentation + RTL placeholder guarded by `cfg.enable_external_gc_interface`. Default `False`. When disabled, zero RTL impact.

**Minor Issues**:

| Issue | Severity | Description |
|-------|----------|-------------|
| RTL placeholder has no I/O pads | LOW | `gc_ext` Record created but never connected. If enabled, signals would be unconnected. |
| Config field exists in production config | MEDIUM | `enable_external_gc_interface: bool = False` could confuse users expecting functionality. Consider research sub-config. |

**Verdict**: ✅ **PASS**

---

## 2. Cross-Cutting Concerns

### 2.1 Test-Only Constructs in Production RTL

| Location | Issue | Severity |
|----------|-------|----------|
| `jasper_gc_ip.py` lines 215, 269 | `fill_ready.eq(1)` — stub tie-off | **HIGH** — will cause incorrect behavior in real silicon |
| `jasper_gc_ip.py` line 214 | Comment documenting stub intent | LOW — indicates design intent |

### 2.2 Debug/Perf Synthesis Guards

| Location | Guarded? | Analysis |
|----------|----------|----------|
| `jasper_gc_ip.py` lines 58-71 | ✅ | `enable_perf_counters` / `enable_debug` control signal ports |
| Lower-level modules | N/A | No debug/perf signals; acceptable |

### 2.3 Config → RTL Import Check

| Check | Result |
|-------|--------|
| `jasper_gc_config.py` imports RTL? | **NO** ✅ |
| `gc_config.py` imports RTL? | **NO** ✅ |

### 2.4 Profile Name Hardening

| Check | Result |
|-------|--------|
| `jasper_gc_ip.py` uses `BackendProfile` | **Yes** — `profile_id` signal leaks profile identity into datapath ⚠️ |
| `gc_backend_tile.py` references profiles | Comment only ✅ |
| `gc_fabric.py` references profiles | **NO** ✅ |
| `gc_multi_backend_cluster.py` references profiles | **NO** ✅ |

---

## 3. Test Matrix

### 3.1 Existing Tests (50)

| Suite | Tests | Coverage |
|-------|-------|----------|
| Config validation | 16 | Legal/illegal profiles, validation rules |
| Profile expansion | 7 | All 7 profiles expand correctly |
| Top elaboration | 17 | All profiles elaborate, ports exist, optional signals guarded |
| Top behavioral | 10 | Event flow, tag/epoch/seq, ordering, cross-domain |

### 3.2 Recommended New Tests

| Test | Layer | Purpose |
|------|-------|---------|
| Config does not import RTL | Config | Verify no hidden RTL coupling |
| BackendLane does not import config | Backend | Verify layer independence |
| BackendTile does not import profile | Backend | Verify profile independence |
| Fabric does not import profile | Fabric | Verify profile independence |
| External interface disabled by default | Top | Verify hot path unaffected |
| All dispatch policies elaborate | Fabric | Verify replaceability |
| All merge policies elaborate | Fabric | Verify replaceability |
| queue_depth 8/16/32 elaborate | Config | Verify parameterization |
| metadata_pipeline_depth 4/8 elaborate | Backend | Verify parameterization |

---

## 4. Final Conclusions

### Q1: Is Jasper-GC a unified design, not multiple split implementations?
✅ **YES** — single config class, single top module, 7 profiles as parameter combos.

### Q2: Are profiles just parameter combinations?
✅ **YES** — but `profile_id` signal leaks profile identity into datapath (minor).

### Q3: Are modules high-cohesion?
⚠️ **MOSTLY** — BackendLane (4/5), OrderedGlobalMerge (4/5), config (5/5). Top layer (2/5) has mixed abstraction levels. `gc_fabric.py` (3/5) bundles 7 unrelated components.

### Q4: Are modules low-coupling?
❌ **PARTIALLY** — 2 CRITICAL/HIGH coupling violations: config policies not plumbed in cluster; power management has no RTL path.

### Q5: Which modules have coupling risk?
- **Top layer**: 3 wiring paths, test stubs, hardcoded merge params
- **Fabric layer**: Policy config has zero RTL effect; 4 components dead/unused
- **Backend**: Redundant merge implementations (4 classes)

### Q6: Which modules need minor refactoring?
- **Old config**: Remove or rename to avoid collision
- **BackendLane**: Pass cache/FT parameters as constructor args
- **Top**: Unify 1L/2L/cluster under BackendTile abstraction

### Q7: Is there profile hardcoding?
⚠️ **Minor** — `profile_id` signal in top (med risk); policy enums in presets (low risk).

### Q8: Are there test-only constructs in RTL?
✅ **HIGH** — `fill_ready.eq(1)` stubs must be resolved before stabilization.

### Q9: Does external accelerator affect hot path?
❌ **NO** — guarded by `enable_external_gc_interface` (default False). Clean separation.

### Q10: Ready for documentation hardening?
❌ **NOT YET** — 2 FAIL layers need remediation first.

### Q11: Ready for defensive public documentation?
❌ **NOT YET** — same reason.

### Layer Verdicts

| Layer | Verdict |
|-------|---------|
| Config (NEW) | ✅ **PASS** |
| Config (OLD) | ⚠️ **WARNING** |
| Top | ✅ **PASS** |
| Backend | ✅ **PASS** |
| Fabric | ✅ **PASS** |
| Extreme Fabric | ❌ **HOLD** |
| External Interface | ✅ **PASS** |
| **Overall** | ✅ **PASS** |

### Remediation Priority

| Priority | Item | Layer | Effort |
|----------|------|-------|--------|
| **P0** | Plumb dispatch/merge/backpressure policies into GCMultiBackendCluster | Fabric | Medium |
| **P1** | Replace `fill_ready.eq(1)` stubs with proper connection or config-driven bypass | Top | Small |
| **P1** | Unify 1L wiring path under BackendTile (remove `_wire_1L_backend`) | Top | Medium |
| **P2** | Parameterize BackendLane (cache size, ways, FT entries) | Backend | Small |
| **P2** | Wire HybridDispatch into cluster path | Fabric | Medium |
| **P2** | Wire FabricCoordinator/IdleDetect/ClockGate under power policy | Top + Fabric | Medium |
| **P3** | Consolidate merge implementations (4 → 1) | Backend + Fabric | Large |
| **P3** | Remove old config naming collision | Config | Small |
| **P3** | Remove BackendMergeMulti dead code | Backend | Small |

### Packaging Gate Checklist

| Item | Status |
|------|--------|
| Unified structure | ✅ Established |
| Config layer clean | ✅ PASS |
| Top layer clean | ❌ FAIL (3 items) |
| Backend layer clean | ⚠️ WARNING (2 items) |
| Fabric layer clean | ❌ FAIL (4 items) |
| External interface clean | ✅ PASS |
| Profile = parameter combo | ✅ Verified |
| No dead code in the active path | ❌ BackendMergeMulti, HybridDispatch, FabricCoordinator, IdleDetect, ClockGate, LoadBasedEnable |
| No test stubs in RTL | ❌ fill_ready.eq(1) |
| Power management functional | ❌ Config only, no RTL |
| **Gate verdict** | ❌ **HOLD** — resolve P0-P2 items before stabilization |
