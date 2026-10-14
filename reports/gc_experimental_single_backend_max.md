# Experimental Single Backend Max Throughput

## Current RTL (meta_drain=1.00, RTL validated)

**Exp Single max_stable:** 60% GC
**Standard baseline:** 60% GC
**Improvement:** 1.0× (same bottleneck)

| GC% | Steady | First Bottleneck |
|-----|--------|------------------|
| 5% | ✅ | none
| 10% | ✅ | none
| 15% | ✅ | none
| 20% | ✅ | none
| 25% | ✅ | none
| 30% | ✅ | none
| 35% | ✅ | none
| 40% | ✅ | none
| 45% | ✅ | none
| 50% | ✅ | none
| 55% | ✅ | none
| 60% | ✅ | none
| 65% | ❌ | event_pipeline
| 70% | ❌ | event_pipeline
| 75% | ❌ | event_pipeline
| 80% | ❌ | event_pipeline
| 85% | ❌ | event_pipeline
| 90% | ❌ | event_pipeline
| 95% | ❌ | event_pipeline
| 100% | ❌ | event_pipeline

## What-if (meta_drain sweep)

| meta_drain | max_stable | bottleneck shift | vs Standard |
|------------|------------|------------------|-------------|
| 0.20 evt/cyc | 25% GC | metadata_cache | 0.4× |
| 1.00 evt/cyc | 60% GC | none | 1.0× |
| 2.00 evt/cyc | 60% GC | none | 1.0× |
| 4.00 evt/cyc | 60% GC | none | 1.0× |

## Test Status

- test_gc_forwarding_table: PASS
- test_gc_metadata_pipeline: PASS
- test_gc_metadata_throughput: PASS
- test_gc_event_pipeline: PASS
- test_gc_event_throughput: PASS
- test_gc_l0_forwarding: PASS
- test_gc_slots_bank: PASS
- test_gc_backend_merge: PASS
- test_gc_heap_region: PASS
- test_gc_numa_ctrl: PASS
- test_gc_backend_config: PASS
- test_gc_backend_integration: PASS

## Methodology

- **Current RTL:** uses module drain rates as synthesized from actual RTL
- **What-if:** model only — assumes metadata can reach higher drain rates
- **Integrated RTL required:** cross-module continuous injection not yet tested
- All data is model estimate unless explicitly marked as RTL simulated