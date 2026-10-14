# tests/test_gc_chip_perf_benchmark.py
# GC chip throughput benchmarks — measure baseline without accelerator
import pytest
from amaranth import *
from amaranth.sim import Simulator
from rtl.gc_scan_coproc import GCScanCoProc
from rtl.gc_sweep_coproc import GCSweepCoProc
from rtl.gc_chip_clean import GCCleanChipTop
from rtl.gc_chip_move import GCMoveChipTop
from rtl.gc_mv_coproc import MV_QUERY, MV_RELOC
from rtl.isa import GC_NEW, GC_DROP, GC_RELOC

pytestmark = pytest.mark.slow


async def _cmd_transaction(ctx, chip, op, rd, rs1, rs2, tag):
    """Full command transaction: send + wait for + take response. Returns (data, cycles)."""
    cyc = 0
    ctx.set(chip.cmd_op[0], op)
    ctx.set(chip.cmd_rd[0], rd)
    ctx.set(chip.cmd_rs1[0], rs1)
    ctx.set(chip.cmd_rs2[0], rs2)
    ctx.set(chip.cmd_tag[0], tag)
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
    return d, cyc


def test_scan_card_throughput():
    """Scan chip card ingestion with burst (keep valid high until accepted)."""
    N = 200
    scan = GCScanCoProc(ncores=1, consume_every=1, batch_size=1)
    sim = Simulator(scan)
    sim.add_clock(1e-6)
    async def proc(ctx):
        accepted = 0
        total_cyc = 0
        for i in range(N):
            ctx.set(scan.wb_addr[0], i * 64)
            ctx.set(scan.wb_data[0], i)
            ctx.set(scan.wb_valid[0], 1)
            while not ctx.get(scan.wb_ready[0]):
                await ctx.tick()
                total_cyc += 1
            accepted += 1
            ctx.set(scan.wb_valid[0], 0)
            await ctx.tick()
            total_cyc += 1
        for _ in range(N):
            await ctx.tick()
        rate = accepted / total_cyc if total_cyc else 0
        print(f"  Scan burst ({N} cards): accepted={accepted}/{N} cyc={total_cyc} rate={rate:.4f} cmds/cyc")
    sim.add_testbench(proc)
    sim.run()


def test_scan_card_backtoback():
    """Scan card throughput: keep valid high for all N, no gaps."""
    N = 200
    scan = GCScanCoProc(ncores=1, consume_every=1, batch_size=1)
    sim = Simulator(scan)
    sim.add_clock(1e-6)
    async def proc(ctx):
        accepted = 0
        ctx.set(scan.wb_addr[0], 0)
        ctx.set(scan.wb_data[0], 0)
        ctx.set(scan.wb_valid[0], 0)
        await ctx.tick()
        for i in range(N):
            ctx.set(scan.wb_addr[0], i * 64)
            ctx.set(scan.wb_data[0], i)
            ctx.set(scan.wb_valid[0], 1)
            await ctx.tick()
            if ctx.get(scan.wb_ready[0]):
                accepted += 1
        ctx.set(scan.wb_valid[0], 0)
        for _ in range(N):
            await ctx.tick()
        rate = accepted / N
        print(f"  Scan back-to-back ({N} cards): accepted={accepted}/{N} rate={rate:.4f} cmds/cyc")
    sim.add_testbench(proc)
    sim.run()


def test_sweep_mark_throughput():
    """Sweep card mark: keep valid high until accepted."""
    N = 200
    sweep = GCSweepCoProc(ncores=1, engine_latency=0)
    sim = Simulator(sweep)
    sim.add_clock(1e-6)
    async def proc(ctx):
        accepted = 0
        total_cyc = 0
        for i in range(N):
            ctx.set(sweep.card_in_card_id, i)
            ctx.set(sweep.card_in_core_id, 0)
            ctx.set(sweep.card_in_epoch, 0)
            ctx.set(sweep.card_in_valid, 1)
            while not ctx.get(sweep.card_in_ready):
                await ctx.tick()
                total_cyc += 1
            accepted += 1
            ctx.set(sweep.card_in_valid, 0)
            await ctx.tick()
            total_cyc += 1
        for _ in range(N):
            await ctx.tick()
        rate = accepted / total_cyc if total_cyc else 0
        print(f"  Sweep mark burst ({N} cards): accepted={accepted}/{N} cyc={total_cyc} rate={rate:.4f} cmds/cyc")
    sim.add_testbench(proc)
    sim.run()


