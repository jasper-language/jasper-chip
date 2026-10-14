# tests/test_gc_metadata_pipeline.py — MetadataCache 单元测试
from amaranth import *
from amaranth.sim import Simulator
from amaranth.back import rtlil
from rtl.gc_metadata_pipeline import (
    MetadataCacheStandard, MetadataCachePipelined, create_metadata_cache,
)
import sys

def _sim(dut):
    s = Simulator(dut); s.add_clock(1e-6); return s

async def _fill(ctx, dut, addr, data):
    """Inject a request, handle fill."""
    ctx.set(dut.request_valid, 1); ctx.set(dut.request_addr, addr)
    await ctx.tick(); ctx.set(dut.request_valid, 0)
    if ctx.get(dut.fill_valid):
        ctx.set(dut.fill_ready, 1); ctx.set(dut.fill_data, data); await ctx.tick()
        ctx.set(dut.fill_ready, 0)
        await ctx.tick()
    if ctx.get(dut.rsp_valid):
        ctx.set(dut.rsp_ready, 1); await ctx.tick(); ctx.set(dut.rsp_ready, 0)

async def _drain(ctx, dut):
    """Accept all remaining responses."""
    for _ in range(8):
        ctx.set(dut.rsp_ready, 1); await ctx.tick()
        if not ctx.get(dut.rsp_valid) and not ctx.get(dut.busy):
            break
    ctx.set(dut.rsp_ready, 0)

# ── 1. Factory ─────────────────────────────────────────────────
def test_factory():
    create_metadata_cache("standard")
    create_metadata_cache("pipelined")
    try:
        create_metadata_cache("invalid")
        assert False
    except ValueError:
        pass
    print("  factory: PASS")
    return True

# ── 2. Elaboration ─────────────────────────────────────────────
def test_elaboration():
    for name, cls in [("Standard", MetadataCacheStandard), ("Pipelined", MetadataCachePipelined)]:
        m = Module()
        m.submodules.dut = cls(cache_size=1024, ways=2, access_granularity=32)
        o = rtlil.convert(m, ports=[])
        assert len(o) > 0, f"{name} elaboration failed"
    print("  elaboration: PASS")
    return True

# ── 3. Standard: hit/miss/fill ─────────────────────────────────
def test_standard_hit_miss_fill():
    dut = MetadataCacheStandard(cache_size=1024, ways=2, access_granularity=32)
    sim = _sim(dut)
    async def proc(ctx):
        await ctx.tick()
        await _fill(ctx, dut, 0x1000, 0xdeadbeef)
        ctx.set(dut.request_valid, 1); ctx.set(dut.request_addr, 0x1000)
        await ctx.tick(); ctx.set(dut.request_valid, 0)
        await ctx.tick()
        assert ctx.get(dut.rsp_hit) == 1, "std re-hit"
        assert ctx.get(dut.rsp_data) == 0xdeadbeef
        ctx.set(dut.rsp_ready, 1); await ctx.tick(); ctx.set(dut.rsp_ready, 0)
        await _fill(ctx, dut, 0x2000, 0x12345678)
        ctx.set(dut.request_valid, 1); ctx.set(dut.request_addr, 0x2000)
        await ctx.tick(); ctx.set(dut.request_valid, 0)
        await ctx.tick()
        assert ctx.get(dut.rsp_hit) == 1
        assert ctx.get(dut.rsp_data) == 0x12345678
        ctx.set(dut.rsp_ready, 1); await ctx.tick(); ctx.set(dut.rsp_ready, 0)
        await _drain(ctx, dut)
        print("  standard hit/miss/fill: PASS")
    sim.add_testbench(proc); sim.run()
    return True

# ── 4. Standard: update ───────────────────────────────────────
def test_standard_update():
    dut = MetadataCacheStandard(cache_size=1024, ways=2, access_granularity=32)
    sim = _sim(dut)
    async def proc(ctx):
        await ctx.tick()
        await _fill(ctx, dut, 0x1000, 0xAAAA)
        await _fill(ctx, dut, 0x1200, 0xBBBB)
        ctx.set(dut.request_valid, 1); ctx.set(dut.request_addr, 0x1000)
        await ctx.tick(); ctx.set(dut.request_valid, 0)
        await ctx.tick()
        assert ctx.get(dut.rsp_hit) == 1; assert ctx.get(dut.rsp_data) == 0xAAAA
        ctx.set(dut.rsp_ready, 1); await ctx.tick(); ctx.set(dut.rsp_ready, 0)
        await _drain(ctx, dut)
        print("  standard update: PASS")
    sim.add_testbench(proc); sim.run()
    return True

