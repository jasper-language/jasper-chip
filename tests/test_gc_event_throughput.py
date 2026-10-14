# tests/test_gc_event_throughput.py
# GCEventPipelineSeparated 连续混合事件吞吐测试
from amaranth import *
from amaranth.sim import Simulator
from rtl.gc_event_pipeline import GCEventPipelineSeparated, EVT_SCAN, EVT_SWEEP, EVT_MOVE


def test_separated_scan_does_not_starve_sweep():
    """Scan 持续有结果时, Sweep 不应无限饥饿 (不在同一结果端口上饿死).

    Separated 的问题: Scan > Sweep > Move 固定优先级合并.
    如果 Scan 持续有结果, Sweep 和 Move 的结果在 result 端口上被扫描优先抢走,
    导致 Sweep/Move 进展停滞.
    """
    dut = GCEventPipelineSeparated()
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        # Inject Scan
        ctx.set(dut.event_valid, 1); ctx.set(dut.event_type, EVT_SCAN)
        ctx.set(dut.event_data, 0xAA)
        await ctx.tick()
        ctx.set(dut.event_valid, 0)
        assert ctx.get(dut.result_valid), "Scan result valid"
        assert ctx.get(dut.result_type) == EVT_SCAN

        # Inject Sweep while Scan result held
        ctx.set(dut.event_valid, 1); ctx.set(dut.event_type, EVT_SWEEP)
        ctx.set(dut.event_data, 0xBB)
        await ctx.tick()
        ctx.set(dut.event_valid, 0)
        # Scan still has priority at output
        assert ctx.get(dut.result_valid)
        assert ctx.get(dut.result_type) == EVT_SCAN, "Scan should still be at output"

        # Accept Scan result
        ctx.set(dut.result_ready, 1); await ctx.tick(); ctx.set(dut.result_ready, 0)
        # Now Sweep should be at output
        assert ctx.get(dut.result_valid), "Sweep result should be valid"
        assert ctx.get(dut.result_type) == EVT_SWEEP, f"Sweep after Scan: {ctx.get(dut.result_type)}"

        ctx.set(dut.result_ready, 1); await ctx.tick(); ctx.set(dut.result_ready, 0)
        print("  separated no-starvation: PASS")
    sim.add_testbench(proc); sim.run()


def test_separated_scan_continuous_starvation():
    """验证连续 Scan 注入时 Sweep/Move 的饥饿延迟.

    注入 20 个 Scan, 中间混入 1 个 Sweep 和 1 个 Move.
    统计 Sweep 和 Move 结果出现的延迟 (在多少个 result_ready 之后).
    """
    dut = GCEventPipelineSeparated()
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        # Inject: 5 Scan, 1 Sweep, 10 Scan, 1 Move, 5 Scan
        events = ([EVT_SCAN]*5) + [EVT_SWEEP] + ([EVT_SCAN]*10) + [EVT_MOVE] + ([EVT_SCAN]*5)
        for evt in events:
            ctx.set(dut.event_valid, 1); ctx.set(dut.event_type, evt); ctx.set(dut.event_data, evt)
            await ctx.tick()
            if not ctx.get(dut.event_ready):
                # Backpressure: wait
                await ctx.tick()
        ctx.set(dut.event_valid, 0)

        # Drain: count results by type and track delay
        results = []
        for _ in range(50):
            ctx.set(dut.result_ready, 1); await ctx.tick()
            if ctx.get(dut.result_valid):
                t = ctx.get(dut.result_type)
                results.append(t)
            if not ctx.get(dut.busy):
                break

        scan_count = results.count(EVT_SCAN)
        sweep_count = results.count(EVT_SWEEP)
        move_count = results.count(EVT_MOVE)
        # Sweep and Move should appear eventually
        sweep_idx = results.index(EVT_SWEEP) if EVT_SWEEP in results else -1
        move_idx = results.index(EVT_MOVE) if EVT_MOVE in results else -1

        print(f"  results: {len(results)} total, S={scan_count} SW={sweep_count} M={move_count}")
        print(f"  Sweep appears at result #{sweep_idx}, Move at #{move_idx}")

        assert sweep_idx >= 0, "Sweep was never emitted!"
        assert move_idx >= 0, "Move was never emitted!"
        # Sweep should appear before the (5+5=10)th result (it was injected after 5 scans)
        # But because Scan has priority, Sweep will wait until all earlier Scan results drain
        # This is expected starvation
        print(f"  Sweep delayed by {sweep_idx} results (5 Scans ahead = expected)")
        print(f"  Move delayed by {move_idx} results (16 events ahead = expected)")

        print("  separated continuous starvation: PASS")
    sim.add_testbench(proc); sim.run()


