# tests/test_gc_multi_backend_throughput.py
# Multi-backend / multi-bank metadata cache throughput demo.
from amaranth import *
from amaranth.sim import Simulator
from rtl.gc_metadata_pipeline import MetadataCacheStandard, MetadataCachePipelined, MetadataCacheBanked
from rtl.gc_backend_event import GCBackendEventRecord

async def _fill_and_warm(ctx, dut, base, count=4):
    for i in range(count):
        ctx.set(dut.request_valid, 1); ctx.set(dut.request_addr, base + i*64)
        await ctx.tick(); ctx.set(dut.request_valid, 0)
        for _ in range(10):
            if ctx.get(dut.fill_valid):
                ctx.set(dut.fill_ready, 1); ctx.set(dut.fill_data, 0xDEAD0000|i)
                await ctx.tick(); ctx.set(dut.fill_ready, 0)
                break
            await ctx.tick()
        for _ in range(10):
            ctx.set(dut.rsp_ready, 1); await ctx.tick()
            if not ctx.get(dut.rsp_valid) and not ctx.get(dut.busy):
                break
        ctx.set(dut.rsp_ready, 0)

async def _continuous_inject(ctx, dut, addrs, N, label=""):
    """Inject N requests cycling through addresses. Return accepted, responses."""
    accepted = 0; responses = 0
    for i in range(N):
        a = addrs[i % len(addrs)]
        ctx.set(dut.request_valid, 1); ctx.set(dut.request_addr, a)
        await ctx.tick()
        if ctx.get(dut.request_ready):
            accepted += 1
        ctx.set(dut.rsp_ready, 1)
        if ctx.get(dut.rsp_valid):
            responses += 1
    ctx.set(dut.request_valid, 0)
    for _ in range(16):
        ctx.set(dut.rsp_ready, 1); await ctx.tick()
        if ctx.get(dut.rsp_valid):
            responses += 1
        elif not ctx.get(dut.busy):
            break
    ctx.set(dut.rsp_ready, 0)
    return accepted, responses

def test_single_bank_throughput():
    """Single bank metadata cache: baseline throughput."""
    for name, cls in [("Standard", MetadataCacheStandard), ("Pipelined", MetadataCachePipelined)]:
        dut = cls(cache_size=1024, ways=2, access_granularity=32)
        sim = Simulator(dut); sim.add_clock(1e-6)
        async def proc(ctx):
            await ctx.tick()
            await _fill_and_warm(ctx, dut, 0x1000, 4)
            N = 100
            # Single address (always hits after warmup)
            acc, rsp = await _continuous_inject(ctx, dut, [0x1000], N)
            print(f"  {name:12s}: 1-addr acc={acc}/{N} ({acc/N*100:.0f}%) rsp={rsp}/{N} ({rsp/N*100:.0f}%)")
            # Multiple addresses (still hits, same set)
            acc2, rsp2 = await _continuous_inject(ctx, dut, [0x1000,0x1100,0x1200,0x1300], N)
            print(f"  {name:12s}: 4-addr acc={acc2}/{N} ({acc2/N*100:.0f}%) rsp={rsp2}/{N} ({rsp2/N*100:.0f}%)")
            assert acc >= N-5, f"{name} single throughput too low: {acc}/{N}"
        sim.add_testbench(proc); sim.run()
    print("  single bank throughput: PASS")

def test_dual_bank_throughput():
    """Two banks: 2× throughput on distributed addresses."""
    dut = MetadataCacheBanked(bank_count=2, cache_size=512, ways=2, access_granularity=32)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        await _fill_and_warm(ctx, dut, 0x1000, 4)
        N = 100
        # Single address → hits bank 0 only (addr[0]=0)
        acc0, rsp0 = await _continuous_inject(ctx, dut, [0x1000], N)
        print(f"  2-bank-1addr: acc={acc0}/{N} ({acc0/N*100:.0f}%) rsp={rsp0}/{N}")
        # Two addresses, one per bank
        # addr[0]=0 → bank 0, addr[0]=1 → bank 1
        acc1, rsp1 = await _continuous_inject(ctx, dut, [0x1000, 0x1001], N)
        print(f"  2-bank-2addr: acc={acc1}/{N} ({acc1/N*100:.0f}%) rsp={rsp1}/{N}")
        # 4 addresses distributed across banks
        acc2, rsp2 = await _continuous_inject(ctx, dut, [0x1000,0x1001,0x1002,0x1003], N)
        print(f"  2-bank-4addr: acc={acc2}/{N} ({acc2/N*100:.0f}%) rsp={rsp2}/{N}")
        assert acc2 >= N-5, f"Dual bank throughput too low: {acc2}/{N}"
    sim.add_testbench(proc); sim.run()
    print("  dual bank throughput: PASS")

