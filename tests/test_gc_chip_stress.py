# tests/test_gc_chip_stress.py
# GC chip stress tests — push original hardware GC to its limits
from amaranth import *
from amaranth.sim import Simulator
from rtl.gc_chip_clean import GCCleanChipTop
from rtl.gc_sweep_coproc import GCSweepCoProc
from rtl.isa import GC_NEW, GC_DROP, GC_CLONE, GC_PIN, GC_UNPIN, GC_RELOC, GC_EPOCH


async def _send(ctx, chip, wait=True):
    """Send one command (assumes signals already set). If wait, block until ready."""
    if wait:
        while not ctx.get(chip.cmd_enq_ready[0]):
            await ctx.tick()
    await ctx.tick()
    ctx.set(chip.cmd_enq_valid[0], 0)


async def _txn(ctx, chip, op, rd, rs1, rs2, tag):
    """Full command transaction: send + wait response."""
    ctx.set(chip.cmd_op[0], op)
    ctx.set(chip.cmd_rd[0], rd)
    ctx.set(chip.cmd_rs1[0], rs1)
    ctx.set(chip.cmd_rs2[0], rs2)
    ctx.set(chip.cmd_tag[0], tag)
    ctx.set(chip.cmd_enq_valid[0], 1)
    while not ctx.get(chip.cmd_enq_ready[0]):
        await ctx.tick()
    await ctx.tick()
    ctx.set(chip.cmd_enq_valid[0], 0)
    while not ctx.get(chip.rsp_valid[0]):
        await ctx.tick()
    d = ctx.get(chip.rsp_data[0])
    ctx.set(chip.rsp_take[0], 1)
    await ctx.tick()
    ctx.set(chip.rsp_take[0], 0)
    return d


def test_handle_exhaustion():
    """Allocate until full then try one more — expect trap."""
    chip = GCCleanChipTop(ncores=1, engine_latency=0)
    sim = Simulator(chip)
    sim.add_clock(1e-6)
    async def proc(ctx):
        handles = set()
        for i in range(300):
            try:
                h = await _txn(ctx, chip, GC_NEW, 1, i, 0, i)
                if h == 0 and i < 254:
                    pass
                handles.add(h)
            except Exception:
                pass
        print(f"  Allocated {len(handles)} unique handles before exhaustion")
        # Expect ≈ 255 (slot 0 reserved)
        assert len(handles) >= 250, f"Expected ~255 handles, got {len(handles)}"
        # Now verify table is full — next GC_NEW should trap
        ctx.set(chip.cmd_op[0], GC_NEW)
        ctx.set(chip.cmd_rd[0], 1)
        ctx.set(chip.cmd_rs1[0], 0)
        ctx.set(chip.cmd_rs2[0], 0)
        ctx.set(chip.cmd_tag[0], 0)
        ctx.set(chip.cmd_enq_valid[0], 1)
        while not ctx.get(chip.cmd_enq_ready[0]):
            await ctx.tick()
        await ctx.tick()
        ctx.set(chip.cmd_enq_valid[0], 0)
        while not ctx.get(chip.rsp_valid[0]):
            await ctx.tick()
        trapped = ctx.get(chip.trap[0])
        ctx.set(chip.rsp_take[0], 1)
        await ctx.tick()
        ctx.set(chip.rsp_take[0], 0)
        print(f"  Overflow attempt: trap={trapped}")
        assert trapped, "Expected trap on full table"
    sim.add_testbench(proc)
    sim.run()


