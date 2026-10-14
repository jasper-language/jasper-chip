# JasperGCConfig API Reference

> Date: 2026-06-07
> Source: `rtl/gc_config.py`

---

## Top-Level Config

```python
@dataclass
class JasperGCConfig:
    frontend:      GCFrontendConfig     # Frontend barrier params
    root_scan:     GCRootScanConfig      # Root scanning
    heap_walk:     GCHeapWalkConfig      # Heap traversal
    mark_sweep:    GCMarkSweepConfig     # Mark/sweep engine
    move:          GCMoveConfig          # Object move/forwarding
    backend:       GCBackendConfig       # Multi-backend / bank
    cycle:         GCCycleConfig         # GC cycle control
    memory_policy: GCMemoryPolicyConfig  # Cache/memory strategy
    debug:         GCDebugConfig         # Debug and perf counters
```

---

## GCFrontendConfig — Frontend Barrier Parameters

| Field | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `gc_slots` | int | 16 | 4–64 | Number of GC slots |
| `rb_cache_ways` | int | 4 | 1–16 | Remembered set cache associativity |
| `rb_slots` | int | 4 | 1–16 | Remembered set slots |
| `wb_depth` | int | 4 | 2–32 | Write barrier FIFO depth |
| `mv_depth` | int | 4 | 2–32 | Move barrier FIFO depth |
| `wb_ptr_filter` | int | 0 | 0/1 | Write barrier pointer filter enable |
| `wb_card_shift` | int | 6 | 4–12 | Card index shift (card size = 2^shift) |
| `wb_obj_shift` | int | 4 | 2–8 | Object index shift |
| `rb_mode` | int | 0 | 0–2 | Remembered set mode |

## GCRootScanConfig — Root Scan Parameters

| Field | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `root_fifo_depth` | int | 8 | 2–64 | Root pointer FIFO depth |
| `root_scan_width` | int | 1 | 1–4 | Parallel root scan width |
| `root_table_entries` | int | 256 | 32–4096 | Root table capacity |

## GCHeapWalkConfig — Heap Walk Parameters

| Field | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `heap_walk_slots` | int | 8 | 2–32 | Heap walk pipeline slots |
| `object_scan_width` | int | 2 | 1–8 | Parallel object field scan width |
| `trace_fifo_depth` | int | 8 | 2–32 | Trace FIFO depth |
| `mark_queue_depth` | int | 32 | 8–256 | Mark queue depth |
| `layout_cache_entries` | int | 16 | 4–64 | Object layout cache entries |
| `max_fields_per_object` | int | 16 | 4–64 | Max fields scanned per object |

## GCMarkSweepConfig — Mark/Sweep Parameters

| Field | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `card_table_size` | int | 16 | 4–64 | Card table sets |
| `card_table_ways` | int | 2 | 1–8 | Card table associativity |
| `card_index_mode` | int | 0 | 0–2 | Card indexing mode |
| `sweep_batch_size` | int | 4 | 1–16 | Sweep batch width |
| `sweep_entries` | int | 256 | 64–2048 | Sweep entry capacity |
| `sweep_fifo_depth` | int | 8 | 2–32 | Sweep result FIFO depth |
| `engine_latency` | int | 0 | 0–15 | Engine simulation latency |

## GCMoveConfig — Move/Forwarding Parameters

| Field | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `forward_table_entries` | int | 64 | 16–512 | Forwarding table entries |
| `forward_table_ways` | int | 4 | 1–8 | Forwarding table associativity |
| `forward_chase_limit` | int | 4 | 1–16 | Max forwarding chain length |
| `reloc_fifo_depth` | int | 8 | 2–32 | Relocation FIFO depth |
| `move_update_fifo_depth` | int | 8 | 2–32 | Move update FIFO depth |

## GCBackendConfig — Multi-Backend / Bank Configuration

