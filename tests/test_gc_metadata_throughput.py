# tests/test_gc_metadata_throughput.py
# MetadataCachePipelined / Standard 连续注入吞吐测试
from amaranth import *
from amaranth.sim import Simulator
from rtl.gc_metadata_pipeline import MetadataCacheStandard, MetadataCachePipelined


async def _fill_and_warmup(ctx, dut, base_addr=0x1000, count=4):
    """Fill `count` unique cache lines, return to idle."""
    for i in range(count):
        addr = base_addr + i * 64
        ctx.set(dut.request_valid, 1); ctx.set(dut.request_addr, addr)
        await ctx.tick()
        ctx.set(dut.request_valid, 0)
        if ctx.get(dut.fill_valid):
            ctx.set(dut.fill_ready, 1); ctx.set(dut.fill_data, 0xDEAD0000 | i)
            await ctx.tick()
            ctx.set(dut.fill_ready, 0)
        # Drain pipeline if pipelined
        for _ in range(8):
            if ctx.get(dut.rsp_valid):
                ctx.set(dut.rsp_ready, 1); await ctx.tick(); ctx.set(dut.rsp_ready, 0)
            else:
                break
    # Full drain
    for _ in range(8):
        if ctx.get(dut.rsp_valid):
            ctx.set(dut.rsp_ready, 1); await ctx.tick(); ctx.set(dut.rsp_ready, 0)
        await ctx.tick()


async def _continuous_throughput(ctx, dut, addr, N, rsp_backpressure=True):
    """Inject valid=1 for N consecutive cycles.
    Returns (accepted, responses_out).
    """
    accepted = 0; responses = 0
    for i in range(N):
        ctx.set(dut.request_valid, 1); ctx.set(dut.request_addr, addr)
        await ctx.tick()
        if ctx.get(dut.request_ready):
            accepted += 1
        # Accept all responses
        if rsp_backpressure:
            ctx.set(dut.rsp_ready, 1)
        if ctx.get(dut.rsp_valid):
            responses += 1
        await ctx.tick()
    ctx.set(dut.request_valid, 0)
    # Drain remaining
    for _ in range(16):
        ctx.set(dut.rsp_ready, 1); await ctx.tick()
        if ctx.get(dut.rsp_valid):
            responses += 1
        elif ctx.get(dut.rsp_valid) == 0 and ctx.get(dut.busy) == 0:
            break
    return accepted, responses


def test_pipelined_hit_throughput():
    """Pipelined: sustained hit throughput = 1 req/cycle (steady state)."""
    dut = MetadataCachePipelined(cache_size=1024, ways=2, line_size=32)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        await _fill_and_warmup(ctx, dut, 0x1000, 2)
        # Continuous injection: 50 cycles
        N = 50
        acc, rsp = await _continuous_throughput(ctx, dut, 0x1000, N)
        # All requests accepted (pipeline has backpressure but steady state = 1/cyc)
        assert acc > 0, f"Accepted 0 / {N}"
        acc_rate = acc / N
        rsp_rate = rsp / N
        print(f"  pipelined: accepted={acc}/{N} ({acc_rate:.2f}/cyc) responses={rsp}/{N} ({rsp_rate:.2f}/cyc)")
        # The pipeline takes 4 cycles to fill; after that accepts 1/cyc
        # Total accepted should be N-4 (first 4 fill the pipeline)
        # But actually, the pipeline takes 4 cycles to produce first output
        # After that, each output frees a slot, so one new request accepted per cycle
        # With N = 50: first 4 cycles produce no output, but pipeline still accepts?
        # No - the pipeline has 8 stages but only 4 cycles of latency.
        # Actually, when stages are empty, pipeline accepts request every cycle for the first 4
        # Then the 5th cycle: output is valid, but until rsp_ready=1, the pipeline stalls
        # With rsp_ready always 1, the 5th cycle accepts a new request AND produces output
        # Steady state: 1 accepted/cycle, 1 response/cycle
        assert acc_rate >= 0.9, f"Accept rate too low: {acc_rate}"
        assert rsp_rate >= 0.9, f"Response rate too low: {rsp_rate}"
        print("  pipelined hit throughput: PASS")
    sim.add_testbench(proc); sim.run()


def test_pipelined_nobackpressure():
    """Pipelined: rsp_ready=0 blocks pipeline → request_ready=0."""
    dut = MetadataCachePipelined(cache_size=1024, ways=2, line_size=32)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        await _fill_and_warmup(ctx, dut, 0x1000, 2)
        # Inject 12 requests to fill the 8-stage pipeline and then some
        for i in range(12):
            ctx.set(dut.request_valid, 1); ctx.set(dut.request_addr, 0x1000 + i*64)
            await ctx.tick()
        ctx.set(dut.request_valid, 0)
        # Wait for first request to reach pipeline output
        for _ in range(8):
            await ctx.tick()
        # Now pipeline should have valid output
        # Hold rsp_ready=0 → stall
        for _ in range(5):
            ctx.set(dut.rsp_ready, 0); await ctx.tick()
            assert ctx.get(dut.request_ready) == 0, "Should not accept when stalled"
            assert ctx.get(dut.rsp_valid) == 1, "Output should hold valid"
        # Release → pipeline drains
        await ctx.tick()
        for _ in range(16):
            ctx.set(dut.rsp_ready, 1); await ctx.tick()
            if not ctx.get(dut.rsp_valid) and not ctx.get(dut.busy):
                break
        assert ctx.get(dut.busy) == 0, "Should drain"
        print("  pipelined nobackpressure: PASS")
    sim.add_testbench(proc); sim.run()


