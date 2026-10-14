# tests/test_jasper_gc_sweep_engine.py
from amaranth import *; from amaranth.sim import Simulator
from amaranth.back import rtlil
from rtl.jasper_gc_sweep_engine import SweepEngine


def test_elab():
    from amaranth.back import rtlil
    m = Module(); m.submodules.se = SweepEngine(step_size=64)
    rtlil.convert(m, ports=[]); print("  OK")


def test_zero_size():
    se = SweepEngine(step_size=64)
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
        assert ctx.get(se.out_objects_scanned) == 0
        assert ctx.get(se.out_dead_objects) == 0
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_one_step():
    se = SweepEngine(step_size=64)
    sim = Simulator(se); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(se.in_valid, 1); ctx.set(se.in_correlation_id, 42)
        ctx.set(se.in_region_base, 0x1000); ctx.set(se.in_region_size, 32)
        ctx.set(se.out_ready, 1)
        await ctx.tick(); ctx.set(se.in_valid, 0)
        await ctx.tick()
        assert ctx.get(se.out_valid) == 1
        assert ctx.get(se.out_correlation_id) == 42
        assert ctx.get(se.out_objects_scanned) >= 1
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_multi_step():
    se = SweepEngine(step_size=64)
    sim = Simulator(se); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(se.in_valid, 1); ctx.set(se.in_correlation_id, 10)
        ctx.set(se.in_region_base, 0x1000); ctx.set(se.in_region_size, 256)
        ctx.set(se.out_ready, 1)
        await ctx.tick(); ctx.set(se.in_valid, 0)
        for cyc in range(15):
            if ctx.get(se.out_valid):
                assert ctx.get(se.out_bytes_scanned) == 256
                assert ctx.get(se.out_objects_scanned) == 4
                break
            await ctx.tick()
        else:
            assert False, "no completion"
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_backpressure():
    se = SweepEngine(step_size=64)
    sim = Simulator(se); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(se.in_valid, 1); ctx.set(se.in_correlation_id, 99)
        ctx.set(se.in_region_base, 0x1000); ctx.set(se.in_region_size, 64)
        ctx.set(se.out_ready, 0)
        await ctx.tick(); ctx.set(se.in_valid, 0)
        for _ in range(10):
            if ctx.get(se.out_valid):
                break
            await ctx.tick()
        assert ctx.get(se.out_valid) == 1
        assert ctx.get(se.busy) == 1
        ctx.set(se.out_ready, 1)
        await ctx.tick()
        assert ctx.get(se.out_valid) == 0
        assert ctx.get(se.busy) == 0
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_cid_epoch_domain():
    se = SweepEngine(step_size=64)
    sim = Simulator(se); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(se.in_valid, 1); ctx.set(se.in_correlation_id, 77)
        ctx.set(se.in_epoch, 5); ctx.set(se.in_merge_domain, 3)
        ctx.set(se.in_region_base, 0x1000); ctx.set(se.in_region_size, 64)
        ctx.set(se.out_ready, 1)
        await ctx.tick(); ctx.set(se.in_valid, 0)
        await ctx.tick()
        assert ctx.get(se.out_valid) == 1
        assert ctx.get(se.out_correlation_id) == 77
        assert ctx.get(se.out_epoch) == 5
        assert ctx.get(se.out_merge_domain) == 3
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_dead_reclaim_stats():
    se = SweepEngine(step_size=64, dead_ratio=0.7, object_granule=32)
    sim = Simulator(se); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(se.in_valid, 1); ctx.set(se.in_correlation_id, 10)
        ctx.set(se.in_region_base, 0x1000); ctx.set(se.in_region_size, 128)
        ctx.set(se.out_ready, 1)
        await ctx.tick(); ctx.set(se.in_valid, 0)
        for cyc in range(15):
            if ctx.get(se.out_valid):
                total = ctx.get(se.out_objects_scanned)
                dead = ctx.get(se.out_dead_objects)
                reclaimed = ctx.get(se.out_bytes_moved)
                meta = ctx.get(se.out_metadata_updates)
                assert dead <= total, f"dead={dead} > total={total}"
                assert reclaimed >= dead * 32, f"reclaim={reclaimed} dead={dead}"
                assert meta >= 1
                break
            await ctx.tick()
        else:
            assert False, "no completion"
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_busy_during_sweep():
    se = SweepEngine(step_size=64)
    sim = Simulator(se); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(se.in_valid, 1); ctx.set(se.in_correlation_id, 10)
        ctx.set(se.in_region_base, 0x1000); ctx.set(se.in_region_size, 256)
        ctx.set(se.out_ready, 1)
        await ctx.tick(); ctx.set(se.in_valid, 0)
        assert ctx.get(se.in_ready) == 0, "should be busy"
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_back_to_back():
    se = SweepEngine(step_size=64)
    sim = Simulator(se); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(se.out_ready, 1)
        for cid in [10, 20]:
            ctx.set(se.in_valid, 1); ctx.set(se.in_correlation_id, cid)
            ctx.set(se.in_region_base, 0x1000); ctx.set(se.in_region_size, 64)
            await ctx.tick(); ctx.set(se.in_valid, 0)
            for _ in range(15):
                if ctx.get(se.out_valid):
                    break
                await ctx.tick()
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_no_dup():
    se = SweepEngine(step_size=64)
    sim = Simulator(se); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(se.out_ready, 1)
        cids = []
        for i in range(4):
            ctx.set(se.in_valid, 1); ctx.set(se.in_correlation_id, i)
            ctx.set(se.in_region_base, 0x1000); ctx.set(se.in_region_size, 64)
            await ctx.tick(); ctx.set(se.in_valid, 0)
            # Wait 2 cycles for SWEEPING→DONE, then read
            await ctx.tick()
            assert ctx.get(se.out_valid) == 1, f"no completion for {i}"
            cids.append(ctx.get(se.out_correlation_id))
            await ctx.tick()  # consume
        assert len(set(cids)) == 4, f"dup: {cids}"
        print("  PASS")
    sim.add_testbench(proc); sim.run()