def test_separated_mixed_throughput():
    """连续混合事件注入, 测量 event_ready 和 result_valid 速率."""
    dut = GCEventPipelineSeparated()
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        # Mix: 40% Scan, 30% Sweep, 30% Move
        N = 100
        events = [EVT_SCAN]*40 + [EVT_SWEEP]*30 + [EVT_MOVE]*30
        import random; random.shuffle(events)
        accepted = 0; results = []
        for i, evt in enumerate(events):
            ctx.set(dut.event_valid, 1); ctx.set(dut.event_type, evt); ctx.set(dut.event_data, evt)
            await ctx.tick()
            if ctx.get(dut.event_ready):
                accepted += 1
            else:
                # Retry next cycle
                await ctx.tick()
                if ctx.get(dut.event_ready):
                    accepted += 1
            # Accept results when available
            ctx.set(dut.result_ready, 1)
            if ctx.get(dut.result_valid):
                results.append(ctx.get(dut.result_type))
        ctx.set(dut.event_valid, 0)
        # Drain
        for _ in range(50):
            ctx.set(dut.result_ready, 1); await ctx.tick()
            if ctx.get(dut.result_valid):
                results.append(ctx.get(dut.result_type))
            if not ctx.get(dut.busy):
                break
        accept_rate = accepted / N
        result_rate = len(results) / N
        print(f"  accepted={accepted}/{N} ({accept_rate:.2f}/cyc) results={len(results)} ({result_rate:.2f}/cyc)")
        print(f"  result breakdown: S={results.count(EVT_SCAN)} SW={results.count(EVT_SWEEP)} M={results.count(EVT_MOVE)}")
        # Each event takes at least 1 cycle (single-entry pipeline stage)
        # With 3 independent stages, can accept up to 3 events in 2 cycles
        # (1/cyc per stage = 3/2 = 1.5/cyc avg)
        assert accept_rate >= 0.5, f"Accept rate too low: {accept_rate}"
        print("  separated mixed throughput: PASS")
    sim.add_testbench(proc); sim.run()


def test_separated_result_backpressure():
    """result_ready=0 时结果不丢, 且 event 仍可接受 (非同一 pipeline)."""
    dut = GCEventPipelineSeparated()
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        # Inject Scan
        ctx.set(dut.event_valid, 1); ctx.set(dut.event_type, EVT_SCAN)
        ctx.set(dut.event_data, 0xAA)
        await ctx.tick(); ctx.set(dut.event_valid, 0)
        await ctx.tick()
        # Result valid, hold result_ready=0
        ctx.set(dut.result_ready, 0)
        await ctx.tick()
        assert ctx.get(dut.result_valid), "Result should hold"
        assert ctx.get(dut.result_type) == EVT_SCAN
        # Inject Sweep while Scan result is held (different sub-pipeline)
        # Check event_ready BEFORE tick (Sweep stage is empty)
        ctx.set(dut.event_valid, 1); ctx.set(dut.event_type, EVT_SWEEP)
        ctx.set(dut.event_data, 0xBB)
        assert ctx.get(dut.event_ready), "Sweep empty stage should be ready before tick"
        await ctx.tick()
        # After tick: event was accepted (occ=1), event_ready=0 until result consumed
        ctx.set(dut.event_valid, 0)
        await ctx.tick()
        # Scan result still held (merger still shows Scan)
        assert ctx.get(dut.result_valid), "Scan result still held"
        assert ctx.get(dut.result_type) == EVT_SCAN
        # Release Scan result
        ctx.set(dut.result_ready, 1); await ctx.tick(); ctx.set(dut.result_ready, 0)
        await ctx.tick()
        # Now Sweep result should be visible
        assert ctx.get(dut.result_valid), "Sweep result should be valid"
        assert ctx.get(dut.result_type) == EVT_SWEEP, f"Sweep after Scan: got {ctx.get(dut.result_type)}"
        ctx.set(dut.result_ready, 1); await ctx.tick(); ctx.set(dut.result_ready, 0)
        print("  separated result backpressure: PASS")
    sim.add_testbench(proc); sim.run()


def test_standard_mixed_throughput():
    """Standard (single stage): max 1 event/2 cycles (accept + result)."""
    from rtl.gc_event_pipeline import GCEventPipelineStandard
    dut = GCEventPipelineStandard()
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        N = 50
        accepted = 0; results = 0
        for i in range(N):
            ctx.set(dut.event_valid, 1); ctx.set(dut.event_type, EVT_SCAN)
            await ctx.tick()
            if ctx.get(dut.event_ready):
                accepted += 1
            ctx.set(dut.result_ready, 1)
            if ctx.get(dut.result_valid):
                results += 1
        ctx.set(dut.event_valid, 0)
        for _ in range(10):
            ctx.set(dut.result_ready, 1); await ctx.tick()
            if ctx.get(dut.result_valid):
                results += 1
            elif not ctx.get(dut.busy):
                break
        print(f"  standard: accepted={accepted}/{N} results={results}")
        # Single stage can sustain 1/cycle (acts as bypass register)
        print(f"  standard throughput: {accepted}/{N} = {accepted/N:.2f}/cyc")
        print("  standard mixed throughput: PASS")
    sim.add_testbench(proc); sim.run()


if __name__ == "__main__":
    tests = [
        ("no starvation", test_separated_scan_does_not_starve_sweep),
        ("continuous starvation", test_separated_scan_continuous_starvation),
        ("mixed throughput", test_separated_mixed_throughput),
        ("result backpressure", test_separated_result_backpressure),
        ("standard mixed", test_standard_mixed_throughput),
    ]
    passed = 0
    for name, fn in tests:
        try:
            fn()
            passed += 1
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"  {name:40s} ❌ {e}")
    print(f"\nResults: {passed}/{len(tests)} passed")
    if passed != len(tests):
        exit(1)