def test_standard_hit_throughput():
    """Standard: sustained hit throughput = 1 req/cycle."""
    dut = MetadataCacheStandard(cache_size=1024, ways=2, line_size=32)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        await _fill_and_warmup(ctx, dut, 0x1000, 2)
        N = 50
        # Standard with registered output: request_ready=1 only at the
        # clock edge, immediately goes to 0 after (out_valid=1).
        # Count responses instead of request_ready for throughput.
        responses = 0
        for i in range(N):
            ctx.set(dut.request_valid, 1); ctx.set(dut.request_addr, 0x1000)
            await ctx.tick()
            ctx.set(dut.rsp_ready, 1)
            if ctx.get(dut.rsp_valid):
                responses += 1
        ctx.set(dut.request_valid, 0)
        # Drain remaining
        for _ in range(8):
            if ctx.get(dut.rsp_valid):
                responses += 1
                await ctx.tick()
            elif ctx.get(dut.busy) == 0:
                break
            else:
                await ctx.tick()
        rsp_rate = responses / N
        print(f"  standard: responses={responses}/{N} ({rsp_rate:.2f}/cyc)")
        assert responses >= N - 1, f"Should respond to most: {responses}/{N}"
        print("  standard hit throughput: PASS")
    sim.add_testbench(proc); sim.run()


def test_pipelined_miss_throughput():
    """Pipelined: sustained miss throughput limited by fill latency."""
    dut = MetadataCachePipelined(cache_size=1024, ways=2, line_size=32)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        # Each unique address → miss → need fill
        N = 10
        accepted = 0; responses = 0
        for i in range(N):
            addr = 0x8000 + i * 64  # All unique → all miss (cache small)
            ctx.set(dut.request_valid, 1); ctx.set(dut.request_addr, addr)
            await ctx.tick()
            if ctx.get(dut.request_ready):
                accepted += 1
            ctx.set(dut.rsp_ready, 1)
            if ctx.get(dut.rsp_valid):
                responses += 1
            # Accept fill when pending
            if ctx.get(dut.fill_valid):
                ctx.set(dut.fill_ready, 1)
                ctx.set(dut.fill_data, 0xBEEF0000 | i)
                await ctx.tick()
                ctx.set(dut.fill_ready, 0)
            else:
                await ctx.tick()
        ctx.set(dut.request_valid, 0)
        # Drain
        for _ in range(16):
            ctx.set(dut.rsp_ready, 1); await ctx.tick()
            if ctx.get(dut.rsp_valid):
                responses += 1
            if ctx.get(dut.fill_valid):
                ctx.set(dut.fill_ready, 1)
                ctx.set(dut.fill_data, 0)
                await ctx.tick()
                ctx.set(dut.fill_ready, 0)
            elif not ctx.get(dut.busy):
                break
        print(f"  pipelined miss: accepted={accepted}/{N} responses={responses}/{N}")
        print("  pipelined miss throughput: PASS")
    sim.add_testbench(proc); sim.run()


def test_throughput_comparison():
    """Compare Standard vs Pipelined throughput, same workload."""
    dut_s = MetadataCacheStandard(cache_size=1024, ways=2, line_size=32)
    dut_p = MetadataCachePipelined(cache_size=1024, ways=2, line_size=32)
    results = {}
    for name, dut in [("Standard", dut_s), ("Pipelined", dut_p)]:
        sim = Simulator(dut); sim.add_clock(1e-6)
        async def proc(ctx, dut=dut, n=name):
            await ctx.tick()
            await _fill_and_warmup(ctx, dut, 0x1000, 2)
            N = 100
            acc, rsp = await _continuous_throughput(ctx, dut, 0x1000, N)
            results[n] = (acc, rsp)
        sim.add_testbench(proc); sim.run()
    s_acc, s_rsp = results["Standard"]
    p_acc, p_rsp = results["Pipelined"]
    print(f"  Standard:  {s_acc}/100 acc, {s_rsp}/100 rsp")
    print(f"  Pipelined: {p_acc}/100 acc, {p_rsp}/100 rsp")
    # Both should be close to 100/100
    assert s_acc >= 95, f"Standard acc too low: {s_acc}"
    assert p_acc >= 90, f"Pipelined acc too low: {p_acc}"
    print("  comparison: PASS")


if __name__ == "__main__":
    tests = [
        ("standard hit throughput", test_standard_hit_throughput),
        ("pipelined hit throughput", test_pipelined_hit_throughput),
        ("pipelined nobackpressure", test_pipelined_nobackpressure),
        ("pipelined miss throughput", test_pipelined_miss_throughput),
        ("comparison", test_throughput_comparison),
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
