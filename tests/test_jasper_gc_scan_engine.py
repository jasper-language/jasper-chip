# ScanEngine unit tests (counting mode, no memory).
from amaranth import *; from amaranth.sim import Simulator
from amaranth.back import rtlil
from rtl.jasper_gc_scan_engine import ScanEngine


def test_elab():
    m = Module(); m.submodules.se = ScanEngine(step_size=64)
    rtlil.convert(m, ports=[]); print("  OK")


def test_scan_one_step():
    se = ScanEngine(step_size=64)
    sim = Simulator(se); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(se.in_valid, 1); ctx.set(se.in_correlation_id, 42)
        ctx.set(se.in_region_base, 0x1000); ctx.set(se.in_region_size, 32)
        ctx.set(se.out_ready, 1)
        await ctx.tick(); ctx.set(se.in_valid, 0)
        # IDLE→SCAN_ISSUE (auto-advance in one cycle), then SCAN_ISSUE conditionally
        # With size=32 ≤ step=64, completes immediately within SCAN_ISSUE
        await ctx.tick()
        assert ctx.get(se.out_valid) == 1
        assert ctx.get(se.out_correlation_id) == 42
        assert ctx.get(se.out_bytes_scanned) == 32
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_multi_step():
    se = ScanEngine(step_size=64)
    sim = Simulator(se); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(se.in_valid, 1); ctx.set(se.in_correlation_id, 10)
        ctx.set(se.in_region_base, 0x1000); ctx.set(se.in_region_size, 256)
        ctx.set(se.out_ready, 1)
        await ctx.tick(); ctx.set(se.in_valid, 0)
        for _ in range(20):
            if ctx.get(se.out_valid):
                assert ctx.get(se.out_bytes_scanned) == 256
                break
            await ctx.tick()
        else: assert False
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_mem_latency_slows_scan():
    """With use_memory=True, memory latency affects scan rate."""
    se = ScanEngine(step_size=64, use_memory=True)
    sim = Simulator(se); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(se.in_valid, 1); ctx.set(se.in_correlation_id, 10)
        ctx.set(se.in_region_base, 0x1000); ctx.set(se.in_region_size, 128)
        ctx.set(se.out_ready, 1)
        await ctx.tick(); ctx.set(se.in_valid, 0)
        done = False
        for cyc in range(40):
            rsp = (cyc % 4 == 0)
            ctx.set(se.mem_req_ready, rsp); ctx.set(se.mem_rsp_valid, rsp)
            if ctx.get(se.out_valid):
                done = True; break
            await ctx.tick()
        assert done
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_mem_backpressure():
    """use_memory=True, memory backpressure stalls engine."""
    se = ScanEngine(step_size=64, use_memory=True)
    sim = Simulator(se); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(se.in_valid, 1); ctx.set(se.in_correlation_id, 99)
        ctx.set(se.in_region_base, 0x1000); ctx.set(se.in_region_size, 64)
        ctx.set(se.out_ready, 1)
        ctx.set(se.mem_req_ready, 0); ctx.set(se.mem_rsp_valid, 0)
        await ctx.tick(); ctx.set(se.in_valid, 0)
        # Should be waiting for mem_req_ready
        for _ in range(5):
            assert ctx.get(se.mem_req_valid) == 1
            await ctx.tick()
        # Unblock memory
        ctx.set(se.mem_req_ready, 1); ctx.set(se.mem_rsp_valid, 1)
        for _ in range(10):
            if ctx.get(se.out_valid): break
            await ctx.tick()
        else: assert False
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_epoch_cid_domain():
    se = ScanEngine(step_size=64)
    sim = Simulator(se); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(se.in_valid, 1); ctx.set(se.in_correlation_id, 77)
        ctx.set(se.in_epoch, 5); ctx.set(se.in_merge_domain, 3)
        ctx.set(se.in_region_base, 0x1000); ctx.set(se.in_region_size, 32)
        ctx.set(se.out_ready, 1)
        await ctx.tick(); ctx.set(se.in_valid, 0)
        await ctx.tick()
        assert ctx.get(se.out_correlation_id) == 77
        assert ctx.get(se.out_epoch) == 5
        assert ctx.get(se.out_merge_domain) == 3
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_zero_size():
    se = ScanEngine(step_size=64)
    sim = Simulator(se); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(se.in_valid, 1); ctx.set(se.in_correlation_id, 10)
        ctx.set(se.in_region_base, 0x1000); ctx.set(se.in_region_size, 0)
        ctx.set(se.out_ready, 1)
        await ctx.tick(); ctx.set(se.in_valid, 0)
        await ctx.tick()
        assert ctx.get(se.out_valid) == 1
        assert ctx.get(se.out_bytes_scanned) == 0
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_no_dup():
    se = ScanEngine(step_size=64)
    sim = Simulator(se); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(se.out_ready, 1)
        cids = []
        for i in range(4):
            ctx.set(se.in_valid, 1); ctx.set(se.in_correlation_id, i)
            ctx.set(se.in_region_base, 0x1000); ctx.set(se.in_region_size, 64)
            await ctx.tick(); ctx.set(se.in_valid, 0)
            await ctx.tick()
            assert ctx.get(se.out_valid) == 1
            cids.append(ctx.get(se.out_correlation_id))
            await ctx.tick()
        assert len(set(cids)) == 4
        print("  PASS")
    sim.add_testbench(proc); sim.run()