def test_clean_gcnew_lat0():
    """GC_NEW engine_latency=0: per-transaction throughput."""
    chip = GCCleanChipTop(ncores=1, engine_latency=0)
    sim = Simulator(chip)
    sim.add_clock(1e-6)
    N = 50
    async def proc(ctx):
        total_cyc = 0
        for i in range(N):
            _, cyc = await _cmd_transaction(ctx, chip, GC_NEW, 1, i, 0, i)
            total_cyc += cyc
        rate = N / total_cyc if total_cyc else 0
        print(f"  GC_NEW (lat=0, txn): {N}/{total_cyc} cyc rate={rate:.4f} cmds/cyc")
    sim.add_testbench(proc)
    sim.run()


def test_clean_gcnew_lat4():
    """GC_NEW engine_latency=4: per-transaction throughput."""
    chip = GCCleanChipTop(ncores=1, engine_latency=4)
    sim = Simulator(chip)
    sim.add_clock(1e-6)
    N = 20
    async def proc(ctx):
        total_cyc = 0
        for i in range(N):
            _, cyc = await _cmd_transaction(ctx, chip, GC_NEW, 1, i, 0, i)
            total_cyc += cyc
        rate = N / total_cyc if total_cyc else 0
        print(f"  GC_NEW (lat=4, txn): {N}/{total_cyc} cyc rate={rate:.4f} cmds/cyc")
    sim.add_testbench(proc)
    sim.run()


def test_move_query():
    """MV_QUERY engine_latency=0: per-transaction throughput."""
    move = GCMoveChipTop(ncores=1)
    sim = Simulator(move)
    sim.add_clock(1e-6)
    N = 50
    async def proc(ctx):
        total_cyc = 0
        for i in range(N):
            _, cyc = await _cmd_transaction(ctx, move, MV_QUERY, 1, 0x1000 + i * 4, 0, i)
            total_cyc += cyc
        rate = N / total_cyc if total_cyc else 0
        print(f"  MV_QUERY (txn): {N}/{total_cyc} cyc rate={rate:.4f} cmds/cyc")
    sim.add_testbench(proc)
    sim.run()


def test_reloc_throughput():
    """GC_RELOC engine_latency=0: allocate + relocate throughput."""
    chip = GCCleanChipTop(ncores=1, engine_latency=0)
    sim = Simulator(chip)
    sim.add_clock(1e-6)
    N = 20
    async def proc(ctx):
        # Must drain reloc_out stream so pending slots free up for subsequent RELOCs
        ctx.set(chip.reloc_out_ready, 1)
        handles = []
        for i in range(N):
            d, _ = await _cmd_transaction(ctx, chip, GC_NEW, 1, i, 0, i)
            handles.append(d)
        total_cyc = 0
        for i, h in enumerate(handles):
            _, cyc = await _cmd_transaction(ctx, chip, GC_RELOC, 0, h, 0x10000000 + i * 4, 0x30 + i)
            total_cyc += cyc
        rate = len(handles) / total_cyc if total_cyc else 0
        print(f"  GC_RELOC (lat=0, txn): {len(handles)}/{total_cyc} cyc rate={rate:.4f} cmds/cyc")
    sim.add_testbench(proc)
    sim.run()


if __name__ == "__main__":
    print("=" * 60)
    print("GC Chip Performance Benchmark (without accelerator)")
    print("=" * 60)
    tests = [
        ("Scan card burst",          test_scan_card_throughput),
        ("Scan back-to-back",        test_scan_card_backtoback),
        ("Sweep mark burst",         test_sweep_mark_throughput),
        ("GC_NEW lat=0",             test_clean_gcnew_lat0),
        ("GC_NEW lat=4",             test_clean_gcnew_lat4),
        ("MV_QUERY",                 test_move_query),
        ("GC_RELOC",                 test_reloc_throughput),
    ]
    for name, fn in tests:
        print(f"\n[{name}]")
        try:
            fn()
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"  FAIL: {e}")
