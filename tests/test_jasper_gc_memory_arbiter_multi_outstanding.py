# Multi-outstanding arbiter tests: configurable N-outstanding with RRB.
from amaranth import *; from amaranth.sim import Simulator
from rtl.jasper_gc_memory_arbiter import MemoryRequestArbiter


def _make(max_os):
    m = Module(); arb = MemoryRequestArbiter(max_outstanding=max_os)
    m.submodules.arb = arb; return m, arb


def _req(arb, engine, tag=0):
    setattr(arb, f'{engine}_req_valid', 1)
    setattr(arb, f'{engine}_req_tag', tag)


def test_elab_d1():
    """Default params (max_outstanding=1) elaborate without error."""
    m, arb = _make(1); sim = Simulator(m); sim.add_clock(1e-6)
    sim.run()


def test_elab_d4():
    """max_outstanding=4 elaborates without error."""
    m, arb = _make(4); sim = Simulator(m); sim.add_clock(1e-6)
    sim.run()


def test_single_outstanding_backward_compat():
    """max_outstanding=1 behaves like v0.1: single outstanding, blocks others."""
    m, arb = _make(1); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(arb.mem_req_ready, 1)
        ctx.set(arb.scan_req_valid, 1)
        await ctx.tick(); ctx.set(arb.scan_req_valid, 0)
        for eng in ['compact', 'mre', 'sweep', 'scan']:
            ctx.set(getattr(arb, f'{eng}_req_valid'), 1)
            assert ctx.get(getattr(arb, f'{eng}_req_ready')) == 0
            ctx.set(getattr(arb, f'{eng}_req_valid'), 0)
        ctx.set(arb.mem_rsp_valid, 1); ctx.set(arb.scan_rsp_ready, 1)
        await ctx.tick(); ctx.set(arb.mem_rsp_valid, 0)
        ctx.set(arb.compact_req_valid, 1)
        assert ctx.get(arb.compact_req_ready) == 1
        await ctx.tick()
    sim.add_testbench(proc); sim.run()


def test_two_outstanding_compact_mre():
    """max_outstanding=2: compact + mre in flight without waiting."""
    m, arb = _make(2); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(arb.mem_req_ready, 1)
        ctx.set(arb.compact_req_valid, 1)
        await ctx.tick(); ctx.set(arb.compact_req_valid, 0)
        ctx.set(arb.mre_req_valid, 1)
        assert ctx.get(arb.mre_req_ready) == 1
        await ctx.tick(); ctx.set(arb.mre_req_valid, 0)
        assert ctx.get(arb.dbg_outstanding) == 2
        ctx.set(arb.mem_rsp_valid, 1); ctx.set(arb.compact_rsp_ready, 1)
        await ctx.tick(); ctx.set(arb.mem_rsp_valid, 0)
        assert ctx.get(arb.dbg_outstanding) == 1
        ctx.set(arb.mem_rsp_valid, 1); ctx.set(arb.mre_rsp_ready, 1)
        await ctx.tick(); ctx.set(arb.mem_rsp_valid, 0)
        assert ctx.get(arb.dbg_outstanding) == 0
    sim.add_testbench(proc); sim.run()


def test_four_outstanding_all_engines():
    """max_outstanding=4: all 4 engines in flight."""
    m, arb = _make(4); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(arb.mem_req_ready, 1)
        tags = {}
        for eng in ['compact', 'mre', 'sweep', 'scan']:
            ctx.set(getattr(arb, f'{eng}_req_valid'), 1)
            assert ctx.get(getattr(arb, f'{eng}_req_ready')) == 1
            tags[eng] = ctx.get(arb.mem_req_tag)
            await ctx.tick()
            ctx.set(getattr(arb, f'{eng}_req_valid'), 0)
        assert ctx.get(arb.dbg_outstanding) == 4
        for eng in ['compact', 'mre', 'sweep', 'scan']:
            ctx.set(arb.mem_rsp_valid, 1)
            ctx.set(arb.mem_rsp_tag, tags[eng])
            ctx.set(getattr(arb, f'{eng}_rsp_ready'), 1)
            await ctx.tick()
            assert ctx.get(getattr(arb, f'{eng}_rsp_valid')) == 1
            ctx.set(getattr(arb, f'{eng}_rsp_ready'), 0)
            ctx.set(arb.mem_rsp_valid, 0)
        assert ctx.get(arb.dbg_outstanding) == 0
    sim.add_testbench(proc); sim.run()


