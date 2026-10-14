# tests/test_jasper_gc_chiplet_link.py
from amaranth import *; from amaranth.sim import Simulator
from amaranth.back import rtlil
from rtl.jasper_gc_chiplet_link import ChipletLink


def test_elab():
    m = Module()
    m.submodules.cl = ChipletLink()
    rtlil.convert(m, ports=[])
    print("  OK")


def _run(dut, proc):
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    sim.add_testbench(proc)
    sim.run()


def _run_sync(dut, proc):
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    sim.add_sync_process(proc)
    sim.run()


async def _send(ctx, dut, tag, addr=0x1000, is_write=0):
    """Send one request with proper handshake, returns True if accepted."""
    ctx.set(dut.req_valid, 1)
    ctx.set(dut.req_tag, tag)
    ctx.set(dut.req_addr, addr)
    ctx.set(dut.req_is_write, is_write)
    while not ctx.get(dut.req_ready):
        await ctx.tick()
        ctx.set(dut.req_valid, 1)
    await ctx.tick()
    ctx.set(dut.req_valid, 0)


def test_simple_read():
    """Single read, default simple mode, verify round-trip latency = 2*link_latency."""
    L = 5
    dut = ChipletLink(link_latency=L)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(dut.rsp_ready, 1)
        await _send(ctx, dut, 42, 0x1000, 0)
        for cyc in range(2 * L + 5):
            if ctx.get(dut.rsp_valid):
                assert ctx.get(dut.rsp_tag) == 42
                assert not ctx.get(dut.rsp_error)
                assert cyc >= 2 * L - 1
                print(f"  PASS (cyc={cyc})")
                return
            await ctx.tick()
        assert False, "no response"
    _run(dut, proc)


def test_simple_write():
    """Single write, verify response."""
    L = 5
    dut = ChipletLink(link_latency=L)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(dut.rsp_ready, 1)
        await _send(ctx, dut, 7, 0x2000, 1)
        for cyc in range(2 * L + 5):
            if ctx.get(dut.rsp_valid):
                assert ctx.get(dut.rsp_tag) == 7
                print(f"  PASS (cyc={cyc})")
                return
            await ctx.tick()
        assert False, "no response"
    _run(dut, proc)


def test_backpressure():
    """Fill pipeline → req_ready=0 in simple mode."""
    L = 4; Q = 4
    dut = ChipletLink(link_latency=L, queue_depth=Q)
    capacity = 2 * L + Q
    async def proc(ctx):
        await ctx.tick()
        ctx.set(dut.rsp_ready, 0)
        full_at = None
        for i in range(capacity + 3):
            ctx.set(dut.req_valid, 1)
            ctx.set(dut.req_tag, i)
            ctx.set(dut.req_addr, 0x1000 + i * 4)
            await ctx.tick()
            ctx.set(dut.req_valid, 0)
            if not ctx.get(dut.req_ready) and full_at is None:
                full_at = i
        assert full_at is not None, "never got full"
        print(f"  PASS (full at {full_at}, cap={capacity})")
    _run(dut, proc)


def test_response_backpressure_hold():
    """Hold rsp_ready=0 → rsp_valid stays high, data not lost."""
    L = 3; Q = 2
    dut = ChipletLink(link_latency=L, queue_depth=Q)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(dut.rsp_ready, 0)
        await _send(ctx, dut, 1, 0x1000, 0)
        resp_seen = False
        for cyc in range(2 * L + Q + 5):
            if ctx.get(dut.rsp_valid):
                resp_seen = True
                assert ctx.get(dut.rsp_tag) == 1
                break
            await ctx.tick()
        assert resp_seen, "response never appeared"
        for _ in range(5):
            assert ctx.get(dut.rsp_valid), "rsp_valid dropped"
            assert ctx.get(dut.rsp_tag) == 1
            await ctx.tick()
        ctx.set(dut.rsp_ready, 1)
        await ctx.tick()
        assert not ctx.get(dut.rsp_valid), "rsp_valid still high after consume"
        print("  PASS")
    _run(dut, proc)


def test_no_loss():
    """Send N requests, receive N responses, all tags accounted for."""
    N = 10
    dut = ChipletLink(link_latency=3, queue_depth=8)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(dut.rsp_ready, 1)
        sent_tags = set()
        rcvd_tags = []
        for i in range(N):
            ctx.set(dut.req_valid, 1)
            ctx.set(dut.req_tag, i)
            ctx.set(dut.req_addr, 0x1000 + i * 4)
            ctx.set(dut.req_is_write, 0)
            while not ctx.get(dut.req_ready):
                if ctx.get(dut.rsp_valid):
                    rcvd_tags.append(ctx.get(dut.rsp_tag))
                await ctx.tick()
                ctx.set(dut.req_valid, 1)
            await ctx.tick()
            ctx.set(dut.req_valid, 0)
            sent_tags.add(i)
            if ctx.get(dut.rsp_valid):
                rcvd_tags.append(ctx.get(dut.rsp_tag))
        for _ in range(200):
            if ctx.get(dut.rsp_valid):
                rcvd_tags.append(ctx.get(dut.rsp_tag))
                if len(rcvd_tags) == N:
                    break
            await ctx.tick()
        assert len(rcvd_tags) == N, f"got {len(rcvd_tags)}/{N}"
        assert set(rcvd_tags) == sent_tags, f"sent={sent_tags} rcvd={set(rcvd_tags)}"
        print(f"  PASS ({N} req/resp)")
    _run(dut, proc)


