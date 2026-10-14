# tests/test_jasper_gc_coherent_access.py
# CoherentAccess v0.1 — 19 unit tests for coherent load/store latency model.
from amaranth import *; from amaranth.sim import Simulator
from amaranth.back import rtlil
from rtl.jasper_gc_coherent_access import CoherentAccess

HIT_ADDR = 0x40; MISS_ADDR = 0x00
UNSUPP_STATUS = 5; FAULT_STATUS = 4; OK_STATUS = 0


def _ca(**kw):
    m = Module(); ca = CoherentAccess(**kw); m.submodules.ca = ca
    return m, ca


# ─── 1. Elaboration ────────────────────────────────────────────────
def test_elab():
    m, ca = _ca()
    rtlil.convert(m, ports=[])
    print("  OK")


# ─── 2. Read hit ───────────────────────────────────────────────────
def test_read_hit():
    m, ca = _ca(hit_latency=2, miss_latency=5)
    sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(ca.rsp_ready, 1)
        ctx.set(ca.req_valid, 1); ctx.set(ca.req_is_write, 0)
        ctx.set(ca.req_addr, HIT_ADDR); ctx.set(ca.req_tag, 10)
        await ctx.tick(); ctx.set(ca.req_valid, 0)
        for _ in range(20):
            if ctx.get(ca.rsp_valid):
                assert ctx.get(ca.rsp_tag) == 10
                assert ctx.get(ca.rsp_hit) == 1
                assert ctx.get(ca.rsp_status) == OK_STATUS
                assert ctx.get(ca.rsp_read_data) == 0xCAFE
                assert ctx.get(ca.rsp_error) == 0
                return
            await ctx.tick()
        assert False
    sim.add_testbench(proc); sim.run(); print("  PASS")


# ─── 3. Read miss ──────────────────────────────────────────────────
def test_read_miss():
    m, ca = _ca(hit_latency=2, miss_latency=5)
    sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(ca.rsp_ready, 1)
        ctx.set(ca.req_valid, 1); ctx.set(ca.req_is_write, 0)
        ctx.set(ca.req_addr, MISS_ADDR); ctx.set(ca.req_tag, 20)
        await ctx.tick(); ctx.set(ca.req_valid, 0)
        for _ in range(20):
            if ctx.get(ca.rsp_valid):
                assert ctx.get(ca.rsp_tag) == 20
                assert ctx.get(ca.rsp_hit) == 0
                assert ctx.get(ca.rsp_status) == OK_STATUS
                return
            await ctx.tick()
        assert False
    sim.add_testbench(proc); sim.run(); print("  PASS")


# ─── 4. Write ──────────────────────────────────────────────────────
def test_write():
    m, ca = _ca(enable_write=True)
    sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(ca.rsp_ready, 1)
        ctx.set(ca.req_valid, 1); ctx.set(ca.req_is_write, 1)
        ctx.set(ca.req_addr, HIT_ADDR); ctx.set(ca.req_tag, 30)
        await ctx.tick(); ctx.set(ca.req_valid, 0)
        for _ in range(20):
            if ctx.get(ca.rsp_valid):
                assert ctx.get(ca.rsp_tag) == 30
                assert ctx.get(ca.rsp_status) == OK_STATUS
                assert ctx.get(ca.rsp_read_data) == 0
                return
            await ctx.tick()
        assert False
    sim.add_testbench(proc); sim.run(); print("  PASS")


# ─── 5. Write disabled → UNSUPPORTED ───────────────────────────────
def test_write_disabled_unsupported():
    m, ca = _ca(enable_write=False)
    sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(ca.rsp_ready, 1)
        ctx.set(ca.req_valid, 1); ctx.set(ca.req_is_write, 1)
        ctx.set(ca.req_addr, HIT_ADDR); ctx.set(ca.req_tag, 40)
        await ctx.tick(); ctx.set(ca.req_valid, 0)
        for _ in range(20):
            if ctx.get(ca.rsp_valid):
                assert ctx.get(ca.rsp_tag) == 40
                assert ctx.get(ca.rsp_status) == UNSUPP_STATUS
                assert ctx.get(ca.rsp_hit) == 1
                return
            await ctx.tick()
        assert False
    sim.add_testbench(proc); sim.run(); print("  PASS")