def test_backpressure_at_max():
    """max_outstanding=2: 3rd request rejected."""
    m, arb = _make(2); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(arb.mem_req_ready, 1)
        ctx.set(arb.compact_req_valid, 1)
        await ctx.tick(); ctx.set(arb.compact_req_valid, 0)
        ctx.set(arb.mre_req_valid, 1)
        await ctx.tick(); ctx.set(arb.mre_req_valid, 0)
        assert ctx.get(arb.dbg_outstanding) == 2
        ctx.set(arb.sweep_req_valid, 1)
        assert ctx.get(arb.sweep_req_ready) == 0
        ctx.set(arb.sweep_req_valid, 0)
        ctx.set(arb.mem_rsp_valid, 1); ctx.set(arb.compact_rsp_ready, 1)
        await ctx.tick(); ctx.set(arb.mem_rsp_valid, 0)
        assert ctx.get(arb.dbg_outstanding) == 1
        ctx.set(arb.sweep_req_valid, 1)
        assert ctx.get(arb.sweep_req_ready) == 1
        await ctx.tick(); ctx.set(arb.sweep_req_valid, 0)
        assert ctx.get(arb.dbg_outstanding) == 2
    sim.add_testbench(proc); sim.run()


def test_response_order_preserved():
    """Responses route to correct engine via RRB regardless of order."""
    m, arb = _make(4); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(arb.mem_req_ready, 1)
        for eng, tag in [('scan', 10), ('sweep', 20), ('mre', 30)]:
            ctx.set(getattr(arb, f'{eng}_req_valid'), 1)
            ctx.set(getattr(arb, f'{eng}_req_tag'), tag)
            await ctx.tick()
            ctx.set(getattr(arb, f'{eng}_req_valid'), 0)
        # scan @ RRB[0], sweep @ RRB[1], mre @ RRB[2]
        # Return MRE response first (tag packed with pos=2)
        ctx.set(arb.mem_rsp_valid, 1)
        ctx.set(arb.mem_rsp_tag, (30 << 2) | 2)
        ctx.set(arb.mre_rsp_ready, 1)
        await ctx.tick()
        assert ctx.get(arb.mre_rsp_valid) == 1
        assert ctx.get(arb.scan_rsp_valid) == 0
        assert ctx.get(arb.sweep_rsp_valid) == 0
        ctx.set(arb.mem_rsp_valid, 0); ctx.set(arb.mre_rsp_ready, 0)
        # Sweep response (tag packed with pos=1)
        ctx.set(arb.mem_rsp_valid, 1)
        ctx.set(arb.mem_rsp_tag, (20 << 2) | 1)
        ctx.set(arb.sweep_rsp_ready, 1)
        await ctx.tick()
        assert ctx.get(arb.sweep_rsp_valid) == 1
        ctx.set(arb.mem_rsp_valid, 0); ctx.set(arb.sweep_rsp_ready, 0)
        # Scan response (tag packed with pos=0)
        ctx.set(arb.mem_rsp_valid, 1)
        ctx.set(arb.mem_rsp_tag, (10 << 2) | 0)
        ctx.set(arb.scan_rsp_ready, 1)
        await ctx.tick()
        assert ctx.get(arb.scan_rsp_valid) == 1
        ctx.set(arb.mem_rsp_valid, 0)
    sim.add_testbench(proc); sim.run()


def test_rrb_wraparound():
    """Fill and drain RRB, fill again."""
    m, arb = _make(4); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(arb.mem_req_ready, 1)
        req_tags = {}
        for eng in ['compact', 'mre', 'sweep']:
            ctx.set(getattr(arb, f'{eng}_req_valid'), 1)
            req_tags[eng] = ctx.get(arb.mem_req_tag)
            await ctx.tick()
            ctx.set(getattr(arb, f'{eng}_req_valid'), 0)
        assert ctx.get(arb.dbg_outstanding) == 3
        for eng in ['compact', 'mre', 'sweep']:
            ctx.set(arb.mem_rsp_valid, 1)
            ctx.set(arb.mem_rsp_tag, req_tags[eng])
            ctx.set(getattr(arb, f'{eng}_rsp_ready'), 1)
            await ctx.tick()
            ctx.set(arb.mem_rsp_valid, 0)
            ctx.set(getattr(arb, f'{eng}_rsp_ready'), 0)
        assert ctx.get(arb.dbg_outstanding) == 0
        for eng in ['scan', 'compact']:
            ctx.set(getattr(arb, f'{eng}_req_valid'), 1)
            await ctx.tick()
            ctx.set(getattr(arb, f'{eng}_req_valid'), 0)
        assert ctx.get(arb.dbg_outstanding) == 2
    sim.add_testbench(proc); sim.run()


