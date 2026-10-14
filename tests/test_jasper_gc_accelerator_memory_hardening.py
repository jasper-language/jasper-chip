# MemoryAccess v0.2 hardening + SweepEngine memory integration
from amaranth import *; from amaranth.sim import Simulator
from rtl.jasper_gc_memory_access import MemoryAccess
from rtl.jasper_gc_memory_arbiter import MemoryRequestArbiter
from rtl.jasper_gc_sweep_engine import SweepEngine
from rtl.jasper_gc_scan_engine import ScanEngine
from rtl.jasper_gc_accelerator_config import JasperGCAcceleratorConfig, AcceleratorProfile
from rtl.jasper_gc_accelerator_ip import JasperGCAcceleratorIP

R0 = 0x08000000


# ─── MemoryAccess v0.2: response backpressure ─────────────────────────────

def test_rsp_hold_when_ready_low():
    """Response stays valid when rsp_ready=0."""
    ma = MemoryAccess(read_latency=2, queue_depth=4)
    sim = Simulator(ma); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(ma.rsp_ready, 0)
        ctx.set(ma.req_valid, 1); ctx.set(ma.req_addr, 0x1000); ctx.set(ma.req_tag, 10)
        await ctx.tick(); ctx.set(ma.req_valid, 0)
        for _ in range(10):
            if ctx.get(ma.rsp_valid):
                assert ctx.get(ma.rsp_tag) == 10
                assert ctx.get(ma.rsp_valid) == 1
                # Still valid next cycle (rsp_ready=0)
                await ctx.tick()
                assert ctx.get(ma.rsp_valid) == 1
                assert ctx.get(ma.rsp_tag) == 10
                break
            await ctx.tick()
        else: assert False, "no rsp"
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_rsp_unblock_after_backpressure():
    """Response pops after rsp_ready=1."""
    ma = MemoryAccess(read_latency=2, queue_depth=4)
    sim = Simulator(ma); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(ma.rsp_ready, 0)
        ctx.set(ma.req_valid, 1); ctx.set(ma.req_tag, 10)
        await ctx.tick(); ctx.set(ma.req_valid, 0)
        for _ in range(20):
            if ctx.get(ma.rsp_valid): break
            await ctx.tick()
        assert ctx.get(ma.rsp_valid) == 1, "no rsp"
        ctx.set(ma.rsp_ready, 1)
        await ctx.tick()
        assert ctx.get(ma.rsp_valid) == 0  # consumed
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_no_loss_accepted_tags():
    """Accepted tags == response tags (collect during and after pushes)."""
    ma = MemoryAccess(read_latency=3, queue_depth=8)
    sim = Simulator(ma); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(ma.rsp_ready, 1)
        accepted = set()
        rsp_tags = set()
        for tag in range(8):
            ctx.set(ma.req_valid, 1); ctx.set(ma.req_tag, tag)
            if ctx.get(ma.req_ready): accepted.add(tag)
            if ctx.get(ma.rsp_valid): rsp_tags.add(ctx.get(ma.rsp_tag))
            await ctx.tick(); ctx.set(ma.req_valid, 0)
            if ctx.get(ma.rsp_valid): rsp_tags.add(ctx.get(ma.rsp_tag))
        for _ in range(120):
            if ctx.get(ma.rsp_valid):
                rsp_tags.add(ctx.get(ma.rsp_tag))
                if len(rsp_tags) >= len(accepted): break
            await ctx.tick()
        assert rsp_tags == accepted, f"accepted={accepted} rsp={rsp_tags}"
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_queue_full_backpressure():
    """req_ready=0 when queue + pipe full."""
    ma = MemoryAccess(read_latency=2, queue_depth=2)
    sim = Simulator(ma); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(ma.rsp_ready, 0)
        for i in range(10):
            ctx.set(ma.req_valid, 1); ctx.set(ma.req_tag, i)
            await ctx.tick(); ctx.set(ma.req_valid, 0)
            if not ctx.get(ma.req_ready):
                print(f"  PASS (full at {i})")
                return
        assert False, "never full"
    sim.add_testbench(proc); sim.run()


# ─── SweepEngine memory mode ──────────────────────────────────────────────