| Field | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `scan_backend_count` | int | 1 | 1–8 | Parallel scan backends |
| `sweep_backend_count` | int | 1 | 1–8 | Parallel sweep backends |
| `move_backend_count` | int | 1 | 1–8 | Parallel move backends |
| `heap_walk_backend_count` | int | 1 | 1–8 | Parallel heap walk backends |
| `metadata_bank_count` | int | 1 | 1–8 | Metadata cache banks |
| `forwarding_bank_count` | int | 1 | 1–8 | Forwarding table banks |
| `slots_bank_count` | int | 1 | 1–8 | Slots bank count |
| `forwarding_table_impl` | str | "standard" | standard, banked_pipeline | Forwarding table implementation |
| `metadata_pipeline_impl` | str | "standard" | standard, pipelined | Metadata pipeline implementation |
| `slots_impl` | str | "standard" | standard, banked | Slots implementation |
| `forwarding_pipeline_stages` | int | 3 | 2–8 | Forwarding pipeline depth |
| `forwarding_dispatch_policy` | str | "round_robin" | round_robin, hash_lsb | Forwarding dispatch policy |
| `forwarding_merge_policy` | str | "ordered" | ordered, unordered | Forwarding merge policy |
| `backend_dispatch_policy` | str | "round_robin" | round_robin, hash_lsb, core_affinity | Backend dispatch policy |
| `backend_merge_policy` | str | "none" | none, ordered, unordered | Backend merge policy |

## GCCycleConfig — GC Cycle Control

| Field | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `enable_compact` | bool | True | — | Enable compaction phase |
| `enable_reloc` | bool | True | — | Enable relocation phase |
| `enable_incremental` | bool | False | — | Enable incremental GC |
| `max_steps` | int | 1000 | 100–10000 | Max GC steps per cycle |
| `safepoint_timeout` | int | 100 | 10–1000 | Safepoint wait timeout |

## GCMemoryPolicyConfig — Memory/Cache Policy

| Field | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `metadata_cache_enable` | bool | False | — | Enable metadata cache |
| `metadata_cache_size` | int | 2048 | 512–32768 | Metadata cache size (bytes) |
| `metadata_cache_ways` | int | 2 | 1–8 | Metadata cache associativity |
| `metadata_cache_line_size` | int | 64 | 32–128 | Cache line size (bytes) |
| `stream_buffer_enable` | bool | False | — | Enable stream buffer |
| `stream_buffer_entries` | int | 4 | 2–16 | Stream buffer entries |
| `stream_buffer_line_size` | int | 64 | 32–128 | Stream buffer line size |
| `stream_buffer_prefetch_distance` | int | 2 | 1–8 | Prefetch lookahead distance |
| `dcache_bypass_enable` | bool | True | — | Enable D-cache bypass |
| `bypass_gc_scan` | bool | True | — | Bypass D-cache for scan |
| `bypass_gc_sweep` | bool | True | — | Bypass D-cache for sweep |
| `bypass_gc_root` | bool | True | — | Bypass D-cache for root scan |
| `bypass_gc_object_walk` | bool | True | — | Bypass D-cache for object walk |
| `cache_partition_enable` | bool | False | — | Enable cache partitioning |
| `mutator_reserved_ways` | int | 6 | 1–15 | Ways reserved for mutator |
| `gc_reserved_ways` | int | 2 | 1–15 | Ways reserved for GC |
| `gc_no_fill_policy` | str | "bypass" | bypass, evict, nofill | Policy when GC misses |

## GCDebugConfig — Debug / Performance

| Field | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `debug` | bool | False | — | Internal debug signal enable |
| `perf_counters_enable` | bool | False | — | Performance counter enable |
| `trace_ports_enable` | bool | False | — | Trace output port enable |
| `debug_synthesis_guard` | bool | False | — | Synthesis guard for debug logic |
| `max_queue_watermark_enable` | bool | False | — | Queue watermark tracking |
| `engine_latency` | int | 0 | 0–15 | Engine simulation latency |
| `safepoint_timeout` | int | 100 | 10–1000 | Safepoint wait timeout |
| `max_steps` | int | 1000 | 100–10000 | Max GC steps per cycle |

---

## Profile Definitions

Three named profiles are defined in `rtl/gc_config.py`:

| Profile | Key Differences from Default |
|---------|------------------------------|
| `lite` | Minimized: gc_slots=8, rb_cache_ways=2, wb_depth=2, root_fifo_depth=4, mark_queue_depth=16, forward_table_entries=32, metadata_cache=disabled |
| `standard` | All defaults. Balanced area/performance. |
| `server` | Maximized: gc_slots=32, rb_cache_ways=8, wb_depth=16, root_fifo_depth=32, mark_queue_depth=128, forward_table_entries=256, metadata_cache=16 KB 4-way, multi-backend with hash_lsb dispatch |

Additional scan/sweep research profiles (`step30`, `step40_joint`, `step40_pareto1/2/3`) are defined in `rtl/gc_profile_params.py` for sweep parameter tuning studies.