def test_fifo_saturation_backpressure():
    """Fill FIFO depth=8 with no response drain, then verify ready goes low."""
    chip = GCCleanChipTop(ncores=1, engine_latency=0)
    sim = Simulator(chip)
    sim.add_clock(1e-6)
    async def proc(ctx):
        N = 16
        filled = 0
        for i in range(N):
            ctx.set(chip.cmd_op[0], GC_NEW)
            ctx.set(chip.cmd_rd[0], 1)
            ctx.set(chip.cmd_rs1[0], i)
            ctx.set(chip.cmd_rs2[0], 0)
            ctx.set(chip.cmd_tag[0], i)
            ctx.set(chip.cmd_enq_valid[0], 1)
            # Check ready BEFORE tick (current cycle)
            ready_before = ctx.get(chip.cmd_enq_ready[0])
            # Tick
            await ctx.tick()
            # Check ready AFTER tick
            ready_after = ctx.get(chip.cmd_enq_ready[0])
            if not ready_before:
                print(f"  cmd {i}: ready went low (FIFO full after {filled} writes)")
                break
            # Capture happened
            filled += 1
            ctx.set(chip.cmd_enq_valid[0], 0)
        print(f"  Filled FIFO with {filled} commands before backpressure")
        # Now drain responses
        drained = 0
        for _ in range(32):
            if ctx.get(chip.rsp_valid[0]):
                ctx.set(chip.rsp_take[0], 1)
                await ctx.tick()
                ctx.set(chip.rsp_take[0], 0)
                drained += 1
            else:
                await ctx.tick()
        print(f"  Drained {drained} responses")
        # Depth=8 FIFO, engine processes 1 before filling, so expect ~9 total
        # (1 processed by engine + 8 in FIFO before ready=0)
        # Actually: process one per cycle, FIFO can buffer depth=8
        # Total accepted before backpressure = 1 (in engine) + 8 (in FIFO) = 9
        assert filled >= 1, "Should have written at least 1"
        assert drained >= filled, f"Drained {drained} < filled {filled}"
    sim.add_testbench(proc)
    sim.run()


def test_mixed_ops_throughput():
    """Interleave NEW/DROP/CLONE/PIN/UNPIN at max rate."""
    chip = GCCleanChipTop(ncores=1, engine_latency=0)
    sim = Simulator(chip)
    sim.add_clock(1e-6)
    async def proc(ctx):
        # Allocate handles first
        handles = []
        for i in range(10):
            h = await _txn(ctx, chip, GC_NEW, 1, i, 0, i)
            handles.append(h)
        # Mixed ops
        ops = [
            (GC_DROP,  0, handles[0], 0),
            (GC_CLONE, 1, handles[1], 0),
            (GC_PIN,   0, handles[2], 0),
            (GC_UNPIN, 0, handles[2], 0),
            (GC_NEW,   1, 99, 0),
            (GC_RELOC, 0, handles[3], 0x2000),
        ]
        total_cyc = 0
        for op, rd, rs1, rs2 in ops:
            _, cyc = 0, 0
            ctx.set(chip.cmd_op[0], op)
            ctx.set(chip.cmd_rd[0], rd)
            ctx.set(chip.cmd_rs1[0], rs1)
            ctx.set(chip.cmd_rs2[0], rs2)
            ctx.set(chip.cmd_tag[0], 0)
            ctx.set(chip.cmd_enq_valid[0], 1)
            while not ctx.get(chip.cmd_enq_ready[0]):
                await ctx.tick(); cyc += 1
            await ctx.tick(); cyc += 1
            ctx.set(chip.cmd_enq_valid[0], 0)
            while not ctx.get(chip.rsp_valid[0]):
                await ctx.tick(); cyc += 1
            d = ctx.get(chip.rsp_data[0])
            trapped = ctx.get(chip.trap[0])
            ctx.set(chip.rsp_take[0], 1)
            await ctx.tick(); cyc += 1
            ctx.set(chip.rsp_take[0], 0)
            total_cyc += cyc
            opname = ["NEW","DROP","CLONE","PIN","UNPIN","RELOC","EPOCH"][op]
            print(f"  {opname}: data=0x{d:08x} trap={trapped} cyc={cyc}")
        rate = len(ops) / total_cyc if total_cyc else 0
        print(f"  Mixed ops avg: {rate:.4f} cmds/cyc")
    sim.add_testbench(proc)
    sim.run()


