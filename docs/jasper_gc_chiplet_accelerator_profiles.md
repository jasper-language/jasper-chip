# Jasper-GC Chiplet Accelerator Profiles

> Date: 2026-06-07  
> Status: ARCHITECTURE  

---

## Profile Overview

| Profile | Tasks | Queue Depth | Region Count | Coherency | Adapter | Status |
|---------|-------|-------------|--------------|-----------|---------|--------|
| chiplet_accel_standard | scan, sweep, rebuild | 8 | 2 | Coherent | Chiplet | **ARCHITECTURE** |
| chiplet_accel_server | +compact, relocate, clean | 16 | 4 | Coherent | Chiplet | **MAINLINE_STUDY** |
| chiplet_accel_extreme | +large object, multi-region | 32 | 8+ | Coherent+HBM | Chiplet | **HOLD** |

---

## chiplet_accel_standard

| Field | Value |
|-------|-------|
| Profile ID | `chiplet_accel_standard` |
| Status | **ARCHITECTURE / RTL_PLANNING** |
| Adapter | CPU-package / chiplet (coherent) |
| Command queue depth | 8 |
| Completion queue depth | 8 |
| Max outstanding commands | 4 |
| Region count | 2 |
| Max region size | 256 MB |
| Coherency | Required |
| Enable debug | Optional |
| Enable perf counters | Optional |

### Supported Commands

| Type | Support |
|------|---------|
| SCAN_REGION | ✅ Required |
| SWEEP_REGION | ✅ Required |
| COMPACT_REGION | ❌ Not supported |
| REBUILD_METADATA | ✅ Required |
| CLEAN_REMEMBERED_SET | ❌ Not supported |
| PREFETCH_METADATA | ⚠️ Optional |
| RELOCATE_COLD_OBJECTS | ❌ Not supported |
| LARGE_OBJECT_MOVE | ❌ Not supported |
| BACKGROUND_GC_PHASE | ❌ Not supported |

### Core Compatibility

| Core Profile | Accelerator Recommended? |
|-------------|--------------------------|
| Standard+ | ✅ Optional |
| Gateway | ✅ Optional |
| Server Base | ⚠️ May benefit |
| Server | ⚠️ Prefer chiplet_accel_server |

---

## chiplet_accel_server

| Field | Value |
|-------|-------|
| Profile ID | `chiplet_accel_server` |
| Status | **MAINLINE_STUDY** |
| Adapter | CPU-package / chiplet (coherent) |
| Command queue depth | 16 |
| Completion queue depth | 16 |
| Max outstanding commands | 8 |
| Region count | 4 |
| Coherency | Required |

### Supported Commands

| Type | Support |
|------|---------|
| SCAN_REGION | ✅ Required |
| SWEEP_REGION | ✅ Required |
| COMPACT_REGION | ✅ Required |
| REBUILD_METADATA | ✅ Required |
| CLEAN_REMEMBERED_SET | ✅ Required |
| PREFETCH_METADATA | ⚠️ Optional |
| RELOCATE_COLD_OBJECTS | ✅ Required |
| LARGE_OBJECT_MOVE | ❌ Not supported |
| BACKGROUND_GC_PHASE | ⚠️ Optional |

### Core Compatibility

| Core Profile | Accelerator Recommended? |
|-------------|--------------------------|
| Server Base | ✅ Recommended |
| Server | ✅ Recommended |
| Extreme | ⚠️ Prefer chiplet_accel_extreme |

---

## chiplet_accel_extreme

| Field | Value |
|-------|-------|
| Profile ID | `chiplet_accel_extreme` |
| Status | **HOLD / RESEARCH** |
| Adapter | Chiplet + HBM-aware |
| Command queue depth | 32 |
| Completion queue depth | 32 |
| Max outstanding commands | 16 |
| Region count | 8+ |
| Coherency | Required (HBM) |

### Supported Commands

| Type | Support |
|------|---------|
| SCAN_REGION | ✅ (multi-region parallel) |
| SWEEP_REGION | ✅ (multi-region parallel) |
| COMPACT_REGION | ✅ (multi-region) |
| REBUILD_METADATA | ✅ (large metadata) |
| CLEAN_REMEMBERED_SET | ✅ (large remembered set) |
| PREFETCH_METADATA | ✅ Required |
| RELOCATE_COLD_OBJECTS | ✅ (multi-region) |
| LARGE_OBJECT_MOVE | ✅ Required |
| BACKGROUND_GC_PHASE | ✅ Required |

### Core Compatibility

| Core Profile | Accelerator Recommended? |
|-------------|--------------------------|
| Extreme | ✅ Required for peak performance |
| Server | ❌ Overprovisioned |

---

## MCU / Lite

MCU and Lite Core profiles do **NOT** include any accelerator.

No chiplet accelerator is defined for MCU/Lite. GC pressure is low;
area and power are the primary optimization goals.