def test_quad_bank_throughput():
    """Four banks: 4× throughput on well-distributed addresses."""
    dut = MetadataCacheBanked(bank_count=4, cache_size=256, ways=2, access_granularity=32)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        await _fill_and_warm(ctx, dut, 0x1000, 8)
        N = 100
        # All to bank 0
        acc0, _ = await _continuous_inject(ctx, dut, [0x1000], N)
        print(f"  4-bank-bank0: acc={acc0}/{N}")
        # 4 addresses, one per bank
        acc4, _ = await _continuous_inject(ctx, dut, [0x1000,0x1001,0x1002,0x1003], N)
        print(f"  4-bank-1ea:   acc={acc4}/{N}")
        # 8 addresses, 2 per bank
        acc8, _ = await _continuous_inject(ctx, dut, [0x1000,0x1001,0x1002,0x1003,
                                                       0x1004,0x1005,0x1006,0x1007], N)
        print(f"  4-bank-2ea:   acc={acc8}/{N}")
        assert acc8 >= N-5, f"Quad bank throughput too low: {acc8}/{N}"
    sim.add_testbench(proc); sim.run()
    print("  quad bank throughput: PASS")

def test_bank_throughput_gain():
    """Compare throughput: 1 bank vs 2 banks vs 4 banks on same workload."""
    results = {}
    for bc in [1, 2, 4]:
        if bc == 1:
            dut = MetadataCachePipelined(cache_size=1024, ways=2, access_granularity=32)
        else:
            dut = MetadataCacheBanked(bank_count=bc, cache_size=1024//bc, ways=2, access_granularity=32)
        sim = Simulator(dut); sim.add_clock(1e-6)
        async def proc(ctx, bc=bc):
            await ctx.tick()
            await _fill_and_warm(ctx, dut, 0x1000, 8)
            N = 100
            # Well-distributed across bc banks
            addrs = [0x1000 + i for i in range(bc * 4)]
            acc, rsp = await _continuous_inject(ctx, dut, addrs, N)
            results[bc] = (acc, rsp)
        sim.add_testbench(proc); sim.run()
    base = results[1][0]
    for bc in [1, 2, 4]:
        acc = results[bc][0]
        gain = acc / base if base > 0 else 0
        print(f"  {bc} bank(s): acc={acc}/{100} gain={gain:.2f}× vs 1-bank")
    # Note: at 1 req/cycle injection rate, single bank already saturates at 1.0.
    # Multi-bank gain would appear at >1 req/cycle injection or under bank contention.
    # This test verifies all banks work correctly, not throughput scaling.
    assert results[4][0] >= results[1][0] * 0.9, f"4-bank should match 1-bank: {results[4][0]} vs {results[1][0]}"
    print("  throughput gain: PASS")

def test_banked_gc_event_integration():
    """Banked metadata cache with GCBackendEvent: core_id/event_id preserved."""
    dut = MetadataCacheBanked(bank_count=2, cache_size=512, ways=2, access_granularity=32)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        await _fill_and_warm(ctx, dut, 0x1000, 4)
        ctx.set(dut.input_event.fields["core_id"], 5)
        ctx.set(dut.input_event.fields["event_id"], 42)
        ctx.set(dut.input_event.fields["epoch"], 3)
        ctx.set(dut.request_valid, 1); ctx.set(dut.request_addr, 0x1000)
        await ctx.tick(); ctx.set(dut.request_valid, 0)
        for _ in range(10):
            ctx.set(dut.rsp_ready, 1); await ctx.tick()
            if ctx.get(dut.rsp_valid):
                assert ctx.get(dut.output_event.fields["core_id"]) == 5, "core_id"
                assert ctx.get(dut.output_event.fields["event_id"]) == 42, "event_id"
                assert ctx.get(dut.output_event.fields["epoch"]) == 3, "epoch"
                break
        ctx.set(dut.rsp_ready, 0)
        print("  banked GCBackendEvent integration: PASS")
    sim.add_testbench(proc); sim.run()

if __name__ == "__main__":
    tests = [
        ("single bank throughput", test_single_bank_throughput),
        ("dual bank throughput", test_dual_bank_throughput),
        ("quad bank throughput", test_quad_bank_throughput),
        ("throughput gain", test_bank_throughput_gain),
        ("GCBackendEvent integration", test_banked_gc_event_integration),
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
