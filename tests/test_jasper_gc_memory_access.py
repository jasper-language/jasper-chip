# tests/test_jasper_gc_memory_access.py
from amaranth import *; from amaranth.sim import Simulator
from amaranth.back import rtlil
from rtl.jasper_gc_memory_access import MemoryAccess


def test_elab():
    m = Module(); m.submodules.ma = MemoryAccess(read_latency=4, write_latency=2)
    rtlil.convert(m, ports=[]); print("  OK")


def test_read_latency():
    """Read request → response after read_latency cycles."""
    ma = MemoryAccess(read_latency=4, write_latency=2)
    sim = Simulator(ma); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(ma.req_valid, 1); ctx.set(ma.req_is_write, 0)
        ctx.set(ma.req_addr, 0x1000); ctx.set(ma.req_tag, 42)
        ctx.set(ma.rsp_ready, 1)
        await ctx.tick(); ctx.set(ma.req_valid, 0)
        for cyc in range(10):
            if ctx.get(ma.rsp_valid):
                assert ctx.get(ma.rsp_tag) == 42, f"tag={ctx.get(ma.rsp_tag)}"
                print(f"  PASS (cyc={cyc})")
                return
            await ctx.tick()
        assert False, "no response"
    sim.add_testbench(proc); sim.run()


def test_backpressure():
    """Fill pipe + queue → req_ready=0."""
    ma = MemoryAccess(read_latency=4, write_latency=2, queue_depth=4)
    sim = Simulator(ma); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(ma.rsp_ready, 0)
        LD = ma.read_latency + 1  # pipe depth
        QD = ma.queue_depth
        total = LD + QD + 2  # enough to fill pipe + queue
        full_at = None
        for i in range(total):
            ctx.set(ma.req_valid, 1); ctx.set(ma.req_is_write, 0)
            ctx.set(ma.req_addr, 0x1000 + i * 4); ctx.set(ma.req_tag, i)
            await ctx.tick(); ctx.set(ma.req_valid, 0)
            ready = ctx.get(ma.req_ready)
            if ready == 0 and full_at is None:
                full_at = i
        assert full_at is not None, "never got full"
        print(f"  PASS (full at push {full_at}, LD={LD} QD={QD})")
    sim.add_testbench(proc); sim.run()


def test_read_data():
    """Read request returns deterministic data (addr ^ tag)."""
    ma = MemoryAccess(read_latency=4)
    sim = Simulator(ma); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(ma.req_valid, 1); ctx.set(ma.req_is_write, 0)
        ctx.set(ma.req_addr, 0x2000); ctx.set(ma.req_tag, 99)
        ctx.set(ma.rsp_ready, 1)
        await ctx.tick(); ctx.set(ma.req_valid, 0)
        for cyc in range(10):
            if ctx.get(ma.rsp_valid):
                data = ctx.get(ma.rsp_read_data)
                assert data == 0x2000 ^ 99, f"data={data}"
                break
            await ctx.tick()
        else: assert False
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_multi_requests():
    """Multiple requests queued, all get responses."""
    ma = MemoryAccess(read_latency=4, write_latency=2, queue_depth=8)
    sim = Simulator(ma); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick(); ctx.set(ma.rsp_ready, 1)
        for tag in [10, 20, 30]:
            ctx.set(ma.req_valid, 1); ctx.set(ma.req_is_write, 0)
            ctx.set(ma.req_addr, 0x1000 + tag); ctx.set(ma.req_tag, tag)
            await ctx.tick(); ctx.set(ma.req_valid, 0)
        tags = []
        for _ in range(50):
            if ctx.get(ma.rsp_valid):
                tags.append(ctx.get(ma.rsp_tag))
                if len(tags) >= 3: break
            await ctx.tick()
        assert tags == [10, 20, 30], f"got {tags}"
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_write_data_stored():
    """Write with data → data echoed on response."""
    ma = MemoryAccess(read_latency=4, write_latency=2, queue_depth=4)
    sim = Simulator(ma); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(ma.req_valid, 1); ctx.set(ma.req_is_write, 1)
        ctx.set(ma.req_addr, 0x3000); ctx.set(ma.req_tag, 7)
        ctx.set(ma.req_write_data, 0xA55A); ctx.set(ma.rsp_ready, 1)
        await ctx.tick(); ctx.set(ma.req_valid, 0)
        for cyc in range(10):
            if ctx.get(ma.rsp_valid):
                assert ctx.get(ma.rsp_tag) == 7
                assert ctx.get(ma.rsp_read_data) == 0xA55A, \
                    f"data={ctx.get(ma.rsp_read_data)}"
                print("  PASS")
                return
            await ctx.tick()
        assert False, "no response"
    sim.add_testbench(proc); sim.run()