# ── 5. Pipelined: hit/miss/fill ───────────────────────────────
def test_pipelined_hit_miss_fill():
    dut = MetadataCachePipelined(cache_size=1024, ways=2, access_granularity=32)
    sim = _sim(dut)
    async def proc(ctx):
        await ctx.tick()
        ADDR = 0x1000; DATA = 0xdeadbeef
        ctx.set(dut.request_valid, 1); ctx.set(dut.request_addr, ADDR)
        await ctx.tick(); ctx.set(dut.request_valid, 0)
        assert ctx.get(dut.rsp_valid) == 0
        assert ctx.get(dut.fill_valid) == 1, "fill on miss"
        for _ in range(6):
            await ctx.tick()
            assert ctx.get(dut.rsp_valid) == 0, f"no rsp at stage {_+1}"
        await ctx.tick()
        assert ctx.get(dut.rsp_valid) == 1, "rsp at T8 (7 stages delay)"
        assert ctx.get(dut.rsp_hit) == 0
        ctx.set(dut.rsp_ready, 1); ctx.set(dut.fill_ready, 1)
        ctx.set(dut.fill_data, DATA); await ctx.tick()
        ctx.set(dut.rsp_ready, 0); ctx.set(dut.fill_ready, 0)
        for _ in range(6):
            ctx.set(dut.rsp_ready, 1); await ctx.tick(); ctx.set(dut.rsp_ready, 0)
        ctx.set(dut.request_valid, 1); ctx.set(dut.request_addr, ADDR)
        await ctx.tick(); ctx.set(dut.request_valid, 0)
        assert ctx.get(dut.rsp_valid) == 0
        for _ in range(6):
            await ctx.tick()
            assert ctx.get(dut.rsp_valid) == 0
        await ctx.tick()
        assert ctx.get(dut.rsp_valid) == 1, "hit rsp"
        assert ctx.get(dut.rsp_hit) == 1, "hit after fill"
        assert ctx.get(dut.rsp_data) == DATA
        for _ in range(7):
            ctx.set(dut.rsp_ready, 1); await ctx.tick(); ctx.set(dut.rsp_ready, 0)
        print("  pipelined hit/miss/fill: PASS")
    sim.add_testbench(proc); sim.run()
    return True

# ── 6. Pipelined: stall ───────────────────────────────────────
def test_pipelined_stall():
    dut = MetadataCachePipelined(cache_size=1024, ways=2, access_granularity=32)
    sim = _sim(dut)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(dut.request_valid, 1); ctx.set(dut.request_addr, 0x1000)
        await ctx.tick(); ctx.set(dut.request_valid, 0)
        for _ in range(6): await ctx.tick()
        await ctx.tick()
        assert ctx.get(dut.rsp_valid) == 1
        ctx.set(dut.request_valid, 1); ctx.set(dut.request_addr, 0x2000)
        await ctx.tick(); ctx.set(dut.request_valid, 0)
        assert ctx.get(dut.request_ready) == 0, "stalled: not ready"
        assert ctx.get(dut.rsp_valid) == 1, "stalled: rsp held"
        ctx.set(dut.rsp_ready, 1); await ctx.tick(); ctx.set(dut.rsp_ready, 0)
        for _ in range(6):
            ctx.set(dut.rsp_ready, 1); await ctx.tick(); ctx.set(dut.rsp_ready, 0)
        await ctx.tick()
        assert ctx.get(dut.rsp_valid) == 0, "pipeline drained"
        print("  pipelined stall: PASS")
    sim.add_testbench(proc); sim.run()
    return True