# ─── 6. Request backpressure: queue full ───────────────────────────
def test_request_backpressure_queue_full():
    m, ca = _ca(hit_latency=2, queue_depth=4)
    sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(ca.rsp_ready, 0)
        rej = None
        for i in range(20):
            ctx.set(ca.req_valid, 1)
            ctx.set(ca.req_addr, HIT_ADDR)
            ctx.set(ca.req_tag, i)
            ctx.set(ca.req_is_write, 0)
            await ctx.tick()
            if not ctx.get(ca.req_ready) and rej is None:
                rej = i
        assert rej is not None, "never got rejected"
        assert rej > 0, f"rejected at {rej}"
        print(f"  PASS (first reject at push {rej})")
    sim.add_testbench(proc); sim.run()


# ─── 7. Response hold under backpressure ───────────────────────────
def test_response_backpressure_hold():
    """rsp_valid stays high when rsp_ready=0; drops when rsp_ready=1."""
    m, ca = _ca(hit_latency=2)
    sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(ca.rsp_ready, 0)
        ctx.set(ca.req_valid, 1); ctx.set(ca.req_is_write, 0)
        ctx.set(ca.req_addr, MISS_ADDR); ctx.set(ca.req_tag, 50)
        await ctx.tick(); ctx.set(ca.req_valid, 0)
        # Wait for response to arrive (rsp_ready=0, so it will hold)
        for _ in range(30):
            if ctx.get(ca.rsp_valid):
                break
            await ctx.tick()
        else:
            assert False, "response never arrived"
        # Hold for 3 cycles
        for _ in range(3):
            assert ctx.get(ca.rsp_valid) == 1, "rsp_valid dropped"
            await ctx.tick()
        # Release
        ctx.set(ca.rsp_ready, 1)
        await ctx.tick()
        # Should now be consumed
        assert ctx.get(ca.rsp_valid) == 0, "response not consumed"
        print("  PASS")
    sim.add_testbench(proc); sim.run()


# ─── 8. Response data stable under backpressure ────────────────────
def test_response_data_stable():
    m, ca = _ca(hit_latency=2)
    sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(ca.rsp_ready, 0)
        ctx.set(ca.req_valid, 1); ctx.set(ca.req_is_write, 0)
        ctx.set(ca.req_addr, HIT_ADDR); ctx.set(ca.req_tag, 60)
        await ctx.tick(); ctx.set(ca.req_valid, 0)
        for _ in range(30):
            if ctx.get(ca.rsp_valid):
                break
            await ctx.tick()
        else:
            assert False
        data = ctx.get(ca.rsp_read_data)
        assert data == 0xCAFE
        for _ in range(3):
            await ctx.tick()
            assert ctx.get(ca.rsp_read_data) == data, "data changed"
        ctx.set(ca.rsp_ready, 1)
        await ctx.tick()
        print("  PASS")
    sim.add_testbench(proc); sim.run()


# ─── 9. Response tag stable under backpressure ─────────────────────
def test_response_tag_stable():
    m, ca = _ca(hit_latency=2)
    sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(ca.rsp_ready, 0)
        ctx.set(ca.req_valid, 1); ctx.set(ca.req_is_write, 0)
        ctx.set(ca.req_addr, HIT_ADDR); ctx.set(ca.req_tag, 70)
        await ctx.tick(); ctx.set(ca.req_valid, 0)
        for _ in range(30):
            if ctx.get(ca.rsp_valid):
                break
            await ctx.tick()
        else:
            assert False
        tag = ctx.get(ca.rsp_tag)
        assert tag == 70
        for _ in range(3):
            await ctx.tick()
            assert ctx.get(ca.rsp_tag) == tag, "tag changed"
        ctx.set(ca.rsp_ready, 1)
        await ctx.tick()
        print("  PASS")
    sim.add_testbench(proc); sim.run()


