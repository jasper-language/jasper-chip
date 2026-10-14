# MRE memory mode + 3-input arbiter + top-level integration tests
from amaranth import *; from amaranth.sim import Simulator
from rtl.jasper_gc_memory_arbiter import MemoryRequestArbiter
from rtl.jasper_gc_metadata_rebuild_engine import MetadataRebuildEngine
from rtl.jasper_gc_accelerator_config import JasperGCAcceleratorConfig, AcceleratorProfile
from rtl.jasper_gc_accelerator_ip import JasperGCAcceleratorIP

R0 = 0x08000000


# ─── MRE memory mode unit tests ───────────────────────────────────────────

def test_mre_counting_mode():
    """use_memory=False — original counting mode."""
    mre = MetadataRebuildEngine(step_size=64)
    sim = Simulator(mre); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(mre.in_valid, 1); ctx.set(mre.in_correlation_id, 10)
        ctx.set(mre.in_region_base, R0); ctx.set(mre.in_region_size, 64)
        ctx.set(mre.out_ready, 1)
        await ctx.tick(); ctx.set(mre.in_valid, 0)
        await ctx.tick()
        assert ctx.get(mre.out_valid) == 1
        assert ctx.get(mre.out_correlation_id) == 10
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_mre_memory_completes():
    """use_memory=True — completes via MemoryAccess."""
    mre = MetadataRebuildEngine(step_size=64, use_memory=True)
    sim = Simulator(mre); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(mre.in_valid, 1); ctx.set(mre.in_correlation_id, 42)
        ctx.set(mre.in_region_base, R0); ctx.set(mre.in_region_size, 64)
        ctx.set(mre.out_ready, 1); ctx.set(mre.mem_req_ready, 1)
        ctx.set(mre.mem_rsp_valid, 1)
        await ctx.tick(); ctx.set(mre.in_valid, 0)
        await ctx.tick(); await ctx.tick()
        assert ctx.get(mre.out_valid) == 1
        assert ctx.get(mre.out_correlation_id) == 42
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_mre_memory_region_base():
    """First mem_req_addr should be region_base."""
    mre = MetadataRebuildEngine(step_size=64, use_memory=True)
    sim = Simulator(mre); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(mre.in_valid, 1); ctx.set(mre.in_correlation_id, 10)
        ctx.set(mre.in_region_base, 0x3000); ctx.set(mre.in_region_size, 64)
        ctx.set(mre.out_ready, 1); ctx.set(mre.mem_req_ready, 1)
        await ctx.tick(); ctx.set(mre.in_valid, 0)
        assert ctx.get(mre.mem_req_addr) == 0x3000
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_mre_memory_backpressure():
    """Memory backpressure stalls MRE."""
    mre = MetadataRebuildEngine(step_size=64, use_memory=True)
    sim = Simulator(mre); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(mre.in_valid, 1); ctx.set(mre.in_correlation_id, 99)
        ctx.set(mre.in_region_base, R0); ctx.set(mre.in_region_size, 64)
        ctx.set(mre.out_ready, 1); ctx.set(mre.mem_req_ready, 0)
        await ctx.tick(); ctx.set(mre.in_valid, 0)
        for _ in range(5):
            assert ctx.get(mre.mem_req_valid) == 1
            await ctx.tick()
        ctx.set(mre.mem_req_ready, 1); ctx.set(mre.mem_rsp_valid, 1)
        for _ in range(10):
            if ctx.get(mre.out_valid): break
            await ctx.tick()
        else: assert False
        print("  PASS")
    sim.add_testbench(proc); sim.run()


# ─── 3-input arbiter tests ────────────────────────────────────────────────

def _arb3():
    m = Module(); m.arb = MemoryRequestArbiter(); m.submodules.arb = m.arb; return m