def test_sweep_counting_mode():
    """use_memory=False — original counting mode works."""
    se = SweepEngine(step_size=64)
    sim = Simulator(se); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(se.in_valid, 1); ctx.set(se.in_correlation_id, 10)
        ctx.set(se.in_region_base, R0); ctx.set(se.in_region_size, 64)
        ctx.set(se.out_ready, 1)
        await ctx.tick(); ctx.set(se.in_valid, 0)
        await ctx.tick()
        assert ctx.get(se.out_valid) == 1
        assert ctx.get(se.out_correlation_id) == 10
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_sweep_memory_completes():
    """use_memory=True — sweep completes via MemoryAccess."""
    se = SweepEngine(step_size=64, use_memory=True)
    sim = Simulator(se); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(se.in_valid, 1); ctx.set(se.in_correlation_id, 42)
        ctx.set(se.in_region_base, R0); ctx.set(se.in_region_size, 64)
        ctx.set(se.out_ready, 1); ctx.set(se.mem_req_ready, 1)
        ctx.set(se.mem_rsp_valid, 1)
        await ctx.tick(); ctx.set(se.in_valid, 0)
        await ctx.tick(); await ctx.tick()
        assert ctx.get(se.out_valid) == 1
        assert ctx.get(se.out_correlation_id) == 42
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_sweep_memory_region_base():
    """First mem_req_addr should be region_base."""
    se = SweepEngine(step_size=64, use_memory=True)
    sim = Simulator(se); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(se.in_valid, 1); ctx.set(se.in_correlation_id, 10)
        ctx.set(se.in_region_base, 0x2000); ctx.set(se.in_region_size, 64)
        ctx.set(se.out_ready, 1); ctx.set(se.mem_req_ready, 1)
        await ctx.tick(); ctx.set(se.in_valid, 0)
        assert ctx.get(se.mem_req_addr) == 0x2000, f"addr={ctx.get(se.mem_req_addr)}"
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_sweep_memory_backpressure():
    """Memory backpressure stalls sweep engine."""
    se = SweepEngine(step_size=64, use_memory=True)
    sim = Simulator(se); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(se.in_valid, 1); ctx.set(se.in_correlation_id, 99)
        ctx.set(se.in_region_base, R0); ctx.set(se.in_region_size, 64)
        ctx.set(se.out_ready, 1); ctx.set(se.mem_req_ready, 0)
        await ctx.tick(); ctx.set(se.in_valid, 0)
        for _ in range(5):
            assert ctx.get(se.mem_req_valid) == 1
            await ctx.tick()
        ctx.set(se.mem_req_ready, 1); ctx.set(se.mem_rsp_valid, 1)
        for _ in range(10):
            if ctx.get(se.out_valid): break
            await ctx.tick()
        else: assert False
        print("  PASS")
    sim.add_testbench(proc); sim.run()


# ─── MemoryRequestArbiter ─────────────────────────────────────────────────

def _arb():
    m = Module()
    m.arb = MemoryRequestArbiter()
    m.submodules.arb = m.arb
    return m