# ─── 10. Read tag/epoch preserved ──────────────────────────────────
def test_read_tag_epoch():
    m, ca = _ca()
    sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(ca.rsp_ready, 1)
        ctx.set(ca.req_valid, 1); ctx.set(ca.req_is_write, 0)
        ctx.set(ca.req_addr, HIT_ADDR); ctx.set(ca.req_tag, 0xA5)
        ctx.set(ca.req_epoch, 0x7B)
        await ctx.tick(); ctx.set(ca.req_valid, 0)
        for _ in range(20):
            if ctx.get(ca.rsp_valid):
                assert ctx.get(ca.rsp_tag) == 0xA5
                assert ctx.get(ca.rsp_epoch) == 0x7B
                assert ctx.get(ca.rsp_hit) == 1
                assert ctx.get(ca.rsp_status) == OK_STATUS
                return
            await ctx.tick()
        assert False
    sim.add_testbench(proc); sim.run(); print("  PASS")


# ─── 11. Write tag/epoch preserved ─────────────────────────────────
def test_write_tag_epoch():
    m, ca = _ca(enable_write=True)
    sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(ca.rsp_ready, 1)
        ctx.set(ca.req_valid, 1); ctx.set(ca.req_is_write, 1)
        ctx.set(ca.req_addr, HIT_ADDR); ctx.set(ca.req_tag, 0xC3)
        ctx.set(ca.req_epoch, 0x1E)
        await ctx.tick(); ctx.set(ca.req_valid, 0)
        for _ in range(20):
            if ctx.get(ca.rsp_valid):
                assert ctx.get(ca.rsp_tag) == 0xC3
                assert ctx.get(ca.rsp_epoch) == 0x1E
                assert ctx.get(ca.rsp_status) == OK_STATUS
                return
            await ctx.tick()
        assert False
    sim.add_testbench(proc); sim.run(); print("  PASS")


# ─── 12. Accepted == response ──────────────────────────────────────
def test_accepted_equals_response():
    """Every accepted request tag appears exactly once in responses."""
    m, ca = _ca(hit_latency=2)
    sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(ca.rsp_ready, 1)
        sent, rcvd = [], []
        for tag in range(4):
            if ctx.get(ca.rsp_valid):
                rcvd.append(ctx.get(ca.rsp_tag))
            ctx.set(ca.req_valid, 1)
            ctx.set(ca.req_addr, HIT_ADDR)
            ctx.set(ca.req_tag, tag)
            ctx.set(ca.req_is_write, 0)
            await ctx.tick()
            if ctx.get(ca.req_ready):
                sent.append(tag)
        ctx.set(ca.req_valid, 0)
        drain_cyc = 0
        while len(rcvd) < len(sent):
            if ctx.get(ca.rsp_valid):
                rcvd.append(ctx.get(ca.rsp_tag))
            drain_cyc += 1
            if drain_cyc > 100:
                assert False, f"drain timeout: sent={sent} rcvd={rcvd}"
            if len(rcvd) >= len(sent):
                break
            await ctx.tick()
        assert sorted(sent) == sorted(rcvd), f"sent={sent} rcvd={rcvd}"
        print(f"  PASS (accepted={len(sent)})")
    sim.add_testbench(proc); sim.run()