def test_arb3_mre_wins():
    """MRE request wins over sweep and scan."""
    m = _arb3(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(m.arb.mem_req_ready, 1)
        ctx.set(m.arb.mre_req_valid, 1); ctx.set(m.arb.sweep_req_valid, 1)
        ctx.set(m.arb.scan_req_valid, 1)
        assert ctx.get(m.arb.mem_req_valid) == 1
        assert ctx.get(m.arb.mre_req_ready) == 1
        assert ctx.get(m.arb.sweep_req_ready) == 0
        assert ctx.get(m.arb.scan_req_ready) == 0
        await ctx.tick()
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_arb3_sweep_wins_when_mre_idle():
    """Sweep wins over scan when MRE idle."""
    m = _arb3(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(m.arb.mem_req_ready, 1)
        ctx.set(m.arb.sweep_req_valid, 1); ctx.set(m.arb.scan_req_valid, 1)
        assert ctx.get(m.arb.mem_req_valid) == 1
        assert ctx.get(m.arb.sweep_req_ready) == 1
        assert ctx.get(m.arb.scan_req_ready) == 0
        await ctx.tick()
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_arb3_outstanding_blocks_all():
    """Outstanding request blocks all 3 engines."""
    m = _arb3(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(m.arb.mem_req_ready, 1)
        ctx.set(m.arb.mre_req_valid, 1)
        assert ctx.get(m.arb.mem_req_valid) == 1
        await ctx.tick(); ctx.set(m.arb.mre_req_valid, 0)
        # Now outstanding — all should be blocked
        ctx.set(m.arb.mre_req_valid, 1); ctx.set(m.arb.sweep_req_valid, 1)
        ctx.set(m.arb.scan_req_valid, 1)
        assert ctx.get(m.arb.mre_req_ready) == 0
        assert ctx.get(m.arb.sweep_req_ready) == 0
        assert ctx.get(m.arb.scan_req_ready) == 0
        # Return response
        ctx.set(m.arb.mre_req_valid, 0)
        ctx.set(m.arb.mem_rsp_valid, 1); ctx.set(m.arb.mre_rsp_ready, 1)
        await ctx.tick()
        # Now outstanding cleared
        ctx.set(m.arb.mem_rsp_valid, 0)
        ctx.set(m.arb.mre_req_valid, 1)
        assert ctx.get(m.arb.mre_req_ready) == 1
        await ctx.tick()
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_arb3_response_routes():
    """Response routes to correct engine."""
    m = _arb3(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(m.arb.mem_req_ready, 1)
        for eng, tag, eng_name in [(m.arb.mre_req_valid, 10, 'mre'),
                                    (m.arb.sweep_req_valid, 20, 'sweep'),
                                    (m.arb.scan_req_valid, 30, 'scan')]:
            ctx.set(eng, 1)
            assert ctx.get(m.arb.mem_req_valid) == 1
            await ctx.tick(); ctx.set(eng, 0)
            ctx.set(m.arb.mem_rsp_valid, 1)
            rsp_valid = {'mre': m.arb.mre_rsp_valid, 'sweep': m.arb.sweep_rsp_valid,
                         'scan': m.arb.scan_rsp_valid}
            rsp_ready = {'mre': m.arb.mre_rsp_ready, 'sweep': m.arb.sweep_rsp_ready,
                         'scan': m.arb.scan_rsp_ready}
            ctx.set(rsp_ready[eng_name], 1)
            await ctx.tick()
            assert ctx.get(rsp_valid[eng_name]) == 1, f"{eng_name} should get rsp"
            others = [n for n in ['mre', 'sweep', 'scan'] if n != eng_name]
            for o in others:
                assert ctx.get(rsp_valid[o]) == 0, f"{o} should NOT get rsp"
            ctx.set(m.arb.mem_rsp_valid, 0)
            ctx.set(rsp_ready[eng_name], 0)
        print("  PASS")
    sim.add_testbench(proc); sim.run()


# ─── Top-level MRE memory integration ─────────────────────────────────────

def test_top_mre_memory_mode():
    """Top-level REBUILD in memory mode via arbiter+MemoryAccess."""
    cfg = JasperGCAcceleratorConfig(profile=AcceleratorProfile.ACCEL_SERVER)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=True)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        ctx.set(dut.iface.current_epoch, 1)
        ctx.set(dut.iface.cmd_valid, 1); ctx.set(dut.iface.cmd_type, 3)
        ctx.set(dut.iface.cmd_correlation_id, 30)
        ctx.set(dut.iface.cmd_epoch, 1)
        ctx.set(dut.iface.cmd_region_base, R0 + 0x20000000)
        ctx.set(dut.iface.cmd_region_size, 64)
        await ctx.tick(); ctx.set(dut.iface.cmd_valid, 0)
        for _ in range(60):
            if ctx.get(dut.iface.comp_valid): break
            await ctx.tick()
        assert ctx.get(dut.iface.comp_correlation_id) == 30
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_top_three_engines_memory():
    """SCAN + SWEEP + REBUILD all in memory mode."""
    cfg = JasperGCAcceleratorConfig(profile=AcceleratorProfile.ACCEL_SERVER)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=True)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        ctx.set(dut.iface.current_epoch, 1)
        for cid, typ, base in [(10, 0, R0), (20, 1, R0 + 0x10000000), (30, 3, R0 + 0x20000000)]:
            ctx.set(dut.iface.cmd_valid, 1); ctx.set(dut.iface.cmd_type, typ)
            ctx.set(dut.iface.cmd_correlation_id, cid)
            ctx.set(dut.iface.cmd_epoch, 1)
            ctx.set(dut.iface.cmd_region_base, base)
            ctx.set(dut.iface.cmd_region_size, 64)
            await ctx.tick(); ctx.set(dut.iface.cmd_valid, 0)
            for _ in range(60):
                if ctx.get(dut.iface.comp_valid): break
                await ctx.tick()
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_top_mre_counting_mode():
    """enable_memory=False → MRE stays counting mode."""
    cfg = JasperGCAcceleratorConfig(profile=AcceleratorProfile.ACCEL_SERVER)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=False)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        ctx.set(dut.iface.current_epoch, 1)
        ctx.set(dut.iface.cmd_valid, 1); ctx.set(dut.iface.cmd_type, 3)
        ctx.set(dut.iface.cmd_correlation_id, 30)
        ctx.set(dut.iface.cmd_epoch, 1)
        ctx.set(dut.iface.cmd_region_base, R0 + 0x20000000)
        ctx.set(dut.iface.cmd_region_size, 64)
        await ctx.tick(); ctx.set(dut.iface.cmd_valid, 0)
        for _ in range(30):
            if ctx.get(dut.iface.comp_valid): break
            await ctx.tick()
        assert ctx.get(dut.iface.comp_correlation_id) == 30
        print("  PASS")
    sim.add_testbench(proc); sim.run()