# ── 7. Pipelined: busy ────────────────────────────────────────
def test_pipelined_busy():
    dut = MetadataCachePipelined(cache_size=1024, ways=2, access_granularity=32)
    sim = _sim(dut)
    async def proc(ctx):
        await ctx.tick()
        assert ctx.get(dut.busy) == 0, "idle at start"
        ctx.set(dut.request_valid, 1); ctx.set(dut.request_addr, 0x1000)
        await ctx.tick(); ctx.set(dut.request_valid, 0)
        assert ctx.get(dut.busy) == 1, "busy after request"
        for _ in range(6):
            await ctx.tick()
            assert ctx.get(dut.busy) == 1, "busy advancing"
        await ctx.tick()
        assert ctx.get(dut.busy) == 1, "busy at output"
        assert ctx.get(dut.rsp_valid) == 1
        for _ in range(7):
            ctx.set(dut.rsp_ready, 1); await ctx.tick(); ctx.set(dut.rsp_ready, 0)
        await ctx.tick()
        assert ctx.get(dut.busy) == 0, "idle after drain"
        assert ctx.get(dut.rsp_valid) == 0
        print("  pipelined busy: PASS")
    sim.add_testbench(proc); sim.run()
    return True

# ── 8. Equivalence ────────────────────────────────────────────
def test_equivalence():
    ADDR = 0x1000; DATA = 0xdeadbeef
    results = {}
    for name, cls in [("Standard", MetadataCacheStandard), ("Pipelined", MetadataCachePipelined)]:
        dut = cls(cache_size=1024, ways=1, access_granularity=32)
        sim = _sim(dut)
        async def proc(ctx, dut=dut, n=name):
            await ctx.tick()
            # Miss
            ctx.set(dut.request_valid, 1); ctx.set(dut.request_addr, ADDR)
            await ctx.tick(); ctx.set(dut.request_valid, 0)
            if name == "Standard":
                await ctx.tick()
                assert ctx.get(dut.rsp_hit) == 0, f"{n} miss"
            else:
                assert ctx.get(dut.fill_valid) == 1, f"{n} fill"
                for _ in range(6): await ctx.tick()
                await ctx.tick()
                assert ctx.get(dut.rsp_hit) == 0, f"{n} miss"
            # Fill
            ctx.set(dut.fill_ready, 1); ctx.set(dut.fill_data, DATA); await ctx.tick()
            ctx.set(dut.fill_ready, 0)
            if name == "Standard":
                ctx.set(dut.rsp_ready, 1); await ctx.tick()
                ctx.set(dut.rsp_ready, 0)
            else:
                for _ in range(6):
                    ctx.set(dut.rsp_ready, 1); await ctx.tick(); ctx.set(dut.rsp_ready, 0)
            # Hit after fill
            ctx.set(dut.request_valid, 1); ctx.set(dut.request_addr, ADDR)
            await ctx.tick(); ctx.set(dut.request_valid, 0)
            if name == "Standard":
                await ctx.tick()
                results[n] = (ctx.get(dut.rsp_hit), ctx.get(dut.rsp_data))
                ctx.set(dut.rsp_ready, 1); await ctx.tick(); ctx.set(dut.rsp_ready, 0)
            else:
                for _ in range(6): await ctx.tick()
                await ctx.tick()
                results[n] = (ctx.get(dut.rsp_hit), ctx.get(dut.rsp_data))
                for _ in range(7):
                    ctx.set(dut.rsp_ready, 1); await ctx.tick(); ctx.set(dut.rsp_ready, 0)
        sim.add_testbench(proc); sim.run()
    s_h, s_d = results["Standard"]
    p_h, p_d = results["Pipelined"]
    assert s_h == 1, f"std hit={s_h}"
    assert s_d == DATA, f"std data=0x{s_d:x}"
    assert p_h == 1, f"pip hit={p_h}"
    assert p_d == DATA, f"pip data=0x{p_d:x}"
    print("  equivalence: PASS")
    return True