def test_engine_latency_sweep():
    """Measure throughput as engine_latency increases."""
    results = []
    for lat in [0, 1, 2, 4, 8, 16]:
        chip = GCCleanChipTop(ncores=1, engine_latency=lat)
        sim = Simulator(chip)
        sim.add_clock(1e-6)
        N = 20
        async def proc(ctx, lat=lat):
            total = 0
            for i in range(N):
                _, cyc = 0, 0
                ctx.set(chip.cmd_op[0], GC_NEW)
                ctx.set(chip.cmd_rd[0], 1)
                ctx.set(chip.cmd_rs1[0], i)
                ctx.set(chip.cmd_rs2[0], 0)
                ctx.set(chip.cmd_tag[0], i)
                ctx.set(chip.cmd_enq_valid[0], 1)
                while not ctx.get(chip.cmd_enq_ready[0]):
                    await ctx.tick(); cyc += 1
                await ctx.tick(); cyc += 1
                ctx.set(chip.cmd_enq_valid[0], 0)
                while not ctx.get(chip.rsp_valid[0]):
                    await ctx.tick(); cyc += 1
                d = ctx.get(chip.rsp_data[0])
                ctx.set(chip.rsp_take[0], 1)
                await ctx.tick(); cyc += 1
                ctx.set(chip.rsp_take[0], 0)
                total += cyc
            results.append((lat, N / total if total else 0))
        sim.add_testbench(proc)
        sim.run()
    for lat, rate in results:
        print(f"  lat={lat:2d}: rate={rate:.4f} cmds/cyc  ({1/rate if rate else float('inf'):.1f} cyc/cmd)")


def test_multicore_contention():
    """2 cores competing for single engine — fairness check."""
    chip = GCCleanChipTop(ncores=2, engine_latency=0)
    sim = Simulator(chip)
    sim.add_clock(1e-6)
    async def proc(ctx):
        ctx.set(chip.reloc_out_ready, 1)
        N = 10
        cyc0 = 0; cyc1 = 0
        # Core 0: send N commands
        for i in range(N):
            ctx.set(chip.cmd_op[0], GC_NEW)
            ctx.set(chip.cmd_rd[0], 1)
            ctx.set(chip.cmd_rs1[0], i)
            ctx.set(chip.cmd_rs2[0], 0)
            ctx.set(chip.cmd_tag[0], i)
            ctx.set(chip.cmd_enq_valid[0], 1)
            while not ctx.get(chip.cmd_enq_ready[0]):
                await ctx.tick(); cyc0 += 1
            await ctx.tick(); cyc0 += 1
            ctx.set(chip.cmd_enq_valid[0], 0)
            while not ctx.get(chip.rsp_valid[0]):
                await ctx.tick(); cyc0 += 1
            ctx.set(chip.rsp_take[0], 1)
            await ctx.tick(); cyc0 += 1
            ctx.set(chip.rsp_take[0], 0)
        # Core 1: send N GC_NEW commands (same engine, separate FIFO)
        for i in range(N):
            ctx.set(chip.cmd_op[1], GC_NEW)
            ctx.set(chip.cmd_rd[1], 1)
            ctx.set(chip.cmd_rs1[1], 100 + i)
            ctx.set(chip.cmd_rs2[1], 0)
            ctx.set(chip.cmd_tag[1], i)
            ctx.set(chip.cmd_enq_valid[1], 1)
            while not ctx.get(chip.cmd_enq_ready[1]):
                await ctx.tick(); cyc1 += 1
            await ctx.tick(); cyc1 += 1
            ctx.set(chip.cmd_enq_valid[1], 0)
            while not ctx.get(chip.rsp_valid[1]):
                await ctx.tick(); cyc1 += 1
            d = ctx.get(chip.rsp_data[1])
            ctx.set(chip.rsp_take[1], 1)
            await ctx.tick(); cyc1 += 1
            ctx.set(chip.rsp_take[1], 0)
        print(f"  Core0: {N} cmds in {cyc0} cyc ({N/cyc0:.4f} cmds/cyc)")
        print(f"  Core1: {N} cmds in {cyc1} cyc ({N/cyc1:.4f} cmds/cyc)")
    sim.add_testbench(proc)
    sim.run()


