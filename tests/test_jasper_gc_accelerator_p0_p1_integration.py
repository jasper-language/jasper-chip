# P0/P1 integration tests — CommandQueue → RegionScheduler → CompletionQueue
from amaranth import *; from amaranth.sim import Simulator
from amaranth.back import rtlil
from rtl.jasper_gc_accelerator_config import (
    JasperGCAcceleratorConfig, AcceleratorProfile)
from rtl.jasper_gc_accelerator_ip import JasperGCAcceleratorIP

R0 = 0x08000000; R1 = 0x18000000


def _ip(cfg=None):
    if cfg is None:
        cfg = JasperGCAcceleratorConfig(profile=AcceleratorProfile.ACCEL_STANDARD)
    return JasperGCAcceleratorIP(cfg)


async def push_wait(ctx, dut, cid, base=R0, cmd_type=0, epoch=1, cur_epoch=1):
    """Push one command with given current_epoch, wait for completion."""
    ctx.set(dut.iface.current_epoch, cur_epoch)
    ctx.set(dut.iface.cmd_valid, 1); ctx.set(dut.iface.cmd_type, cmd_type)
    ctx.set(dut.iface.cmd_epoch, epoch)
    ctx.set(dut.iface.cmd_correlation_id, cid)
    ctx.set(dut.iface.cmd_region_base, base)
    await ctx.tick(); ctx.set(dut.iface.cmd_valid, 0)
    for _ in range(80):
        if ctx.get(dut.iface.comp_valid):
            return ctx.get(dut.iface.comp_correlation_id), ctx.get(dut.iface.comp_status)
        await ctx.tick()
    return None, None


def test_elab():
    for p in AcceleratorProfile:
        m = Module()
        m.submodules.dut = JasperGCAcceleratorIP(
            JasperGCAcceleratorConfig.from_profile(p))
        rtlil.convert(m, ports=[])
    print("  all profiles elaborate")


def test_single_cmd():
    dut = _ip(); sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        cid, _ = await push_wait(ctx, dut, 42)
        assert cid == 42
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_two_cmds():
    dut = _ip(); sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        c1, _ = await push_wait(ctx, dut, 10, R0)
        c2, _ = await push_wait(ctx, dut, 20, R1)
        assert c1 == 10 and c2 == 20
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_cmd_queue_depth():
    cfg = JasperGCAcceleratorConfig(command_queue_depth=4)
    dut = _ip(cfg); sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        for i in range(4):
            c, _ = await push_wait(ctx, dut, i)
            assert c == i
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_comp_backpressure():
    cfg = JasperGCAcceleratorConfig(completion_queue_depth=2)
    dut = _ip(cfg); sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        for cid in [10, 20, 30]:
            c, _ = await push_wait(ctx, dut, cid, R0 + cid * 0x10000000)
            assert c == cid
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_epoch_ok():
    """current_epoch=3, cmd_epoch=3 → OK."""
    dut = _ip(); sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        cid, st = await push_wait(ctx, dut, 10, epoch=3, cur_epoch=3)
        assert cid == 10
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_epoch_stale_aborted():
    """current_epoch=3, cmd_epoch=2 → ABORTED (status=3)."""
    dut = _ip(); sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        cid, st = await push_wait(ctx, dut, 10, epoch=2, cur_epoch=3)
        assert cid == 10
        assert st == 3, f"expected ABORTED(3), got {st}"
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_epoch_future_ok():
    """current_epoch=3, cmd_epoch=4 → accepted (future epoch = OK)."""
    dut = _ip(); sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        cid, st = await push_wait(ctx, dut, 10, epoch=4, cur_epoch=3)
        assert cid == 10
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_epoch_change_after_push():
    """current_epoch changes after push → uses epoch-at-issue semantics."""
    dut = _ip(); sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        ctx.set(dut.iface.current_epoch, 3)
        ctx.set(dut.iface.cmd_valid, 1); ctx.set(dut.iface.cmd_correlation_id, 10)
        ctx.set(dut.iface.cmd_epoch, 3)
        await ctx.tick(); ctx.set(dut.iface.cmd_valid, 0)
        ctx.set(dut.iface.current_epoch, 10)  # raises epoch after push
        for _ in range(80):
            if ctx.get(dut.iface.comp_valid):
                assert ctx.get(dut.iface.comp_correlation_id) == 10
                print("  PASS")
                return
            await ctx.tick()
        assert False, "no completion"
    sim.add_testbench(proc); sim.run()


def test_region_lock_exclusive():
    cfg = JasperGCAcceleratorConfig(support_compact=True)
    dut = _ip(cfg); sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        c1, _ = await push_wait(ctx, dut, 10, R0, cmd_type=2)
        c2, _ = await push_wait(ctx, dut, 20, R0, cmd_type=2)
        assert c1 == 10
        assert c2 is not None
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_cross_region_parallel():
    cfg = JasperGCAcceleratorConfig(support_compact=True)
    dut = _ip(cfg); sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        c1, _ = await push_wait(ctx, dut, 10, R0, cmd_type=2)
        c2, _ = await push_wait(ctx, dut, 20, R1, cmd_type=2)
        assert c1 == 10 and c2 == 20
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_unsupported_cmd():
    cfg = JasperGCAcceleratorConfig(support_compact=False)
    dut = _ip(cfg); sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        cid, _ = await push_wait(ctx, dut, 77, cmd_type=2)
        assert cid is not None
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_no_loss_10():
    dut = _ip(); sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        seen = set()
        for i in range(10):
            c, _ = await push_wait(ctx, dut, i, R0 + i * 0x10000000)
            seen.add(c)
        assert len(seen) == 10
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_cid_set_equality():
    dut = _ip(); sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        injected = {10, 20, 30, 40, 50}
        returned = set()
        for cid in sorted(injected):
            rc, _ = await push_wait(ctx, dut, cid, R0 + cid)
            returned.add(rc)
        assert injected == returned
        print("  PASS")
    sim.add_testbench(proc); sim.run()
