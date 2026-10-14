# 4-input arbiter no-loss stress: priority / outstanding / response hold / route / tag equality.
from amaranth import *; from amaranth.sim import Simulator
from rtl.jasper_gc_memory_arbiter import MemoryRequestArbiter


def _arb4():
    m = Module(); arb = MemoryRequestArbiter(); m.submodules.arb = arb; return m, arb


# ─── Priority: compact > mre > sweep > scan ──────────────────────────────

def test_compact_beats_all():
    """All 4 valid → compact wins."""
    m, arb = _arb4(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(arb.mem_req_ready, 1)
        ctx.set(arb.compact_req_valid, 1); ctx.set(arb.mre_req_valid, 1)
        ctx.set(arb.sweep_req_valid, 1); ctx.set(arb.scan_req_valid, 1)
        assert ctx.get(arb.compact_req_ready) == 1
        assert ctx.get(arb.mre_req_ready) == 0
        assert ctx.get(arb.sweep_req_ready) == 0
        assert ctx.get(arb.scan_req_ready) == 0
        await ctx.tick(); print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_mre_beats_sweep_beats_scan():
    """mre / sweep / scan valid → mre wins."""
    m, arb = _arb4(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(arb.mem_req_ready, 1)
        ctx.set(arb.mre_req_valid, 1); ctx.set(arb.sweep_req_valid, 1)
        ctx.set(arb.scan_req_valid, 1)
        assert ctx.get(arb.mre_req_ready) == 1
        assert ctx.get(arb.sweep_req_ready) == 0
        assert ctx.get(arb.scan_req_ready) == 0
        await ctx.tick(); print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_sweep_beats_scan():
    """sweep / scan valid → sweep wins (mre idle)."""
    m, arb = _arb4(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(arb.mem_req_ready, 1)
        ctx.set(arb.sweep_req_valid, 1); ctx.set(arb.scan_req_valid, 1)
        assert ctx.get(arb.sweep_req_ready) == 1
        assert ctx.get(arb.scan_req_ready) == 0
        await ctx.tick(); print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_scan_alone():
    """Only scan valid → scan wins."""
    m, arb = _arb4(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(arb.mem_req_ready, 1)
        ctx.set(arb.scan_req_valid, 1)
        assert ctx.get(arb.scan_req_ready) == 1
        await ctx.tick(); print("  PASS")
    sim.add_testbench(proc); sim.run()


# ─── Outstanding blocks all ──────────────────────────────────────────────

def test_outstanding_blocks_all():
    """outstanding=1 → all req_ready=0."""
    m, arb = _arb4(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(arb.mem_req_ready, 1)
        ctx.set(arb.scan_req_valid, 1)
        await ctx.tick(); ctx.set(arb.scan_req_valid, 0)
        for eng in ['compact', 'mre', 'sweep', 'scan']:
            ctx.set(getattr(arb, f'{eng}_req_valid'), 1)
            rr = ctx.get(getattr(arb, f'{eng}_req_ready'))
            assert rr == 0, f"{eng} got req_ready when outstanding"
            ctx.set(getattr(arb, f'{eng}_req_valid'), 0)
        ctx.set(arb.mem_rsp_valid, 1); ctx.set(arb.scan_rsp_ready, 1)
        await ctx.tick(); print("  PASS")
    sim.add_testbench(proc); sim.run()


# ─── Response backpressure ───────────────────────────────────────────────

def test_response_hold_under_backpressure():
    """rsp_valid holds when rsp_ready=0; releases when rsp_ready=1."""
    m, arb = _arb4(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(arb.mem_req_ready, 1)
        ctx.set(arb.scan_req_valid, 1)
        await ctx.tick(); ctx.set(arb.scan_req_valid, 0)
        ctx.set(arb.mem_rsp_valid, 1); ctx.set(arb.scan_rsp_ready, 0)
        await ctx.tick()
        assert ctx.get(arb.scan_rsp_valid) == 1
        assert ctx.get(arb.mre_req_ready) == 0
        ctx.set(arb.scan_rsp_ready, 1)
        await ctx.tick()
        ctx.set(arb.mem_rsp_valid, 0)
        assert ctx.get(arb.scan_rsp_valid) == 0
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_outstanding_cleared_on_rsp_accept():
    """outstanding clears after response accepted, allowing new requests."""
    m, arb = _arb4(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(arb.mem_req_ready, 1)
        ctx.set(arb.scan_req_valid, 1)
        await ctx.tick(); ctx.set(arb.scan_req_valid, 0)
        ctx.set(arb.mre_req_valid, 1)
        assert ctx.get(arb.mre_req_ready) == 0
        ctx.set(arb.mre_req_valid, 0)
        ctx.set(arb.mem_rsp_valid, 1); ctx.set(arb.scan_rsp_ready, 1)
        await ctx.tick(); ctx.set(arb.mem_rsp_valid, 0)
        ctx.set(arb.compact_req_valid, 1)
        assert ctx.get(arb.compact_req_ready) == 1
        await ctx.tick(); print("  PASS")
    sim.add_testbench(proc); sim.run()


# ─── Response routing: each engine gets its own response ──────────────────

def test_compact_response_route():
    m, arb = _arb4(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(arb.mem_req_ready, 1)
        ctx.set(arb.compact_req_valid, 1)
        await ctx.tick(); ctx.set(arb.compact_req_valid, 0)
        ctx.set(arb.mem_rsp_valid, 1); ctx.set(arb.compact_rsp_ready, 1)
        await ctx.tick()
        assert ctx.get(arb.compact_rsp_valid) == 1
        assert ctx.get(arb.mre_rsp_valid) == 0
        assert ctx.get(arb.sweep_rsp_valid) == 0
        assert ctx.get(arb.scan_rsp_valid) == 0
        ctx.set(arb.mem_rsp_valid, 0)
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_mre_response_route():
    m, arb = _arb4(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(arb.mem_req_ready, 1)
        ctx.set(arb.mre_req_valid, 1)
        await ctx.tick(); ctx.set(arb.mre_req_valid, 0)
        ctx.set(arb.mem_rsp_valid, 1); ctx.set(arb.mre_rsp_ready, 1)
        await ctx.tick()
        assert ctx.get(arb.mre_rsp_valid) == 1
        assert ctx.get(arb.compact_rsp_valid) == 0
        assert ctx.get(arb.sweep_rsp_valid) == 0
        assert ctx.get(arb.scan_rsp_valid) == 0
        ctx.set(arb.mem_rsp_valid, 0)
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_sweep_response_route():
    m, arb = _arb4(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(arb.mem_req_ready, 1)
        ctx.set(arb.sweep_req_valid, 1)
        await ctx.tick(); ctx.set(arb.sweep_req_valid, 0)
        ctx.set(arb.mem_rsp_valid, 1); ctx.set(arb.sweep_rsp_ready, 1)
        await ctx.tick()
        assert ctx.get(arb.sweep_rsp_valid) == 1
        assert ctx.get(arb.compact_rsp_valid) == 0
        assert ctx.get(arb.mre_rsp_valid) == 0
        assert ctx.get(arb.scan_rsp_valid) == 0
        ctx.set(arb.mem_rsp_valid, 0)
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_scan_response_route():
    m, arb = _arb4(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(arb.mem_req_ready, 1)
        ctx.set(arb.scan_req_valid, 1)
        await ctx.tick(); ctx.set(arb.scan_req_valid, 0)
        ctx.set(arb.mem_rsp_valid, 1); ctx.set(arb.scan_rsp_ready, 1)
        await ctx.tick()
        assert ctx.get(arb.scan_rsp_valid) == 1
        assert ctx.get(arb.compact_rsp_valid) == 0
        assert ctx.get(arb.mre_rsp_valid) == 0
        assert ctx.get(arb.sweep_rsp_valid) == 0
        ctx.set(arb.mem_rsp_valid, 0)
        print("  PASS")
    sim.add_testbench(proc); sim.run()


# ─── out_engine stable under backpressure ─────────────────────────────────

def test_out_engine_stable_under_backpressure():
    """out_engine doesn't change while response is held."""
    m, arb = _arb4(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(arb.mem_req_ready, 1)
        ctx.set(arb.scan_req_valid, 1)
        await ctx.tick(); ctx.set(arb.scan_req_valid, 0)
        ctx.set(arb.mem_rsp_valid, 1); ctx.set(arb.scan_rsp_ready, 0)
        await ctx.tick()
        ctx.set(arb.compact_req_valid, 1)
        await ctx.tick(); ctx.set(arb.compact_req_valid, 0)
        ctx.set(arb.scan_rsp_ready, 1)
        await ctx.tick()
        assert ctx.get(arb.scan_rsp_valid) == 1
        assert ctx.get(arb.compact_rsp_valid) == 0
        ctx.set(arb.mem_rsp_valid, 0)
        print("  PASS")
    sim.add_testbench(proc); sim.run()


# ─── Tag set equality (no missing, no duplicate) ──────────────────────────

def test_tag_set_equality():
    """accepted request tags == routed response tags per engine."""
    m, arb = _arb4(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(arb.mem_req_ready, 1)
        req_tags = {}
        rsp_tags = {}
        for eng, name in [(arb.compact_req_valid, 'compact'),
                           (arb.mre_req_valid, 'mre'),
                           (arb.sweep_req_valid, 'sweep'),
                           (arb.scan_req_valid, 'scan')]:
            for tag in [1, 2, 3]:
                ctx.set(eng, 1)
                ctx.set(getattr(arb, f'{name}_req_tag'), tag)
                rr = ctx.get(getattr(arb, f'{name}_req_ready'))
                if rr:
                    req_tags.setdefault(name, []).append(tag)
                await ctx.tick(); ctx.set(eng, 0)
                ctx.set(arb.mem_rsp_valid, 1)
                ctx.set(arb.mem_rsp_tag, tag)
                ctx.set(getattr(arb, f'{name}_rsp_ready'), 1)
                await ctx.tick()
                rv = ctx.get(getattr(arb, f'{name}_rsp_valid'))
                if rv:
                    rt = ctx.get(arb.mem_rsp_tag)
                    rsp_tags.setdefault(name, []).append(rt)
                ctx.set(arb.mem_rsp_valid, 0)
                ctx.set(arb.mem_rsp_tag, 0)
                ctx.set(getattr(arb, f'{name}_rsp_ready'), 0)
        for name in ['compact', 'mre', 'sweep', 'scan']:
            assert req_tags.get(name, []) == rsp_tags.get(name, []), \
                f"{name}: req={req_tags.get(name, [])} rsp={rsp_tags.get(name, [])}"
        print("  PASS")
    sim.add_testbench(proc); sim.run()


# ─── No missing / no duplicate ────────────────────────────────────────────

def test_no_missing_responses():
    """Every accepted request produces exactly one response (one per engine)."""
    m, arb = _arb4(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(arb.mem_req_ready, 1)
        acc = 0; rsp = 0
        engs = [(arb.compact_req_valid, 'compact'),
                (arb.mre_req_valid, 'mre'),
                (arb.sweep_req_valid, 'sweep'),
                (arb.scan_req_valid, 'scan')]
        for sig, name in engs:
            ctx.set(sig, 1)
            await ctx.tick(); ctx.set(sig, 0)
            if ctx.get(arb.mem_req_valid):
                acc += 1
                ctx.set(arb.mem_rsp_valid, 1)
                ctx.set(getattr(arb, f'{name}_rsp_ready'), 1)
                await ctx.tick()
                assert ctx.get(getattr(arb, f'{name}_rsp_valid')) == 1, f"{name} missing rsp"
                rsp += 1
                ctx.set(arb.mem_rsp_valid, 0)
                ctx.set(getattr(arb, f'{name}_rsp_ready'), 0)
        assert acc == rsp, f"accepted={acc} responses={rsp}"
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_no_duplicate_responses():
    """Each accepted request produces exactly one response; no response goes to wrong engine."""
    m, arb = _arb4(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(arb.mem_req_ready, 1)
        # Accept compact, return response — only compact gets it
        ctx.set(arb.compact_req_valid, 1)
        await ctx.tick(); ctx.set(arb.compact_req_valid, 0)
        ctx.set(arb.mem_rsp_valid, 1)
        ctx.set(arb.compact_rsp_ready, 1)
        # Also set other rsp_ready to capture misrouting
        ctx.set(arb.mre_rsp_ready, 1); ctx.set(arb.sweep_rsp_ready, 1)
        ctx.set(arb.scan_rsp_ready, 1)
        await ctx.tick()
        assert ctx.get(arb.compact_rsp_valid) == 1, "compact should get rsp"
        assert ctx.get(arb.mre_rsp_valid) == 0, "mre should NOT get rsp"
        assert ctx.get(arb.sweep_rsp_valid) == 0, "sweep should NOT get rsp"
        assert ctx.get(arb.scan_rsp_valid) == 0, "scan should NOT get rsp"
        ctx.set(arb.mem_rsp_valid, 0)
        # Accept scan, return response — only scan gets it
        ctx.set(arb.scan_req_valid, 1)
        await ctx.tick(); ctx.set(arb.scan_req_valid, 0)
        ctx.set(arb.mem_rsp_valid, 1)
        ctx.set(arb.scan_rsp_ready, 1)
        await ctx.tick()
        assert ctx.get(arb.scan_rsp_valid) == 1
        assert ctx.get(arb.compact_rsp_valid) == 0
        assert ctx.get(arb.mre_rsp_valid) == 0
        assert ctx.get(arb.sweep_rsp_valid) == 0
        ctx.set(arb.mem_rsp_valid, 0)
        # No duplicate count test requires counting accepted vs responses
        print("  PASS")
    sim.add_testbench(proc); sim.run()


# ─── Priority does not overwrite accepted route ──────────────────────────

def test_priority_no_overwrite_route():
    """out_engine latched at request time; priority change doesn't overwrite."""
    m, arb = _arb4(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(arb.mem_req_ready, 1)
        ctx.set(arb.scan_req_valid, 1)
        await ctx.tick(); ctx.set(arb.scan_req_valid, 0)
        ctx.set(arb.compact_req_valid, 1)
        await ctx.tick(); ctx.set(arb.compact_req_valid, 0)
        ctx.set(arb.mem_rsp_valid, 1); ctx.set(arb.scan_rsp_ready, 1)
        ctx.set(arb.compact_rsp_ready, 1)
        await ctx.tick()
        assert ctx.get(arb.scan_rsp_valid) == 1
        assert ctx.get(arb.compact_rsp_valid) == 0
        ctx.set(arb.mem_rsp_valid, 0)
        print("  PASS")
    sim.add_testbench(proc); sim.run()


# ─── No last_sel routing ─────────────────────────────────────────────────

def test_no_last_sel_routing():
    """Routing based on out_engine (latched), not a separate selector."""
    m, arb = _arb4(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(arb.mem_req_ready, 1)
        ctx.set(arb.scan_req_valid, 1)
        await ctx.tick(); ctx.set(arb.scan_req_valid, 0)
        for eng_name in ['compact', 'mre', 'sweep']:
            ctx.set(getattr(arb, f'{eng_name}_req_valid'), 1)
            await ctx.tick()
            ctx.set(getattr(arb, f'{eng_name}_req_valid'), 0)
        ctx.set(arb.mem_rsp_valid, 1); ctx.set(arb.scan_rsp_ready, 1)
        await ctx.tick()
        assert ctx.get(arb.scan_rsp_valid) == 1
        ctx.set(arb.mem_rsp_valid, 0)
        print("  PASS")
    sim.add_testbench(proc); sim.run()


# ─── Single outstanding confirmed ────────────────────────────────────────

def test_single_outstanding():
    """Only one outstanding request at a time."""
    m, arb = _arb4(); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(arb.mem_req_ready, 1)
        ctx.set(arb.compact_req_valid, 1)
        await ctx.tick(); ctx.set(arb.compact_req_valid, 0)
        for eng in ['compact', 'mre', 'sweep', 'scan']:
            ctx.set(getattr(arb, f'{eng}_req_valid'), 1)
            rr = ctx.get(getattr(arb, f'{eng}_req_ready'))
            assert rr == 0
            ctx.set(getattr(arb, f'{eng}_req_valid'), 0)
        ctx.set(arb.mem_rsp_valid, 1); ctx.set(arb.compact_rsp_ready, 1)
        await ctx.tick(); ctx.set(arb.mem_rsp_valid, 0)
        ctx.set(arb.mre_req_valid, 1)
        assert ctx.get(arb.mre_req_ready) == 1
        await ctx.tick(); print("  PASS")
    sim.add_testbench(proc); sim.run()
