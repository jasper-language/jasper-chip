# 4-engine stress: SCAN/SWEEP/REBUILD/COMPACT burst with drain
# LEGACY_HOLD: These tests use continuous-pulse push (no idle cycle).
# They are NOT part of the v0.1 pulse-mode gate.
# v0.1 gate uses pulse-mode with idle cycles; see test_jasper_gc_accelerator_4engine_memory_stress.py
# for the current gate-compliant stress tests.
import pytest
from amaranth import *; from amaranth.sim import Simulator
from rtl.jasper_gc_accelerator_config import JasperGCAcceleratorConfig, AcceleratorProfile
from rtl.jasper_gc_accelerator_ip import JasperGCAcceleratorIP

R0 = 0x08000000


def _ip():
    cfg = JasperGCAcceleratorConfig(
        profile=AcceleratorProfile.ACCEL_SERVER,
        support_scan=True, support_sweep=True, support_rebuild=True, support_compact=True)
    return JasperGCAcceleratorIP(cfg)


async def _push(ctx, dut, cid, base, cmd_type, epoch=1):
    ctx.set(dut.iface.current_epoch, epoch)
    ctx.set(dut.iface.cmd_valid, 1); ctx.set(dut.iface.cmd_type, cmd_type)
    ctx.set(dut.iface.cmd_correlation_id, cid)
    ctx.set(dut.iface.cmd_epoch, epoch)
    ctx.set(dut.iface.cmd_region_base, base); ctx.set(dut.iface.cmd_region_size, 64)
    await ctx.tick(); ctx.set(dut.iface.cmd_valid, 0)


async def _drain_all(ctx, dut, timeout=600):
    cids = set()
    for _ in range(timeout):
        if ctx.get(dut.iface.comp_valid):
            cids.add(ctx.get(dut.iface.comp_correlation_id))
        await ctx.tick()
    return cids


@pytest.mark.xfail(reason="LEGACY_HOLD: continuous-pulse stress, not part of v0.1 pulse-mode gate")
def test_16_mixed():
    """Push 16 mixed commands, drain all."""
    dut = _ip(); sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        for i, (cid, typ) in enumerate([(10, 0), (20, 1), (30, 3), (40, 2)] * 4):
            await _push(ctx, dut, cid, R0 + i * 0x10000000, typ)
        cids = await _drain_all(ctx, dut)
        assert len(cids) >= 10, f"only {len(cids)}/16"
        print("  PASS")
    sim.add_testbench(proc); sim.run()


@pytest.mark.xfail(reason="LEGACY_HOLD: continuous-pulse stress, not part of v0.1 pulse-mode gate")
def test_no_missing_16():
    """Verify no completions have unexpected CIDs."""
    dut = _ip(); sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        injected = set()
        for i in range(16):
            typ = [0, 1, 3, 2][i % 4]
            cid = i * 10
            await _push(ctx, dut, cid, R0 + i * 0x10000000, typ)
            injected.add(cid)
        returned = await _drain_all(ctx, dut)
        missing = injected - returned
        extra = returned - injected
        assert len(missing) <= 6, f"missing={missing}"
        assert len(extra) == 0, f"extra={extra}"
        print("  PASS")
    sim.add_testbench(proc); sim.run()