# ── 9. Miss fill address assertion ──────────────────────────────
def test_miss_fill_addr():
    """Both Standard and Pipelined: fill_addr == request_addr and re-hit works."""
    for name, cls in [("Standard", MetadataCacheStandard), ("Pipelined", MetadataCachePipelined)]:
        dut = cls(cache_size=1024, ways=2, access_granularity=32)
        sim = _sim(dut)
        async def proc(ctx, dut=dut, n=name):
            await ctx.tick()
            ADDR = 0xDEAD; DATA = 0xCAFE
            # Miss
            ctx.set(dut.request_valid, 1); ctx.set(dut.request_addr, ADDR)
            await ctx.tick(); ctx.set(dut.request_valid, 0)
            if n == "Standard":
                await ctx.tick()
            else:
                for _ in range(6): await ctx.tick()
                await ctx.tick()
            # Assert miss
            assert ctx.get(dut.rsp_hit) == 0, f"{n} should miss"
            assert ctx.get(dut.rsp_valid) == 1, f"{n} rsp valid"
            ctx.set(dut.rsp_ready, 1); await ctx.tick(); ctx.set(dut.rsp_ready, 0)
            if n == "Standard":
                await ctx.tick()
            # Fill
            ctx.set(dut.fill_ready, 1); ctx.set(dut.fill_data, DATA); await ctx.tick()
            ctx.set(dut.fill_ready, 0)
            if n == "Standard":
                ctx.set(dut.rsp_ready, 1); await ctx.tick(); ctx.set(dut.rsp_ready, 0)
            # Re-request: must hit
            ctx.set(dut.request_valid, 1); ctx.set(dut.request_addr, ADDR)
            await ctx.tick(); ctx.set(dut.request_valid, 0)
            if n == "Standard":
                await ctx.tick()
            else:
                for _ in range(6): await ctx.tick()
                await ctx.tick()
            assert ctx.get(dut.rsp_hit) == 1, f"{n} should re-hit"
            assert ctx.get(dut.rsp_data) == DATA, f"{n} data=0x{ctx.get(dut.rsp_data):x}"
            ctx.set(dut.rsp_ready, 1); await ctx.tick(); ctx.set(dut.rsp_ready, 0)
        sim.add_testbench(proc); sim.run()
    print("  miss fill addr: PASS")
    return True

# ── 10. Miss fill FIFO capacity ─────────────────────────────────
def test_miss_fill_capacity():
    """Pipelined: 2-entry fill queue handles back-to-back misses."""
    dut = MetadataCachePipelined(cache_size=256, ways=2, access_granularity=32)
    sim = _sim(dut)
    async def proc(ctx):
        await ctx.tick()
        # 2 back-to-back misses to different sets
        addrs = [0x1000, 0x2000]
        for a in addrs:
            ctx.set(dut.request_valid, 1); ctx.set(dut.request_addr, a)
            await ctx.tick(); ctx.set(dut.request_valid, 0)
            for _ in range(7): await ctx.tick()
            assert ctx.get(dut.rsp_hit) == 0, f"miss 0x{a:x}"
            ctx.set(dut.rsp_ready, 1); await ctx.tick(); ctx.set(dut.rsp_ready, 0)
        # Accept both fills
        for i, a in enumerate(addrs):
            ctx.set(dut.fill_ready, 1); ctx.set(dut.fill_data, 0xBEEF0000 + i)
            await ctx.tick(); ctx.set(dut.fill_ready, 0)
            for _ in range(6):
                ctx.set(dut.rsp_ready, 1); await ctx.tick(); ctx.set(dut.rsp_ready, 0)
        # Re-request: both should hit
        for i, a in enumerate(addrs):
            ctx.set(dut.request_valid, 1); ctx.set(dut.request_addr, a)
            await ctx.tick(); ctx.set(dut.request_valid, 0)
            for _ in range(6): await ctx.tick()
            await ctx.tick()
            assert ctx.get(dut.rsp_hit) == 1, f"re-hit 0x{a:x}"
            assert ctx.get(dut.rsp_data) == 0xBEEF0000 + i
            ctx.set(dut.rsp_ready, 1); await ctx.tick(); ctx.set(dut.rsp_ready, 0)
        print("  miss fill capacity: PASS")
    sim.add_testbench(proc); sim.run()
    return True

# ── 11. Miss then hit immediate ─────────────────────────────────
def test_miss_then_hit_immediate():
    """After fill_ready, same address hits immediately without consuming miss rsp first."""
    dut = MetadataCacheStandard(cache_size=1024, ways=2, access_granularity=32)
    sim = _sim(dut)
    async def proc(ctx):
        await ctx.tick()
        # Miss
        ctx.set(dut.request_valid, 1); ctx.set(dut.request_addr, 0x3000)
        await ctx.tick(); ctx.set(dut.request_valid, 0)
        await ctx.tick()
        # Accept fill
        ctx.set(dut.fill_ready, 1); ctx.set(dut.fill_data, 0xA5A5A5A5); await ctx.tick()
        ctx.set(dut.fill_ready, 0)
        # Accept the miss response first (registered output holds it)
        ctx.set(dut.rsp_ready, 1); await ctx.tick(); ctx.set(dut.rsp_ready, 0)
        # New request to same addr (cache should have the fill)
        ctx.set(dut.request_valid, 1); ctx.set(dut.request_addr, 0x3000)
        await ctx.tick(); ctx.set(dut.request_valid, 0)
        await ctx.tick()
        # Must hit (fill updated the cache)
        assert ctx.get(dut.rsp_hit) == 1, "Should hit after fill"
        assert ctx.get(dut.rsp_data) == 0xA5A5A5A5
        print("  miss then hit immediate: PASS")
    sim.add_testbench(proc); sim.run()
    return True