# ─── 13. No missing response ───────────────────────────────────────
def test_no_missing_response():
    """All accepted requests produce a response — no tag missing."""
    m, ca = _ca(hit_latency=2)
    sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(ca.rsp_ready, 1)
        sent, rcvd = [], []
        for tag in range(4):
            if ctx.get(ca.rsp_valid):
                rcvd.append(ctx.get(ca.rsp_tag))
            ctx.set(ca.req_valid, 1)
            ctx.set(ca.req_addr, HIT_ADDR)
            ctx.set(ca.req_tag, tag)
            ctx.set(ca.req_is_write, 0)
            await ctx.tick()
            if ctx.get(ca.req_ready):
                sent.append(tag)
        ctx.set(ca.req_valid, 0)
        drain_cyc = 0
        while len(rcvd) < len(sent):
            if ctx.get(ca.rsp_valid):
                rcvd.append(ctx.get(ca.rsp_tag))
            drain_cyc += 1
            if drain_cyc > 100:
                assert False, f"drain timeout: sent={sent} rcvd={rcvd}"
            if len(rcvd) >= len(sent):
                break
            await ctx.tick()
        missing = set(sent) - set(rcvd)
        assert not missing, f"missing tags: {missing}"
        print("  PASS")
    sim.add_testbench(proc); sim.run()


# ─── 14. No duplicate response ─────────────────────────────────────
def test_no_duplicate_response():
    """No tag appears in more than one response."""
    m, ca = _ca(hit_latency=2)
    sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(ca.rsp_ready, 1)
        sent, seen = [], set()
        for tag in range(4):
            if ctx.get(ca.rsp_valid):
                t = ctx.get(ca.rsp_tag)
                assert t not in seen, f"duplicate tag {t}"
                seen.add(t)
            ctx.set(ca.req_valid, 1)
            ctx.set(ca.req_addr, HIT_ADDR)
            ctx.set(ca.req_tag, tag)
            ctx.set(ca.req_is_write, 0)
            await ctx.tick()
            if ctx.get(ca.req_ready):
                sent.append(tag)
        ctx.set(ca.req_valid, 0)
        drain_cyc = 0
        while len(seen) < len(sent):
            if ctx.get(ca.rsp_valid):
                t = ctx.get(ca.rsp_tag)
                assert t not in seen, f"duplicate tag {t}"
                seen.add(t)
            drain_cyc += 1
            if drain_cyc > 100:
                assert False, f"drain timeout: sent={sent} seen={seen}"
            if len(seen) >= len(sent):
                break
            await ctx.tick()
        print("  PASS")
    sim.add_testbench(proc); sim.run()


# ─── 15. Mixed read/write sequence ─────────────────────────────────
def test_mixed_read_write_sequence():
    """Interleaved reads and writes all produce responses in order."""
    m, ca = _ca(enable_write=True, hit_latency=2)
    sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(ca.rsp_ready, 1)
        seq = [(0, HIT_ADDR, 10), (1, HIT_ADDR, 11),
               (0, MISS_ADDR, 12), (1, MISS_ADDR, 13)]
        rcvd = []
        for is_w, addr, tag in seq:
            if ctx.get(ca.rsp_valid):
                rcvd.append(ctx.get(ca.rsp_tag))
            ctx.set(ca.req_valid, 1)
            ctx.set(ca.req_is_write, is_w)
            ctx.set(ca.req_addr, addr)
            ctx.set(ca.req_tag, tag)
            await ctx.tick()
        ctx.set(ca.req_valid, 0)
        drain_cyc = 0
        while len(rcvd) < len(seq):
            if ctx.get(ca.rsp_valid):
                rcvd.append(ctx.get(ca.rsp_tag))
            drain_cyc += 1
            if drain_cyc > 100:
                assert False, f"drain timeout: rcvd={rcvd}"
            if len(rcvd) >= len(seq):
                break
            await ctx.tick()
        assert rcvd == [10, 11, 12, 13], f"got {rcvd}"
        print("  PASS")
    sim.add_testbench(proc); sim.run()


