# tests/test_jasper_gc_metadata_rebuild_engine.py
from amaranth import *; from amaranth.sim import Simulator
from amaranth.back import rtlil
from rtl.jasper_gc_metadata_rebuild_engine import MetadataRebuildEngine


def test_elab():
    m = Module(); m.submodules.mre = MetadataRebuildEngine(step_size=64)
    rtlil.convert(m, ports=[]); print("  OK")


def test_zero_size():
    mre = MetadataRebuildEngine(step_size=64)
    sim = Simulator(mre); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(mre.in_valid, 1); ctx.set(mre.in_correlation_id, 10)
        ctx.set(mre.in_region_base, 0x1000); ctx.set(mre.in_region_size, 0)
        ctx.set(mre.out_ready, 1)
        await ctx.tick(); ctx.set(mre.in_valid, 0)
        await ctx.tick()
        assert ctx.get(mre.out_valid) == 1
        assert ctx.get(mre.out_bytes_scanned) == 0
        assert ctx.get(mre.out_metadata_updates) == 0
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_one_step():
    mre = MetadataRebuildEngine(step_size=64)
    sim = Simulator(mre); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(mre.in_valid, 1); ctx.set(mre.in_correlation_id, 42)
        ctx.set(mre.in_region_base, 0x1000); ctx.set(mre.in_region_size, 32)
        ctx.set(mre.out_ready, 1)
        await ctx.tick(); ctx.set(mre.in_valid, 0)
        await ctx.tick()
        assert ctx.get(mre.out_valid) == 1
        assert ctx.get(mre.out_correlation_id) == 42
        assert ctx.get(mre.out_metadata_updates) >= 1
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_multi_step():
    mre = MetadataRebuildEngine(step_size=64)
    sim = Simulator(mre); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(mre.in_valid, 1); ctx.set(mre.in_correlation_id, 10)
        ctx.set(mre.in_region_base, 0x1000); ctx.set(mre.in_region_size, 256)
        ctx.set(mre.out_ready, 1)
        await ctx.tick(); ctx.set(mre.in_valid, 0)
        for cyc in range(15):
            if ctx.get(mre.out_valid):
                assert ctx.get(mre.out_bytes_scanned) == 256
                assert ctx.get(mre.out_metadata_updates) >= 1
                break
            await ctx.tick()
        else:
            assert False, "no completion"
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_backpressure():
    mre = MetadataRebuildEngine(step_size=64)
    sim = Simulator(mre); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(mre.in_valid, 1); ctx.set(mre.in_correlation_id, 99)
        ctx.set(mre.in_region_base, 0x1000); ctx.set(mre.in_region_size, 64)
        ctx.set(mre.out_ready, 0)
        await ctx.tick(); ctx.set(mre.in_valid, 0)
        for _ in range(10):
            if ctx.get(mre.out_valid):
                break
            await ctx.tick()
        assert ctx.get(mre.out_valid) == 1
        assert ctx.get(mre.busy) == 1
        ctx.set(mre.out_ready, 1)
        await ctx.tick()
        assert ctx.get(mre.out_valid) == 0
        assert ctx.get(mre.busy) == 0
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_cid_epoch_domain():
    mre = MetadataRebuildEngine(step_size=64)
    sim = Simulator(mre); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(mre.in_valid, 1); ctx.set(mre.in_correlation_id, 77)
        ctx.set(mre.in_epoch, 5); ctx.set(mre.in_merge_domain, 3)
        ctx.set(mre.in_region_base, 0x1000); ctx.set(mre.in_region_size, 64)
        ctx.set(mre.out_ready, 1)
        await ctx.tick(); ctx.set(mre.in_valid, 0)
        await ctx.tick()
        assert ctx.get(mre.out_valid) == 1
        assert ctx.get(mre.out_correlation_id) == 77
        assert ctx.get(mre.out_epoch) == 5
        assert ctx.get(mre.out_merge_domain) == 3
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_busy_during_rebuild():
    mre = MetadataRebuildEngine(step_size=64)
    sim = Simulator(mre); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(mre.in_valid, 1); ctx.set(mre.in_correlation_id, 10)
        ctx.set(mre.in_region_base, 0x1000); ctx.set(mre.in_region_size, 256)
        ctx.set(mre.out_ready, 1)
        await ctx.tick(); ctx.set(mre.in_valid, 0)
        assert ctx.get(mre.in_ready) == 0
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_back_to_back():
    mre = MetadataRebuildEngine(step_size=64)
    sim = Simulator(mre); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(mre.out_ready, 1)
        for cid in [10, 20]:
            ctx.set(mre.in_valid, 1); ctx.set(mre.in_correlation_id, cid)
            ctx.set(mre.in_region_base, 0x1000); ctx.set(mre.in_region_size, 64)
            await ctx.tick(); ctx.set(mre.in_valid, 0)
            await ctx.tick()
            assert ctx.get(mre.out_valid) == 1, f"no comp for {cid}"
            await ctx.tick()
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_no_dup():
    mre = MetadataRebuildEngine(step_size=64)
    sim = Simulator(mre); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(mre.out_ready, 1)
        cids = []
        for i in range(4):
            ctx.set(mre.in_valid, 1); ctx.set(mre.in_correlation_id, i)
            ctx.set(mre.in_region_base, 0x1000); ctx.set(mre.in_region_size, 64)
            await ctx.tick(); ctx.set(mre.in_valid, 0)
            await ctx.tick()
            assert ctx.get(mre.out_valid) == 1, f"no comp for {i}"
            cids.append(ctx.get(mre.out_correlation_id))
            await ctx.tick()
        assert len(set(cids)) == 4, f"dup: {cids}"
        print("  PASS")
    sim.add_testbench(proc); sim.run()