def test_arb_sweep_wins():
    """Sweep request wins over scan."""
    m = _arb(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(m.arb.mem_req_ready, 1)
        ctx.set(m.arb.scan_req_valid, 1); ctx.set(m.arb.scan_req_tag, 0x0010)
        ctx.set(m.arb.sweep_req_valid, 1); ctx.set(m.arb.sweep_req_tag, 0x0011)
        # Check BEFORE tick (combinational)
        assert ctx.get(m.arb.mem_req_valid) == 1
        tag = ctx.get(m.arb.mem_req_tag)
        assert (tag & 0x3FFF) == 0x11, f"tag={tag:04x}"
        await ctx.tick()
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_arb_scan_when_sweep_idle():
    """Scan wins when sweep is idle."""
    m = _arb(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(m.arb.mem_req_ready, 1)
        ctx.set(m.arb.scan_req_valid, 1); ctx.set(m.arb.scan_req_tag, 0x0020)
        assert ctx.get(m.arb.mem_req_valid) == 1
        tag = ctx.get(m.arb.mem_req_tag)
        assert (tag & 0x3FFF) == 0x20, f"tag={tag:04x}"
        await ctx.tick()
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_arb_scan_holds_when_sweep_active():
    """Scan holds valid when sweep is selected."""
    m = _arb(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(m.arb.mem_req_ready, 1)
        ctx.set(m.arb.scan_req_valid, 1)
        ctx.set(m.arb.sweep_req_valid, 1)
        # Check BEFORE tick
        assert ctx.get(m.arb.scan_req_ready) == 0  # not selected
        assert ctx.get(m.arb.scan_req_valid) == 1  # still holding
        await ctx.tick()
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_arb_outstanding_blocks_new():
    """Single-outstanding: new request blocked while outstanding."""
    m = _arb(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(m.arb.mem_req_ready, 1)
        ctx.set(m.arb.scan_req_valid, 1)  # scan issues request
        assert ctx.get(m.arb.mem_req_valid) == 1
        await ctx.tick(); ctx.set(m.arb.scan_req_valid, 0)
        # Now outstanding=1, sweep should be blocked
        ctx.set(m.arb.sweep_req_valid, 1)
        rdy = ctx.get(m.arb.sweep_req_ready)
        assert rdy == 0, f"sweep_req_ready={rdy}"
        # Return response (consume)
        ctx.set(m.arb.sweep_req_valid, 0)
        ctx.set(m.arb.mem_rsp_valid, 1); ctx.set(m.arb.scan_rsp_ready, 1)
        await ctx.tick()
        # Now outstanding=0, sweep can issue
        ctx.set(m.arb.mem_rsp_valid, 0)
        ctx.set(m.arb.sweep_req_valid, 1)
        assert ctx.get(m.arb.mem_req_valid) == 1
        await ctx.tick()
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_arb_response_routes_correctly():
    """Response routes to the engine that issued the request."""
    m = _arb(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(m.arb.mem_req_ready, 1)
        ctx.set(m.arb.sweep_req_valid, 1)  # sweep issues first
        await ctx.tick(); ctx.set(m.arb.sweep_req_valid, 0)
        # Return response
        ctx.set(m.arb.mem_rsp_valid, 1); ctx.set(m.arb.sweep_rsp_ready, 1)
        await ctx.tick()
        assert ctx.get(m.arb.sweep_rsp_valid) == 1, "sweep should get rsp"
        assert ctx.get(m.arb.scan_rsp_valid) == 0, "scan should NOT get rsp"
        ctx.set(m.arb.mem_rsp_valid, 0)
        # Now scan issues
        ctx.set(m.arb.scan_req_valid, 1)
        await ctx.tick(); ctx.set(m.arb.scan_req_valid, 0)
        ctx.set(m.arb.mem_rsp_valid, 1)
        await ctx.tick()
        assert ctx.get(m.arb.scan_rsp_valid) == 1, "scan should get rsp"
        assert ctx.get(m.arb.sweep_rsp_valid) == 0, "sweep should NOT get rsp"
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_arb_scan_blocked_during_sweep_outstanding():
    """Scan req_ready=0 while sweep request is outstanding."""
    m = _arb(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(m.arb.mem_req_ready, 1)
        ctx.set(m.arb.sweep_req_valid, 1)
        await ctx.tick(); ctx.set(m.arb.sweep_req_valid, 0)
        # scan should be blocked
        ctx.set(m.arb.scan_req_valid, 1)
        assert ctx.get(m.arb.scan_req_ready) == 0, "scan should be blocked"
        print("  PASS")
    sim.add_testbench(proc); sim.run()


# ─── Top-level memory integration ─────────────────────────────────────────

def test_top_sweep_memory_mode():
    """Top-level SWEEP in memory mode completes via MemoryAccess."""
    cfg = JasperGCAcceleratorConfig(profile=AcceleratorProfile.ACCEL_SERVER)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=True)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        ctx.set(dut.iface.current_epoch, 1)
        ctx.set(dut.iface.cmd_valid, 1); ctx.set(dut.iface.cmd_type, 1)
        ctx.set(dut.iface.cmd_correlation_id, 20)
        ctx.set(dut.iface.cmd_epoch, 1)
        ctx.set(dut.iface.cmd_region_base, R0 + 0x10000000)
        ctx.set(dut.iface.cmd_region_size, 64)
        await ctx.tick(); ctx.set(dut.iface.cmd_valid, 0)
        for _ in range(60):
            if ctx.get(dut.iface.comp_valid):
                break
            await ctx.tick()
        assert ctx.get(dut.iface.comp_correlation_id) == 20
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_top_sweep_counting_mode():
    """Top-level SWEEP in counting mode (enable_memory=False)."""
    cfg = JasperGCAcceleratorConfig(profile=AcceleratorProfile.ACCEL_SERVER)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=False)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        ctx.set(dut.iface.current_epoch, 1)
        ctx.set(dut.iface.cmd_valid, 1); ctx.set(dut.iface.cmd_type, 1)
        ctx.set(dut.iface.cmd_correlation_id, 20)
        ctx.set(dut.iface.cmd_epoch, 1)
        ctx.set(dut.iface.cmd_region_base, R0 + 0x10000000)
        ctx.set(dut.iface.cmd_region_size, 64)
        await ctx.tick(); ctx.set(dut.iface.cmd_valid, 0)
        for _ in range(30):
            if ctx.get(dut.iface.comp_valid):
                break
            await ctx.tick()
        assert ctx.get(dut.iface.comp_correlation_id) == 20
        print("  PASS")
    sim.add_testbench(proc); sim.run()

def test_memory_mode_ip_scan_sweep():
    """Top-level accelerator with enable_memory=True processes both SCAN and SWEEP."""
    cfg = JasperGCAcceleratorConfig(profile=AcceleratorProfile.ACCEL_SERVER)
    dut = JasperGCAcceleratorIP(cfg, enable_memory=True)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.iface.comp_ready, 1)
        ctx.set(dut.iface.current_epoch, 1)
        for cid, typ, base in [(10, 0, R0), (20, 1, R0 + 0x10000000)]:
            ctx.set(dut.iface.cmd_valid, 1); ctx.set(dut.iface.cmd_type, typ)
            ctx.set(dut.iface.cmd_correlation_id, cid)
            ctx.set(dut.iface.cmd_epoch, 1)
            ctx.set(dut.iface.cmd_region_base, base)
            ctx.set(dut.iface.cmd_region_size, 64)
            await ctx.tick(); ctx.set(dut.iface.cmd_valid, 0)
            for _ in range(40):
                if ctx.get(dut.iface.comp_valid): break
                await ctx.tick()
        print("  PASS")
    sim.add_testbench(proc); sim.run()
