# 3-Engine MemoryStress Report

> Date: 2026-06-07

## Arbiter Stress (7/7 PASS)

| Test | Status | Description |
|------|--------|-------------|
| mre_beats_sweep_beats_scan | ✅ PASS | MRE > SWEEP > SCAN priority |
| sweep_beats_scan_when_mre_idle | ✅ PASS | SWEEP > SCAN when MRE idle |
| scan_alone | ✅ PASS | SCAN alone accepted |
| outstanding_blocks_all | ✅ PASS | All blocked while one outstanding |
| response_hold_under_backpressure | ✅ PASS | Response held when rsp_ready=0 |
| response_route_correct | ✅ PASS | Each engine gets its own response |
| tag_set_equality | ✅ PASS | Accepted == response tags |

## Top-level 3-Engine Memory Stress (7/7 PASS)

| Test | Status | Description |
|------|--------|-------------|
| scan_alone | ✅ PASS | SCAN memory mode |
| sweep_alone | ✅ PASS | SWEEP memory mode |
| rebuild_alone | ✅ PASS | REBUILD memory mode |
| three_mixed | ✅ PASS | SCAN+SWEEP+REBUILD all complete |
| mixed_burst_6 | ✅ PASS | 6 mixed commands all drain |
| epoch_preserved | ✅ PASS | Epoch unchanged through MemoryAccess |
| counting_mode_backward | ✅ PASS | enable_memory=False still works |

## Key Metrics

| Metric | Value |
|--------|-------|
| total_tests | 162 |
| passed | 162 |
| failed | 0 |
| arbiter priority | mre > sweep > scan |
| outstanding mode | global single-outstanding |
| response routing | out_engine register (0/1/2) |
| multi-outstanding | FUTURE |
| Compact memory | NOT integrated (counting only) |

## Known Bottlenecks

1. **Global single-outstanding**: Only 1 memory request in flight at a time.
   - All 3 engines serialize on MemoryAccess
   - Next phase: multi-outstanding or per-engine MemoryAccess
2. **Single CompletionQueue**: All engine completions share one queue
3. **Counting engines**: No real memory access or data-plane throughput
4. **Compact not memory-integrated**: Counting mode only

## Next Phase

- Compact memory integration (counting → memory mode)
- Multi-outstanding arbiter or per-engine MemoryAccess
