# 3-engine memory stress: SCAN/SWEEP/REBUILD through arbiter→MemoryAccess
from amaranth import *; from amaranth.sim import Simulator
from rtl.jasper_gc_accelerator_config import JasperGCAcceleratorConfig, AcceleratorProfile
from rtl.jasper_gc_accelerator_ip import JasperGCAcceleratorIP

R0 = 0x08000000


def _dut():
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_SERVER)
    return JasperGCAcceleratorIP(cfg, enable_memory=True)


async def _push_wait(ctx, dut, cid, base, typ, epoch=1, timeout=60):
    ctx.set(dut.iface.current_epoch, epoch)
    ctx.set(dut.iface.cmd_valid, 1); ctx.set(dut.iface.cmd_type, typ)
    ctx.set(dut.iface.cmd_correlation_id, cid)
    ctx.set(dut.iface.cmd_epoch, epoch)
    ctx.set(dut.iface.cmd_region_base, base); ctx.set(dut.iface.cmd_region_size, 64)
    await ctx.tick(); ctx.set(dut.iface.cmd_valid, 0)
    for _ in range(timeout):
        if ctx.get(dut.iface.comp_valid):
            return ctx.get(dut.iface.comp_correlation_id)
        await ctx.tick()
    return None


def test_scan_alone():
    dut = _dut(); sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        cid = await _push_wait(ctx, dut, 10, R0, 0)
        assert cid == 10, f"got {cid}"
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_sweep_alone():
    dut = _dut(); sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        cid = await _push_wait(ctx, dut, 20, R0 + 0x10000000, 1)
        assert cid == 20
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_rebuild_alone():
    dut = _dut(); sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        cid = await _push_wait(ctx, dut, 30, R0 + 0x20000000, 3)
        assert cid == 30
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_three_mixed():
    """SCAN + SWEEP + REBUILD all complete."""
    dut = _dut(); sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        for cid, typ, base in [(10, 0, R0), (20, 1, R0 + 0x10000000), (30, 3, R0 + 0x20000000)]:
            rc = await _push_wait(ctx, dut, cid, base, typ)
            assert rc == cid, f"expected {cid} got {rc}"
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_mixed_burst_6():
    """6 mixed commands, all drain."""
    dut = _dut(); sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        cmds = [(10, 0, R0), (20, 1, R0 + 0x10000000), (30, 3, R0 + 0x20000000),
                (40, 0, R0 + 0x30000000), (50, 1, R0 + 0x40000000), (60, 3, R0 + 0x50000000)]
        for cid, typ, base in cmds:
            rc = await _push_wait(ctx, dut, cid, base, typ)
            assert rc == cid, f"expected {cid} got {rc}"
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_epoch_preserved():
    dut = _dut(); sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        ctx.set(dut.iface.current_epoch, 3)
        ctx.set(dut.iface.cmd_valid, 1); ctx.set(dut.iface.cmd_type, 0)
        ctx.set(dut.iface.cmd_correlation_id, 10)
        ctx.set(dut.iface.cmd_epoch, 3)
        ctx.set(dut.iface.cmd_region_base, R0); ctx.set(dut.iface.cmd_region_size, 64)
        await ctx.tick(); ctx.set(dut.iface.cmd_valid, 0)
        for _ in range(60):
            if ctx.get(dut.iface.comp_valid):
                assert ctx.get(dut.iface.comp_epoch) == 3
                break
            await ctx.tick()
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_counting_mode_backward():
    """enable_memory=False all still work."""
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_SERVER)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=False)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        for cid, typ, base in [(10, 0, R0), (20, 1, R0 + 0x10000000), (30, 3, R0 + 0x20000000)]:
            rc = await _push_wait(ctx, dut, cid, base, typ)
            assert rc == cid
        print("  PASS")
    sim.add_testbench(proc); sim.run()