def test_credit_mode():
    """Credit mode: credits decrement on accept, increment on return."""
    MC = 8; CRL = 2
    dut = ChipletLink(mode="credit", max_credits=MC,
                      credit_return_latency=CRL, link_latency=3, queue_depth=8)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(dut.rsp_ready, 1)
        assert ctx.get(dut.dbg_credits) == MC
        await _send(ctx, dut, 1, 0x1000, 0)
        assert ctx.get(dut.dbg_credits) == MC - 1
        for _ in range(2 * dut.link_latency + CRL + 10):
            await ctx.tick()
        assert ctx.get(dut.dbg_credits) == MC, f"credits={ctx.get(dut.dbg_credits)}"
        print("  PASS")
    _run(dut, proc)


def test_credit_exhaustion():
    """Run out of credits → req_ready=0."""
    MC = 4
    dut = ChipletLink(mode="credit", max_credits=MC,
                      credit_return_latency=10, link_latency=2, queue_depth=4)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(dut.rsp_ready, 1)
        for i in range(MC):
            await _send(ctx, dut, i, 0x1000 + i, 0)
        assert ctx.get(dut.dbg_credits) == 0, f"credits={ctx.get(dut.dbg_credits)}"
        ctx.set(dut.req_valid, 1)
        ctx.set(dut.req_tag, 99)
        await ctx.tick()
        assert not ctx.get(dut.req_ready), "req_ready should be 0"
        ctx.set(dut.req_valid, 0)
        print("  PASS")
    _run(dut, proc)


def test_credit_return():
    """After remote dequeues, credits are returned after credit_return_latency."""
    MC = 2; CRL = 3
    dut = ChipletLink(mode="credit", max_credits=MC,
                      credit_return_latency=CRL, link_latency=2, queue_depth=2)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(dut.rsp_ready, 1)
        for i in range(MC):
            await _send(ctx, dut, i, 0x1000 + i, 0)
        assert ctx.get(dut.dbg_credits) == 0
        for _ in range(2 * dut.link_latency + CRL + 10):
            await ctx.tick()
            if ctx.get(dut.rsp_valid):
                await ctx.tick()
                ctx.set(dut.rsp_ready, 1)
            else:
                await ctx.tick()
        assert ctx.get(dut.dbg_credits) > 0, "credits never returned"
        print(f"  PASS (credits={ctx.get(dut.dbg_credits)})")
    _run(dut, proc)


def test_error_injection():
    """Enable error injection → some responses have rsp_error=1."""
    dut = ChipletLink(error_rate=128, link_latency=3, queue_depth=4)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(dut.rsp_ready, 1)
        errors = 0
        total = 50
        for i in range(total):
            await _send(ctx, dut, i, 0x1000 + i, 0)
        for _ in range(200):
            if ctx.get(dut.rsp_valid):
                if ctx.get(dut.rsp_error):
                    errors += 1
                await ctx.tick()
                ctx.set(dut.rsp_ready, 1)
            else:
                await ctx.tick()
        assert errors > 0, "no errors injected"
        print(f"  PASS ({errors}/{total} errors)")
    _run(dut, proc)


def test_tag_preservation():
    """16-bit tag is preserved end-to-end through the pipeline."""
    N = 16
    dut = ChipletLink(link_latency=4, queue_depth=8)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(dut.rsp_ready, 1)
        sent = []
        rcvd = []
        for tag in range(N):
            ctx.set(dut.req_valid, 1)
            ctx.set(dut.req_tag, tag)
            ctx.set(dut.req_addr, 0x1000 + tag)
            ctx.set(dut.req_is_write, 0)
            while not ctx.get(dut.req_ready):
                if ctx.get(dut.rsp_valid):
                    rcvd.append(ctx.get(dut.rsp_tag))
                await ctx.tick()
                ctx.set(dut.req_valid, 1)
            await ctx.tick()
            ctx.set(dut.req_valid, 0)
            sent.append(tag)
            if ctx.get(dut.rsp_valid):
                rcvd.append(ctx.get(dut.rsp_tag))
        for _ in range(200):
            if ctx.get(dut.rsp_valid):
                rcvd.append(ctx.get(dut.rsp_tag))
                if len(rcvd) == N:
                    break
            await ctx.tick()
        assert rcvd == sent, f"tag mismatch: sent={sent} rcvd={rcvd}"
        print("  PASS")
    _run(dut, proc)