def test_read_data_generated():
    """Read → data is deterministic (addr ^ tag)."""
    ma = MemoryAccess(read_latency=4)
    sim = Simulator(ma); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(ma.req_valid, 1); ctx.set(ma.req_is_write, 0)
        ctx.set(ma.req_addr, 0x4000); ctx.set(ma.req_tag, 55)
        ctx.set(ma.rsp_ready, 1)
        await ctx.tick(); ctx.set(ma.req_valid, 0)
        for cyc in range(10):
            if ctx.get(ma.rsp_valid):
                data = ctx.get(ma.rsp_read_data)
                expected = 0x4000 ^ 55
                assert data == expected, f"data={data} expected={expected}"
                assert data != 0, "read data should be non-zero"
                break
            await ctx.tick()
        else: assert False
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_write_data_backpressure():
    """Write with data under backpressure."""
    ma = MemoryAccess(read_latency=4, write_latency=2, queue_depth=4)
    sim = Simulator(ma); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(ma.rsp_ready, 0)
        sent = []
        for i in range(ma.queue_depth):
            ctx.set(ma.req_valid, 1); ctx.set(ma.req_is_write, 1)
            ctx.set(ma.req_addr, 0x5000 + i * 4); ctx.set(ma.req_tag, i)
            ctx.set(ma.req_write_data, 0x100 + i)
            if ctx.get(ma.req_ready):
                sent.append(i)
            await ctx.tick()
            ctx.set(ma.req_valid, 0)
        assert len(sent) == ma.queue_depth, f"only {len(sent)} accepted"
        ctx.set(ma.req_valid, 0); ctx.set(ma.rsp_ready, 1)
        recv = []
        for _ in range(50):
            if ctx.get(ma.rsp_valid):
                recv.append((ctx.get(ma.rsp_tag), ctx.get(ma.rsp_read_data)))
                if len(recv) >= len(sent): break
            await ctx.tick()
        assert len(recv) == len(sent), f"recv {len(recv)} != sent {len(sent)}"
        for rtag, rdata in recv:
            assert rdata == 0x100 + rtag, f"tag={rtag} data={rdata} != {0x100 + rtag}"
        print("  PASS")
    sim.add_testbench(proc); sim.run()


def test_write_read_interleave():
    """Interleaved writes and reads, both with correct data."""
    ma = MemoryAccess(read_latency=4, write_latency=2, queue_depth=8)
    sim = Simulator(ma); sim.add_clock(1e-6)
    requests = [
        (0, 0x1000, 10, None),
        (1, 0x2000, 20, 0xDEAD),
        (0, 0x3000, 30, None),
        (1, 0x4000, 40, 0xBEEF),
    ]
    async def proc(ctx):
        await ctx.tick(); ctx.set(ma.rsp_ready, 1)
        for is_write, addr, tag, wdata in requests:
            ctx.set(ma.req_valid, 1); ctx.set(ma.req_is_write, is_write)
            ctx.set(ma.req_addr, addr); ctx.set(ma.req_tag, tag)
            if is_write:
                ctx.set(ma.req_write_data, wdata)
            await ctx.tick(); ctx.set(ma.req_valid, 0)
        for idx, (is_write, addr, tag, wdata) in enumerate(requests):
            for _ in range(20):
                if ctx.get(ma.rsp_valid):
                    rtag = ctx.get(ma.rsp_tag)
                    rdata = ctx.get(ma.rsp_read_data)
                    assert rtag == tag, f"req {idx}: tag {rtag} != {tag}"
                    if is_write:
                        assert rdata == wdata, \
                            f"req {idx}: write data {rdata} != {wdata}"
                    else:
                        expected = addr ^ tag
                        assert rdata == expected, \
                            f"req {idx}: read data {rdata} != {expected}"
                    await ctx.tick()
                    break
                await ctx.tick()
            else: assert False, f"req {idx}: no response"
        print("  PASS")
    sim.add_testbench(proc); sim.run()