# ─── 16. Hit/miss correctly reported ───────────────────────────────
def test_hit_miss_report():
    m, ca = _ca()
    sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(ca.rsp_ready, 1)
        for idx, (addr, expect_hit) in enumerate(
            [(HIT_ADDR, 1), (MISS_ADDR, 0), (0x80, 0), (0xC0, 1)]):
            # drain any pending response
            if ctx.get(ca.rsp_valid):
                pass
            ctx.set(ca.req_valid, 1)
            ctx.set(ca.req_addr, addr)
            ctx.set(ca.req_tag, idx)
            ctx.set(ca.req_is_write, 0)
            await ctx.tick(); ctx.set(ca.req_valid, 0)
            for _ in range(30):
                if ctx.get(ca.rsp_valid):
                    assert ctx.get(ca.rsp_hit) == expect_hit, \
                        f"addr={addr:#x} hit={ctx.get(ca.rsp_hit)}"
                    assert ctx.get(ca.rsp_tag) == idx
                    break
                await ctx.tick()
            else:
                assert False, f"no response for tag {idx}"
        print("  PASS")
    sim.add_testbench(proc); sim.run()


# ─── 17. Fault injection ───────────────────────────────────────────
def test_fault_injection():
    """Request with fault_tag returns FAULT status."""
    m, ca = _ca(enable_error_injection=True, fault_tag=0xFF)
    sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(ca.rsp_ready, 1)
        ctx.set(ca.req_valid, 1); ctx.set(ca.req_is_write, 0)
        ctx.set(ca.req_addr, HIT_ADDR); ctx.set(ca.req_tag, 0xFF)
        await ctx.tick(); ctx.set(ca.req_valid, 0)
        for _ in range(20):
            if ctx.get(ca.rsp_valid):
                assert ctx.get(ca.rsp_tag) == 0xFF
                assert ctx.get(ca.rsp_status) == FAULT_STATUS
                assert ctx.get(ca.rsp_error) == 1
                return
            await ctx.tick()
        assert False
    sim.add_testbench(proc); sim.run(); print("  PASS")


# ─── 18. UNSUPPORTED for disabled write ────────────────────────────
def test_unsupported_status():
    m, ca = _ca(enable_write=False)
    sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(ca.rsp_ready, 1)
        ctx.set(ca.req_valid, 1); ctx.set(ca.req_is_write, 1)
        ctx.set(ca.req_addr, HIT_ADDR); ctx.set(ca.req_tag, 0xAA)
        await ctx.tick(); ctx.set(ca.req_valid, 0)
        for _ in range(20):
            if ctx.get(ca.rsp_valid):
                assert ctx.get(ca.rsp_tag) == 0xAA
                assert ctx.get(ca.rsp_status) == UNSUPP_STATUS
                assert ctx.get(ca.rsp_error) == 1
                return
            await ctx.tick()
        assert False
    sim.add_testbench(proc); sim.run(); print("  PASS")


# ─── 19. Read after write sequence ─────────────────────────────────
def test_read_after_write_sequence():
    """Read after write — both complete normally in sequence."""
    m, ca = _ca(enable_write=True, hit_latency=2)
    sim = Simulator(m); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(ca.rsp_ready, 1)
        # Write
        ctx.set(ca.req_valid, 1); ctx.set(ca.req_is_write, 1)
        ctx.set(ca.req_addr, HIT_ADDR); ctx.set(ca.req_tag, 10)
        await ctx.tick(); ctx.set(ca.req_valid, 0)
        for _ in range(10):
            if ctx.get(ca.rsp_valid):
                assert ctx.get(ca.rsp_tag) == 10
                assert ctx.get(ca.rsp_status) == OK_STATUS
                break
            await ctx.tick()
        else:
            assert False
        # Read after write
        ctx.set(ca.req_valid, 1); ctx.set(ca.req_is_write, 0)
        ctx.set(ca.req_addr, HIT_ADDR); ctx.set(ca.req_tag, 11)
        await ctx.tick(); ctx.set(ca.req_valid, 0)
        for _ in range(10):
            if ctx.get(ca.rsp_valid):
                assert ctx.get(ca.rsp_tag) == 11
                assert ctx.get(ca.rsp_status) == OK_STATUS
                assert ctx.get(ca.rsp_hit) == 1
                print("  PASS")
                return
            await ctx.tick()
        assert False
    sim.add_testbench(proc); sim.run()