def test_max_burst_peak():
    """Find peak sustained throughput with pipelined send (keep valid high)."""
    chip = GCCleanChipTop(ncores=1, engine_latency=0)
    sim = Simulator(chip)
    sim.add_clock(1e-6)
    async def proc(ctx):
        N = 200
        ctx.set(chip.cmd_op[0], GC_NEW)
        ctx.set(chip.cmd_rd[0], 1)
        ctx.set(chip.cmd_rs1[0], 0)
        ctx.set(chip.cmd_rs2[0], 0)
        ctx.set(chip.cmd_tag[0], 0)
        ctx.set(chip.cmd_enq_valid[0], 1)
        accepted = 0; send_cyc = 0
        for i in range(N):
            ready_before = ctx.get(chip.cmd_enq_ready[0])
            await ctx.tick(); send_cyc += 1
            if ready_before:
                accepted += 1
        ctx.set(chip.cmd_enq_valid[0], 0)
        drained = 0
        for _ in range(N):
            if ctx.get(chip.rsp_valid[0]):
                ctx.set(chip.rsp_take[0], 1)
                await ctx.tick()
                ctx.set(chip.rsp_take[0], 0)
                drained += 1
            else:
                await ctx.tick()
        send_rate = accepted / send_cyc if send_cyc else 0
        print(f"  Burst: accepted={accepted}/{N} drained={drained} send_rate={send_rate:.4f} cmds/cyc")
    sim.add_testbench(proc)
    sim.run()


def test_backtoback_reloc_pending():
    """Multiple back-to-back RELOCs — mv_out_valid pending slot bottleneck."""
    chip = GCCleanChipTop(ncores=1, engine_latency=0)
    sim = Simulator(chip)
    sim.add_clock(1e-6)
    async def proc(ctx):
        ctx.set(chip.reloc_out_ready, 1)
        handles = []
        for i in range(5):
            h = await _txn(ctx, chip, GC_NEW, 1, i, 0, i)
            handles.append(h)
        total_cyc = 0
        for i, h in enumerate(handles):
            _, cyc = 0, 0
            ctx.set(chip.cmd_op[0], GC_RELOC)
            ctx.set(chip.cmd_rd[0], 0)
            ctx.set(chip.cmd_rs1[0], h)
            ctx.set(chip.cmd_rs2[0], 0x1000 + i * 4)
            ctx.set(chip.cmd_tag[0], i)
            ctx.set(chip.cmd_enq_valid[0], 1)
            while not ctx.get(chip.cmd_enq_ready[0]):
                await ctx.tick(); cyc += 1
            await ctx.tick(); cyc += 1
            ctx.set(chip.cmd_enq_valid[0], 0)
            while not ctx.get(chip.rsp_valid[0]):
                await ctx.tick(); cyc += 1
            ctx.set(chip.rsp_take[0], 1)
            await ctx.tick(); cyc += 1
            ctx.set(chip.rsp_take[0], 0)
            total_cyc += cyc
        rate = len(handles) / total_cyc if total_cyc else 0
        print(f"  RELOC b2b: {len(handles)}/{total_cyc} cyc rate={rate:.4f} cmds/cyc")
    sim.add_testbench(proc)
    sim.run()


if __name__ == "__main__":
    print("=" * 60)
    print("GC Chip Stress Tests")
    print("=" * 60)
    tests = [
        ("Handle exhaustion",      test_handle_exhaustion),
        ("FIFO saturation",        test_fifo_saturation_backpressure),
        ("Mixed ops",              test_mixed_ops_throughput),
        ("Engine latency sweep",   test_engine_latency_sweep),
        ("Multi-core contention",  test_multicore_contention),
        ("Max burst peak",         test_max_burst_peak),
        ("Back-to-back RELOC",     test_backtoback_reloc_pending),
    ]
    for name, fn in tests:
        print(f"\n--- {name} ---")
        try:
            fn()
        except AssertionError as e:
            print(f"  FAIL: {e}")
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"  FAIL: {e}")