def test_configurable_latency():
    """Different link_latency values produce correct round-trip times."""
    for L in (1, 3, 8):
        dut = ChipletLink(link_latency=L)
        async def proc(ctx, L=L):
            await ctx.tick()
            ctx.set(dut.rsp_ready, 1)
            await _send(ctx, dut, 99, 0x1000, 0)
            for cyc in range(2 * L + 5):
                if ctx.get(dut.rsp_valid):
                    assert ctx.get(dut.rsp_tag) == 99
                    assert cyc >= 2 * L - 1, f"L={L} cyc={cyc}"
                    break
                await ctx.tick()
            else:
                assert False, f"L={L} no response"
        _run(dut, proc)
    print("  PASS")


def test_profile_presets():
    """Test with different parameter combinations (profiles)."""
    profiles = [
        ("standard",   5, 4),
        ("low_latency", 2, 8),
        ("high_bw",    8, 16),
        ("extreme",    12, 32),
    ]
    for name, L, Q in profiles:
        dut = ChipletLink(link_latency=L, queue_depth=Q)
        async def proc(ctx, L=L, Q=Q, name=name):
            await ctx.tick()
            ctx.set(dut.rsp_ready, 1)
            await _send(ctx, dut, 1, 0x1000, 0)
            ok = False
            for cyc in range(2 * L + Q + 10):
                if ctx.get(dut.rsp_valid):
                    assert ctx.get(dut.rsp_tag) == 1
                    ok = True
                    break
                await ctx.tick()
            assert ok, f"{name}: no response"
            ctx.get(dut.dbg_link_busy)
            ctx.get(dut.dbg_queue_level)
        _run(dut, proc)
    print("  PASS")


def test_phy_num_lanes():
    dut = ChipletLink(link_latency=3, num_lanes=4)
    def proc():
        yield dut.req_valid.eq(1); yield dut.req_tag.eq(42); yield
        yield dut.req_valid.eq(0)
        for _ in range(20):
            v = yield dut.rsp_valid
            if v:
                t = yield dut.rsp_tag
                assert t == 42, f"tag={t}"
                return
            yield
        assert False, "timeout"
    _run_sync(dut, proc)


def test_phy_training():
    dut = ChipletLink(link_latency=3, training_cycles=5)
    def proc():
        rr = yield dut.req_ready
        lt = yield dut.dbg_link_training
        lr = yield dut.dbg_link_ready
        assert rr == 0, f"req_ready={rr}"
        assert lt == 1, f"training={lt}"
        assert lr == 0, f"link_ready={lr}"
        for _ in range(10):
            yield
        rr2 = yield dut.req_ready
        lt2 = yield dut.dbg_link_training
        assert lt2 == 0, f"training={lt2}"
        assert rr2 == 1, f"req_ready={rr2}"
    _run_sync(dut, proc)


def test_phy_serdes_delay():
    dut = ChipletLink(link_latency=2, serdes_delay=3)
    def proc():
        yield dut.req_valid.eq(1); yield dut.req_tag.eq(77); yield
        yield dut.req_valid.eq(0)
        for i in range(30):
            v = yield dut.rsp_valid
            if v:
                assert i >= 5, f"early at {i}"
                return
            yield
        assert False, "timeout"
    _run_sync(dut, proc)


def test_phy_ber():
    dut = ChipletLink(link_latency=2, ber_rate=128, queue_depth=8)
    def proc():
        yield dut.req_valid.eq(1); yield dut.req_tag.eq(99); yield
        yield dut.req_valid.eq(0)
        for _ in range(20):
            v = yield dut.rsp_valid
            if v:
                be = yield dut.dbg_bit_errors
                yield
                return
            yield
    _run_sync(dut, proc)


def test_phy_combined():
    dut = ChipletLink(link_latency=2, num_lanes=2, training_cycles=3, serdes_delay=1)
    def proc():
        yield dut.req_valid.eq(1); yield dut.req_tag.eq(0xAA)
        for _ in range(10):
            rr = yield dut.req_ready
            if rr:
                break
            yield
        yield dut.req_valid.eq(0)
        for _ in range(40):
            v = yield dut.rsp_valid
            if v:
                t = yield dut.rsp_tag
                assert t == 0xAA, f"tag={t}"
                return
            yield
        assert False, "timeout"
    _run_sync(dut, proc)


def test_phy_backward_compat():
    dut = ChipletLink()
    def proc():
        yield dut.req_valid.eq(1); yield dut.req_tag.eq(0xBB); yield
        yield dut.req_valid.eq(0)
        for _ in range(20):
            v = yield dut.rsp_valid
            if v:
                t = yield dut.rsp_tag
                assert t == 0xBB, f"tag={t}"
                return
            yield
        assert False, "timeout"
    _run_sync(dut, proc)
