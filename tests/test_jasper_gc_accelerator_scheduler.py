# tests/test_jasper_gc_accelerator_scheduler.py
from amaranth import *; from amaranth.sim import Simulator
from amaranth.back import rtlil
from rtl.jasper_gc_accelerator_scheduler import RegionScheduler

R0 = 0x08000000  # bit 28 = 0 → region 0
R1 = 0x18000000  # bit 28 = 1 → region 1


def test_scheduler_elab():
    m = Module(); m.submodules.dut = RegionScheduler(region_count=4)
    rtlil.convert(m, ports=[])


def test_scheduler_accept_good_epoch():
    sched = RegionScheduler(region_count=2)
    sim = Simulator(sched); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(sched.current_epoch, 5)
        ctx.set(sched.in_valid, 1); ctx.set(sched.in_type, 0)
        ctx.set(sched.in_epoch, 5); ctx.set(sched.in_correlation_id, 42)
        ctx.set(sched.in_region_base, R0); ctx.set(sched.out_ready, 1)
        await ctx.tick()
        assert ctx.get(sched.out_valid) == 1, "should issue"
        assert ctx.get(sched.out_correlation_id) == 42
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_scheduler_stale_epoch_abort():
    sched = RegionScheduler(region_count=2)
    sim = Simulator(sched); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(sched.current_epoch, 10)
        ctx.set(sched.in_valid, 1); ctx.set(sched.in_type, 0)
        ctx.set(sched.in_epoch, 5); ctx.set(sched.in_correlation_id, 42)
        ctx.set(sched.in_region_base, R0); ctx.set(sched.out_ready, 1)
        await ctx.tick()
        assert ctx.get(sched.out_valid) == 0, "should NOT issue"
        assert ctx.get(sched.comp_valid) == 1, "should abort"
        assert ctx.get(sched.comp_status) == 3, f"got {ctx.get(sched.comp_status)} (ABORTED=3)"
        assert ctx.get(sched.comp_correlation_id) == 42
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_scheduler_unsupported_cmd():
    sched = RegionScheduler(region_count=2, support_compact=False)
    sim = Simulator(sched); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(sched.current_epoch, 1)
        ctx.set(sched.in_valid, 1); ctx.set(sched.in_type, 2)
        ctx.set(sched.in_epoch, 1); ctx.set(sched.in_correlation_id, 77)
        ctx.set(sched.in_region_base, R0); ctx.set(sched.out_ready, 1)
        await ctx.tick()
        assert ctx.get(sched.out_valid) == 0
        assert ctx.get(sched.comp_valid) == 1
        assert ctx.get(sched.comp_status) == 5, f"got {ctx.get(sched.comp_status)} (UNSUPPORTED=5)"
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_scheduler_region_lock_exclusive():
    sched = RegionScheduler(region_count=2, support_compact=True)
    sim = Simulator(sched); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(sched.current_epoch, 1); ctx.set(sched.out_ready, 1)
        # Check out_valid BEFORE tick (pre-edge — combinational)
        ctx.set(sched.in_valid, 1); ctx.set(sched.in_type, 2)
        ctx.set(sched.in_epoch, 1); ctx.set(sched.in_correlation_id, 10)
        ctx.set(sched.in_region_base, R0)
        assert ctx.get(sched.out_valid) == 1, "1st should issue"
        await ctx.tick(); ctx.set(sched.in_valid, 0)
        await ctx.tick()
        ctx.set(sched.in_valid, 1); ctx.set(sched.in_type, 2)
        ctx.set(sched.in_epoch, 1); ctx.set(sched.in_correlation_id, 20)
        ctx.set(sched.in_region_base, R0)
        assert ctx.get(sched.out_valid) == 0, "2nd should NOT issue"
        await ctx.tick(); ctx.set(sched.in_valid, 0)
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_scheduler_cross_region_parallel():
    sched = RegionScheduler(region_count=4, support_compact=True)
    sim = Simulator(sched); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(sched.current_epoch, 1); ctx.set(sched.out_ready, 1)
        ctx.set(sched.in_valid, 1); ctx.set(sched.in_type, 2)
        ctx.set(sched.in_epoch, 1); ctx.set(sched.in_correlation_id, 10)
        ctx.set(sched.in_region_base, R0)
        assert ctx.get(sched.out_valid) == 1, "region0 issue"
        await ctx.tick(); ctx.set(sched.in_valid, 0)
        await ctx.tick()
        ctx.set(sched.in_valid, 1); ctx.set(sched.in_type, 2)
        ctx.set(sched.in_epoch, 1); ctx.set(sched.in_correlation_id, 20)
        ctx.set(sched.in_region_base, R1)
        assert ctx.get(sched.out_valid) == 1, "region1 issue (parallel)"
        await ctx.tick(); ctx.set(sched.in_valid, 0)
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_scheduler_scan_shared():
    sched = RegionScheduler(region_count=2)
    sim = Simulator(sched); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(sched.current_epoch, 1); ctx.set(sched.out_ready, 1)
        ctx.set(sched.in_valid, 1); ctx.set(sched.in_type, 0)
        ctx.set(sched.in_epoch, 1); ctx.set(sched.in_correlation_id, 10)
        ctx.set(sched.in_region_base, R0)
        await ctx.tick()
        assert ctx.get(sched.out_valid) == 1, "1st SCAN"
        ctx.set(sched.in_valid, 0); await ctx.tick()
        # 2nd SCAN on same region — shared, should issue
        ctx.set(sched.in_valid, 1); ctx.set(sched.in_type, 0)
        ctx.set(sched.in_epoch, 1); ctx.set(sched.in_correlation_id, 20)
        ctx.set(sched.in_region_base, R0)
        await ctx.tick()
        assert ctx.get(sched.out_valid) == 1, "2nd SCAN (shared)"
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_scheduler_scan_then_exclusive_blocked():
    sched = RegionScheduler(region_count=2, support_sweep=True)
    sim = Simulator(sched); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(sched.current_epoch, 1); ctx.set(sched.out_ready, 1)
        ctx.set(sched.in_valid, 1); ctx.set(sched.in_type, 0)
        ctx.set(sched.in_epoch, 1); ctx.set(sched.in_correlation_id, 10)
        ctx.set(sched.in_region_base, R0)
        await ctx.tick(); ctx.set(sched.in_valid, 0)
        await ctx.tick()
        ctx.set(sched.in_valid, 1); ctx.set(sched.in_type, 1)
        ctx.set(sched.in_epoch, 1); ctx.set(sched.in_correlation_id, 20)
        ctx.set(sched.in_region_base, R0)
        await ctx.tick()
        assert ctx.get(sched.out_valid) == 0, "SWEEP blocked"
        assert ctx.get(sched.comp_valid) == 1, "BUSY completion"
        print("  PASS")
    sim.add_testbench(proc); sim.run()