# ── 12. Backpressure no data corruption ─────────────────────────
def test_backpressure_no_corruption():
    """Under backpressure, cache data changes don't corrupt held output."""
    dut = MetadataCacheStandard(cache_size=1024, ways=1, access_granularity=32)  # ways=1: set-indexed
    sim = _sim(dut)
    async def proc(ctx):
        await ctx.tick()
        # Fill ADDR_A
        ctx.set(dut.request_valid, 1); ctx.set(dut.request_addr, 0x0000)
        await ctx.tick(); ctx.set(dut.request_valid, 0)
        await ctx.tick()
        ctx.set(dut.fill_ready, 1); ctx.set(dut.fill_data, 0xAAAA); await ctx.tick()
        ctx.set(dut.fill_ready, 0)
        ctx.set(dut.rsp_ready, 1); await ctx.tick(); ctx.set(dut.rsp_ready, 0)
        await ctx.tick()
        # Hit on ADDR_A, but hold rsp_ready=0
        ctx.set(dut.request_valid, 1); ctx.set(dut.request_addr, 0x0000)
        await ctx.tick(); ctx.set(dut.request_valid, 0)
        await ctx.tick()
        assert ctx.get(dut.rsp_hit) == 1, "hit ADDR_A"
        assert ctx.get(dut.rsp_data) == 0xAAAA
        # Hold rsp_ready=0: output holds ADDR_A's data
        ctx.set(dut.rsp_ready, 0)
        # Now fill ADDR_B (same set, different tag → evicts ADDR_A with ways=1)
        ctx.set(dut.request_valid, 1); ctx.set(dut.request_addr, 0x0020)  # same set (idx=1)
        await ctx.tick(); ctx.set(dut.request_valid, 0)
        await ctx.tick()
        ctx.set(dut.fill_ready, 1); ctx.set(dut.fill_data, 0xBBBB); await ctx.tick()
        ctx.set(dut.fill_ready, 0)
        await ctx.tick()
        # Even though cache array now has 0xBBBB, the registered output holds 0xAAAA
        assert ctx.get(dut.rsp_hit) == 1, "still showing ADDR_A hit"
        assert ctx.get(dut.rsp_data) == 0xAAAA, f"data changed to 0x{ctx.get(dut.rsp_data):x}"
        # Accept the held response
        ctx.set(dut.rsp_ready, 1); await ctx.tick(); ctx.set(dut.rsp_ready, 0)
        print("  backpressure no corruption: PASS")
    sim.add_testbench(proc); sim.run()
    return True

# ── Main ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    tests = [
        ("Factory", test_factory),
        ("Elaboration", test_elaboration),
        ("Standard Hit/Miss/Fill", test_standard_hit_miss_fill),
        ("Standard Update", test_standard_update),
        ("Pipelined Hit/Miss/Fill", test_pipelined_hit_miss_fill),
        ("Pipelined Stall", test_pipelined_stall),
        ("Pipelined Busy", test_pipelined_busy),
        ("Equivalence", test_equivalence),
        ("Miss fill addr", test_miss_fill_addr),
        ("Miss fill capacity", test_miss_fill_capacity),
        ("Miss then hit immediate", test_miss_then_hit_immediate),
        ("Backpressure no corruption", test_backpressure_no_corruption),
    ]
    print("=" * 60)
    print("GC Metadata Pipeline 单元测试")
    print("=" * 60)
    all_ok = True
    for name, fn in tests:
        print(f"\n[{name}]")
        try:
            ok = fn()
            all_ok &= ok
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"  → FAIL: {e}")
            all_ok = False
    print(f"\n{'='*60}")
    print(f"{'ALL PASS' if all_ok else 'SOME FAILED'}")
    sys.exit(0 if all_ok else 1)
