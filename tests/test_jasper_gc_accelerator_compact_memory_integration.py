# Compact memory mode + 4-input arbiter + top-level integration tests
from amaranth import *; from amaranth.sim import Simulator
from rtl.jasper_gc_memory_arbiter import MemoryRequestArbiter
from rtl.jasper_gc_compact_engine import CompactEngine
from rtl.jasper_gc_accelerator_config import JasperGCAcceleratorConfig, AcceleratorProfile
from rtl.jasper_gc_accelerator_ip import JasperGCAcceleratorIP

R0 = 0x08000000


# ─── Compact memory mode unit tests ───────────────────────────────────────

def test_ce_counting_mode():
    ce = CompactEngine(step_size=64)
    sim = Simulator(ce); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(ce.in_valid, 1); ctx.set(ce.in_correlation_id, 10)
        ctx.set(ce.in_region_base, R0); ctx.set(ce.in_region_size, 64)
        ctx.set(ce.out_ready, 1)
        await ctx.tick(); ctx.set(ce.in_valid, 0)
        await ctx.tick()
        assert ctx.get(ce.out_valid) == 1
        assert ctx.get(ce.out_correlation_id) == 10
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_ce_memory_completes():
    ce = CompactEngine(step_size=64, use_memory=True)
    sim = Simulator(ce); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(ce.in_valid, 1); ctx.set(ce.in_correlation_id, 42)
        ctx.set(ce.in_region_base, R0); ctx.set(ce.in_region_size, 64)
        ctx.set(ce.out_ready, 1); ctx.set(ce.mem_req_ready, 1)
        ctx.set(ce.mem_rsp_valid, 1)
        await ctx.tick(); ctx.set(ce.in_valid, 0)
        await ctx.tick(); await ctx.tick()
        assert ctx.get(ce.out_valid) == 1
        assert ctx.get(ce.out_correlation_id) == 42
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_ce_memory_region_base():
    ce = CompactEngine(step_size=64, use_memory=True)
    sim = Simulator(ce); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(ce.in_valid, 1); ctx.set(ce.in_correlation_id, 10)
        ctx.set(ce.in_region_base, 0x4000); ctx.set(ce.in_region_size, 64)
        ctx.set(ce.out_ready, 1); ctx.set(ce.mem_req_ready, 1)
        await ctx.tick(); ctx.set(ce.in_valid, 0)
        assert ctx.get(ce.mem_req_addr) == 0x4000
        print("  PASS")
    sim.add_testbench(proc); sim.run()


# ─── 4-input arbiter tests ────────────────────────────────────────────────

def _arb4():
    m = Module(); m.arb = MemoryRequestArbiter(); m.submodules.arb = m.arb; return m


def test_arb4_compact_wins():
    m = _arb4(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(m.arb.mem_req_ready, 1)
        # Set all 4 valid, check priority BEFORE tick
        ctx.set(m.arb.compact_req_valid, 1); ctx.set(m.arb.mre_req_valid, 1)
        ctx.set(m.arb.sweep_req_valid, 1); ctx.set(m.arb.scan_req_valid, 1)
        assert ctx.get(m.arb.compact_req_ready) == 1, "compact should win"
        assert ctx.get(m.arb.mre_req_ready) == 0, "mre blocked"
        assert ctx.get(m.arb.sweep_req_ready) == 0, "sweep blocked"
        assert ctx.get(m.arb.scan_req_ready) == 0, "scan blocked"
        await ctx.tick(); print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_arb4_outstanding_blocks_all():
    m = _arb4(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(m.arb.mem_req_ready, 1)
        ctx.set(m.arb.scan_req_valid, 1)
        await ctx.tick(); ctx.set(m.arb.scan_req_valid, 0)
        for eng in ['compact', 'mre', 'sweep', 'scan']:
            setattr(m.arb, f'{eng}_req_valid', 1)
            assert ctx.get(getattr(m.arb, f'{eng}_req_ready')) == 0
            setattr(m.arb, f'{eng}_req_valid', 0)
        ctx.set(m.arb.mem_rsp_valid, 1); ctx.set(m.arb.scan_rsp_ready, 1)
        await ctx.tick(); print("  PASS")
    sim.add_testbench(proc); sim.run()


# ─── Top-level 4-engine memory integration ────────────────────────────────

def test_top_compact_memory():
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_SERVER)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=True)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        ctx.set(dut.iface.current_epoch, 1)
        ctx.set(dut.iface.cmd_valid, 1); ctx.set(dut.iface.cmd_type, 2)
        ctx.set(dut.iface.cmd_correlation_id, 40)
        ctx.set(dut.iface.cmd_epoch, 1)
        ctx.set(dut.iface.cmd_region_base, R0 + 0x30000000)
        ctx.set(dut.iface.cmd_region_size, 64)
        await ctx.tick(); ctx.set(dut.iface.cmd_valid, 0)
        for _ in range(60):
            if ctx.get(dut.iface.comp_valid): break
            await ctx.tick()
        assert ctx.get(dut.iface.comp_correlation_id) == 40
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_top_four_engines_memory():
    """All 4 engines in memory mode."""
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_SERVER)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=True)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        ctx.set(dut.iface.current_epoch, 1)
        for cid, typ, base in [(10, 0, R0), (20, 1, R0 + 0x10000000),
                                (30, 3, R0 + 0x20000000), (40, 2, R0 + 0x30000000)]:
            ctx.set(dut.iface.cmd_valid, 1); ctx.set(dut.iface.cmd_type, typ)
            ctx.set(dut.iface.cmd_correlation_id, cid)
            ctx.set(dut.iface.cmd_epoch, 1)
            ctx.set(dut.iface.cmd_region_base, base)
            ctx.set(dut.iface.cmd_region_size, 64)
            await ctx.tick(); ctx.set(dut.iface.cmd_valid, 0)
            for _ in range(80):
                if ctx.get(dut.iface.comp_valid): break
                await ctx.tick()
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_top_compact_counting():
    """enable_memory=False → compact counting mode."""
    cfg = JasperGCAcceleratorConfig.from_profile(AcceleratorProfile.ACCEL_SERVER)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=False)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        ctx.set(dut.iface.current_epoch, 1)
        ctx.set(dut.iface.cmd_valid, 1); ctx.set(dut.iface.cmd_type, 2)
        ctx.set(dut.iface.cmd_correlation_id, 40)
        ctx.set(dut.iface.cmd_epoch, 1)
        ctx.set(dut.iface.cmd_region_base, R0 + 0x30000000)
        await ctx.tick(); ctx.set(dut.iface.cmd_valid, 0)
        for _ in range(30):
            if ctx.get(dut.iface.comp_valid): break
            await ctx.tick()
        assert ctx.get(dut.iface.comp_correlation_id) == 40
        print("  PASS")
    sim.add_testbench(proc); sim.run()
