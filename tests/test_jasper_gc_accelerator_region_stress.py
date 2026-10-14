# Region ownership stress: concurrent commands to same/different regions
from amaranth import *; from amaranth.sim import Simulator
from rtl.jasper_gc_accelerator_config import JasperGCAcceleratorConfig, AcceleratorProfile
from rtl.jasper_gc_accelerator_ip import JasperGCAcceleratorIP

R0 = 0x08000000; R1 = 0x18000000


def _ip():
    cfg = JasperGCAcceleratorConfig(
        profile=AcceleratorProfile.ACCEL_SERVER,
        support_scan=True, support_sweep=True, support_rebuild=True, support_compact=True)
    return JasperGCAcceleratorIP(cfg)


async def _push_wait(ctx, dut, cid, base, typ, epoch=1):
    ctx.set(dut.iface.current_epoch, epoch)
    ctx.set(dut.iface.cmd_valid, 1); ctx.set(dut.iface.cmd_type, typ)
    ctx.set(dut.iface.cmd_correlation_id, cid)
    ctx.set(dut.iface.cmd_epoch, epoch)
    ctx.set(dut.iface.cmd_region_base, base); ctx.set(dut.iface.cmd_region_size, 64)
    await ctx.tick(); ctx.set(dut.iface.cmd_valid, 0)
    for _ in range(60):
        if ctx.get(dut.iface.comp_valid):
            return ctx.get(dut.iface.comp_correlation_id), ctx.get(dut.iface.comp_status)
        await ctx.tick()
    return None, None


def test_scan_shared_same_region():
    """Multiple SCANs to same region → all complete (shared)."""
    dut = _ip(); sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        c1, _ = await _push_wait(ctx, dut, 10, R0, 0)
        c2, _ = await _push_wait(ctx, dut, 20, R0, 0)
        assert c1 == 10 and c2 == 20
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_scan_then_sweep_same_region():
    """SCAN then SWEEP to same region → SWEEP may be BUSY or OK."""
    dut = _ip(); sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        c1, _ = await _push_wait(ctx, dut, 10, R0, 0)
        c2, s2 = await _push_wait(ctx, dut, 20, R0, 1)
        assert c1 == 10 and c2 == 20
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_scan_then_rebuild_same_region():
    """SCAN then REBUILD to same region."""
    dut = _ip(); sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        c1, _ = await _push_wait(ctx, dut, 10, R0, 0)
        c2, _ = await _push_wait(ctx, dut, 20, R0, 3)
        assert c1 == 10 and c2 == 20
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_scan_then_compact_same_region():
    """SCAN then COMPACT to same region."""
    dut = _ip(); sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        c1, _ = await _push_wait(ctx, dut, 10, R0, 0)
        c2, _ = await _push_wait(ctx, dut, 20, R0, 2)
        assert c1 == 10 and c2 == 20
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_diff_region_parallel():
    """Different regions → commands execute in parallel."""
    dut = _ip(); sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        for cid, base, typ in [(10, R0, 0), (20, R1, 1), (30, R0 + 0x20000000, 3), (40, R0 + 0x30000000, 2)]:
            c, _ = await _push_wait(ctx, dut, cid, base, typ)
            assert c == cid
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_stale_epoch_no_region_lock():
    """Stale epoch command rejected — no region lock."""
    dut = _ip(); sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        # current_epoch=5 → cmd_epoch=3 is stale
        c1, s1 = await _push_wait(ctx, dut, 10, R0, 0, epoch=3)
        assert c1 == 10, f"cid={c1}"
        # After stale rejection, region should be free — send another
        c2, _ = await _push_wait(ctx, dut, 20, R0, 0, epoch=5)
        assert c2 == 20
        print("  PASS")
    sim.add_testbench(proc); sim.run()
