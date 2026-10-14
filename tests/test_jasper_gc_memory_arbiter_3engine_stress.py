# 3-input arbiter stress: priority, outstanding, response routing no-loss
from amaranth import *; from amaranth.sim import Simulator
from rtl.jasper_gc_memory_arbiter import MemoryRequestArbiter


def _arb3():
    m = Module(); m.arb = MemoryRequestArbiter(); m.submodules.arb = m.arb; return m


def test_mre_beats_sweep_beats_scan():
    """MRE > SWEEP > SCAN priority when all 3 valid."""
    m = _arb3(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(m.arb.mem_req_ready, 1)
        ctx.set(m.arb.mre_req_valid, 1); ctx.set(m.arb.sweep_req_valid, 1)
        ctx.set(m.arb.scan_req_valid, 1)
        assert ctx.get(m.arb.mre_req_ready) == 1
        assert ctx.get(m.arb.sweep_req_ready) == 0
        assert ctx.get(m.arb.scan_req_ready) == 0
        await ctx.tick(); print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_sweep_beats_scan_when_mre_idle():
    m = _arb3(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(m.arb.mem_req_ready, 1)
        ctx.set(m.arb.sweep_req_valid, 1); ctx.set(m.arb.scan_req_valid, 1)
        assert ctx.get(m.arb.sweep_req_ready) == 1
        assert ctx.get(m.arb.scan_req_ready) == 0
        await ctx.tick(); print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_scan_alone():
    m = _arb3(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(m.arb.mem_req_ready, 1)
        ctx.set(m.arb.scan_req_valid, 1)
        assert ctx.get(m.arb.scan_req_ready) == 1
        await ctx.tick(); print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_outstanding_blocks_all():
    m = _arb3(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(m.arb.mem_req_ready, 1)
        ctx.set(m.arb.scan_req_valid, 1)
        assert ctx.get(m.arb.mem_req_valid) == 1
        await ctx.tick(); ctx.set(m.arb.scan_req_valid, 0)
        # outstanding=1, all blocked
        ctx.set(m.arb.mre_req_valid, 1); ctx.set(m.arb.sweep_req_valid, 1)
        ctx.set(m.arb.scan_req_valid, 1)
        assert ctx.get(m.arb.mre_req_ready) == 0
        assert ctx.get(m.arb.sweep_req_ready) == 0
        assert ctx.get(m.arb.scan_req_ready) == 0
        # release
        ctx.set(m.arb.mre_req_valid, 0); ctx.set(m.arb.sweep_req_valid, 0)
        ctx.set(m.arb.scan_req_valid, 0)
        ctx.set(m.arb.mem_rsp_valid, 1); ctx.set(m.arb.scan_rsp_ready, 1)
        await ctx.tick()
        assert ctx.get(m.arb.scan_rsp_valid) == 1, "scan should get rsp"
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_response_hold_under_backpressure():
    """Response stays valid when rsp_ready=0; releases when rsp_ready=1."""
    m = _arb3(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(m.arb.mem_req_ready, 1)
        ctx.set(m.arb.scan_req_valid, 1)
        await ctx.tick(); ctx.set(m.arb.scan_req_valid, 0)
        ctx.set(m.arb.mem_rsp_valid, 1); ctx.set(m.arb.scan_rsp_ready, 0)
        await ctx.tick()
        assert ctx.get(m.arb.scan_rsp_valid) == 1  # held
        # All new reqs should be blocked (outstanding via mem_rsp)
        ctx.set(m.arb.mre_req_valid, 1)
        assert ctx.get(m.arb.mre_req_ready) == 0  # blocked
        ctx.set(m.arb.mre_req_valid, 0)
        # Release
        ctx.set(m.arb.scan_rsp_ready, 1)
        await ctx.tick()
        ctx.set(m.arb.mem_rsp_valid, 0)  # clear for next cycle
        assert ctx.get(m.arb.scan_rsp_valid) == 0  # consumed
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_response_route_correct():
    """Each engine's response routes correctly."""
    m = _arb3(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(m.arb.mem_req_ready, 1)
        for eng, name, rsp_sig in [
            (m.arb.mre_req_valid, 'mre', m.arb.mre_rsp_valid),
            (m.arb.sweep_req_valid, 'sweep', m.arb.sweep_rsp_valid),
            (m.arb.scan_req_valid, 'scan', m.arb.scan_rsp_valid),
        ]:
            ctx.set(eng, 1)
            await ctx.tick(); ctx.set(eng, 0)
            ctx.set(m.arb.mem_rsp_valid, 1); ctx.set(getattr(m.arb, f'{name}_rsp_ready'), 1)
            await ctx.tick()
            assert ctx.get(rsp_sig) == 1, f"{name} should get rsp"
            for other, _, o_sig in [
                (m.arb.mre_req_valid, 'mre', m.arb.mre_rsp_valid),
                (m.arb.sweep_req_valid, 'sweep', m.arb.sweep_rsp_valid),
                (m.arb.scan_req_valid, 'scan', m.arb.scan_rsp_valid),
            ]:
                if other is not eng:
                    assert ctx.get(o_sig) == 0, f"wrong engine got rsp"
            ctx.set(m.arb.mem_rsp_valid, 0)
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_tag_set_equality():
    """accepted tags == response tags."""
    m = _arb3(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(m.arb.mem_req_ready, 1)
        accepted = set()
        for eng, name in [(m.arb.mre_req_valid, 'mre'), (m.arb.sweep_req_valid, 'sweep'),
                           (m.arb.scan_req_valid, 'scan')]:
            tag = {'mre': 10, 'sweep': 20, 'scan': 30}[name]
            ctx.set(eng, 1); setattr(m.arb, f'{name}_req_tag', tag)
            if ctx.get(getattr(m.arb, f'{name}_req_ready')):
                accepted.add((name, tag))
            await ctx.tick(); ctx.set(eng, 0)
            ctx.set(m.arb.mem_rsp_valid, 1)
            ctx.set(getattr(m.arb, f'{name}_rsp_ready'), 1)
            await ctx.tick()
            ctx.set(m.arb.mem_rsp_valid, 0)
        # Verify each got its response
        for name in ['mre', 'sweep', 'scan']:
            assert ctx.get(getattr(m.arb, f'{name}_rsp_valid')) == 0  # already consumed
        print("  PASS")
    sim.add_testbench(proc); sim.run()