def test_tag_round_trip():
    """Engine tags survive pack/unpack through RRB (bits above rrb_tag_lsb_width preserved)."""
    m, arb = _make(4); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(arb.mem_req_ready, 1)
        ctx.set(arb.compact_req_valid, 1)
        ctx.set(arb.compact_req_tag, 0x1234)
        packed = ctx.get(arb.mem_req_tag)
        await ctx.tick(); ctx.set(arb.compact_req_valid, 0)
        ctx.set(arb.mem_rsp_valid, 1)
        ctx.set(arb.mem_rsp_tag, packed)
        ctx.set(arb.compact_rsp_ready, 1)
        await ctx.tick()
        assert ctx.get(arb.compact_rsp_valid) == 1
        assert ctx.get(arb.compact_rsp_tag) == 0x1234
        ctx.set(arb.mem_rsp_valid, 0)
    sim.add_testbench(proc); sim.run()


def test_rrb_slot_reuse():
    """Freed RRB slot is reused for a subsequent request."""
    m, arb = _make(2); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(arb.mem_req_ready, 1)
        ctx.set(arb.scan_req_valid, 1)
        ctx.set(arb.scan_req_tag, 100)
        await ctx.tick(); ctx.set(arb.scan_req_valid, 0)
        ctx.set(arb.sweep_req_valid, 1)
        ctx.set(arb.sweep_req_tag, 200)
        await ctx.tick(); ctx.set(arb.sweep_req_valid, 0)
        assert ctx.get(arb.dbg_outstanding) == 2
        # Consume scan (RRB[0])
        ctx.set(arb.mem_rsp_valid, 1)
        ctx.set(arb.mem_rsp_tag, (100 << 1) | 0)
        ctx.set(arb.scan_rsp_ready, 1)
        await ctx.tick(); ctx.set(arb.mem_rsp_valid, 0)
        ctx.set(arb.scan_rsp_ready, 0)
        assert ctx.get(arb.dbg_outstanding) == 1
        # New request should reuse slot 0
        ctx.set(arb.mre_req_valid, 1)
        ctx.set(arb.mre_req_tag, 300)
        await ctx.tick(); ctx.set(arb.mre_req_valid, 0)
        assert ctx.get(arb.dbg_outstanding) == 2
        # Return responses: mre (tag with pos=0), sweep (tag with pos=1)
        ctx.set(arb.mem_rsp_valid, 1)
        ctx.set(arb.mem_rsp_tag, (300 << 1) | 0)
        ctx.set(arb.mre_rsp_ready, 1)
        await ctx.tick()
        assert ctx.get(arb.mre_rsp_valid) == 1
        ctx.set(arb.mem_rsp_valid, 0); ctx.set(arb.mre_rsp_ready, 0)
        ctx.set(arb.mem_rsp_valid, 1)
        ctx.set(arb.mem_rsp_tag, (200 << 1) | 1)
        ctx.set(arb.sweep_rsp_ready, 1)
        await ctx.tick()
        assert ctx.get(arb.sweep_rsp_valid) == 1
        ctx.set(arb.mem_rsp_valid, 0)
    sim.add_testbench(proc); sim.run()


def test_rsp_tag_engine_specific():
    """Only the target engine's rsp_tag updates; unrelated engines see correct tag."""
    m, arb = _make(4); sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(arb.mem_req_ready, 1)
        ctx.set(arb.sweep_req_valid, 1); ctx.set(arb.sweep_req_tag, 0xAA)
        await ctx.tick(); ctx.set(arb.sweep_req_valid, 0)
        ctx.set(arb.scan_req_valid, 1); ctx.set(arb.scan_req_tag, 0xBB)
        await ctx.tick(); ctx.set(arb.scan_req_valid, 0)
        ctx.set(arb.mem_rsp_valid, 1)
        ctx.set(arb.mem_rsp_tag, (0xAA << 2) | 0)
        ctx.set(arb.sweep_rsp_ready, 1)
        await ctx.tick()
        assert ctx.get(arb.sweep_rsp_valid) == 1
        assert ctx.get(arb.sweep_rsp_tag) == 0xAA
        assert ctx.get(arb.scan_rsp_valid) == 0
        ctx.set(arb.mem_rsp_valid, 0); ctx.set(arb.sweep_rsp_ready, 0)
    sim.add_testbench(proc); sim.run()
