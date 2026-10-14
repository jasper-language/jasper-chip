# tests/test_gc_pipelined_throughput.py
# 精准测量 GCSweepCoProc 引擎吞吐：原始 vs Pipelined。
from amaranth import *
from amaranth.sim import Simulator
from rtl.gc_sweep_coproc import GCSweepCoProc
from rtl.gc_sweep_coproc_pipelined import GCSweepCoProcPipelined
from rtl.isa import GC_NEW, GC_RELOC


def test_back_to_back_original():
    print("  Original:")
    dut = GCSweepCoProc(ncores=1, fifo_depth=8)
    sim = Simulator(dut); sim.add_clock(1e-6)
    trace = []
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.rsp_take[0], 1); await ctx.tick()
        for i in range(6):
            ctx.set(dut.cmd_op[0], GC_NEW if i < 4 else GC_RELOC)
            ctx.set(dut.cmd_rd[0], i + 1)
            ctx.set(dut.cmd_rs1[0], (i * 4 + 0x100) & 0xFF or 1)
            ctx.set(dut.cmd_tag[0], i)
            ctx.set(dut.cmd_enq_valid[0], 1)
            await ctx.tick()
            ctx.set(dut.cmd_enq_valid[0], 0)
        for cyc in range(6):
            rv = ctx.get(dut.rsp_valid[0])
            rt = ctx.get(dut.rsp_tag[0]) if rv else 0
            trace.append(f"  cyc={cyc} rsp_v={rv} tag={rt}")
            if rv: ctx.set(dut.rsp_take[0], 1)
            await ctx.tick()
    sim.add_testbench(proc); sim.run()
    for l in trace: print(l)

def test_back_to_back_pipelined():
    print("  Pipelined:")
    dut = GCSweepCoProcPipelined(ncores=1, fifo_depth=8, rsp_fifo_depth=8)
    sim = Simulator(dut); sim.add_clock(1e-6)
    trace = []
    async def proc(ctx):
        await ctx.tick(); ctx.set(dut.rsp_take[0], 1); ctx.set(dut.mv_upd_ready[0], 1); await ctx.tick()
        for i in range(6):
            ctx.set(dut.cmd_op[0], GC_NEW if i < 4 else GC_RELOC)
            ctx.set(dut.cmd_rd[0], i + 1)
            ctx.set(dut.cmd_rs1[0], (i * 4 + 0x100) & 0xFF or 1)
            ctx.set(dut.cmd_tag[0], i)
            ctx.set(dut.cmd_enq_valid[0], 1)
            await ctx.tick()
            ctx.set(dut.cmd_enq_valid[0], 0)
        for cyc in range(6):
            rv = ctx.get(dut.rsp_valid[0])
            rt = ctx.get(dut.rsp_tag[0]) if rv else 0
            trace.append(f"  cyc={cyc} rsp_v={rv} tag={rt}")
            if rv: ctx.set(dut.rsp_take[0], 1)
            await ctx.tick()
    sim.add_testbench(proc); sim.run()
    for l in trace: print(l)


def test_sustained_original():
    print()
    print("  Original:")
    for fd in [4, 8]:
        dut = GCSweepCoProc(ncores=1, fifo_depth=fd)
        sim = Simulator(dut); sim.add_clock(1e-6)
        async def proc(ctx, fifo_d=fd):
            await ctx.tick(); ctx.set(dut.rsp_take[0], 1); await ctx.tick()
            issued = 0
            for i in range(8):
                ctx.set(dut.cmd_op[0], GC_NEW)
                ctx.set(dut.cmd_rd[0], i + 1)
                ctx.set(dut.cmd_rs1[0], (i * 4 + 0x100) & 0xFF or 1)
                ctx.set(dut.cmd_tag[0], i)
                ctx.set(dut.cmd_enq_valid[0], 1)
                await ctx.tick()
                if ctx.get(dut.cmd_enq_ready[0]): issued += 1
                ctx.set(dut.cmd_enq_valid[0], 0)
            ctx.set(dut.cmd_enq_valid[0], 0)
            responses = 0; first = None; last = None
            for cyc in range(50):
                rv = ctx.get(dut.rsp_valid[0])
                if rv:
                    if first is None: first = cyc
                    last = cyc; responses += 1
                    ctx.set(dut.rsp_take[0], 1)
                await ctx.tick()
                if not rv: ctx.set(dut.rsp_take[0], 1)
                if responses >= issued: break
            rate = responses / (last - first + 1) if last != first else 0
            print(f"    FIFO={fifo_d}: issued={issued}/8 drain_span={last-first+1 if last else 0}cyc rate={rate:.4f}/cyc")
        sim.add_testbench(proc); sim.run()

def test_sustained_pipelined():
    print("  Pipelined:")
    for fd in [4, 8]:
        dut = GCSweepCoProcPipelined(ncores=1, fifo_depth=fd, rsp_fifo_depth=8)
        sim = Simulator(dut); sim.add_clock(1e-6)
        async def proc(ctx, fifo_d=fd):
            await ctx.tick(); ctx.set(dut.rsp_take[0], 1); ctx.set(dut.mv_upd_ready[0], 1); await ctx.tick()
            issued = 0
            for i in range(8):
                ctx.set(dut.cmd_op[0], GC_NEW)
                ctx.set(dut.cmd_rd[0], i + 1)
                ctx.set(dut.cmd_rs1[0], (i * 4 + 0x100) & 0xFF or 1)
                ctx.set(dut.cmd_tag[0], i)
                ctx.set(dut.cmd_enq_valid[0], 1)
                await ctx.tick()
                if ctx.get(dut.cmd_enq_ready[0]): issued += 1
                ctx.set(dut.cmd_enq_valid[0], 0)
            ctx.set(dut.cmd_enq_valid[0], 0)
            responses = 0; first = None; last = None
            for cyc in range(50):
                rv = ctx.get(dut.rsp_valid[0])
                if rv:
                    if first is None: first = cyc
                    last = cyc; responses += 1
                    ctx.set(dut.rsp_take[0], 1)
                await ctx.tick()
                if not rv: ctx.set(dut.rsp_take[0], 1)
                if responses >= issued: break
            rate = responses / (last - first + 1) if last != first else 0
            print(f"    FIFO={fifo_d}: issued={issued}/8 drain_span={last-first+1 if last else 0}cyc rate={rate:.4f}/cyc")
        sim.add_testbench(proc); sim.run()


def test_continuous_peak():
    print()
    print("  [持续注入 200 周期]")
    for label, build in [
        ("Original ", lambda: GCSweepCoProc(ncores=1, fifo_depth=8)),
        ("Pipelined", lambda: GCSweepCoProcPipelined(ncores=1, fifo_depth=8, rsp_fifo_depth=8)),
    ]:
        dut = build()
        sim = Simulator(dut); sim.add_clock(1e-6)
        async def proc(ctx, lb=label):
            await ctx.tick()
            ctx.set(dut.rsp_take[0], 1)
            if lb == "Pipelined": ctx.set(dut.mv_upd_ready[0], 1)
            await ctx.tick()
            total = 200; accepted = 0; responses = 0
            for i in range(total):
                ctx.set(dut.cmd_op[0], GC_NEW if (i % 6) != 5 else GC_RELOC)
                ctx.set(dut.cmd_rd[0], (i % 31) + 1)
                ctx.set(dut.cmd_rs1[0], ((i * 4 + 0x100) & 0xFF) or 1)
                ctx.set(dut.cmd_rs2[0], ((i * 4 + 0x200) & 0xFF) or 1)
                ctx.set(dut.cmd_tag[0], i & 0xFF)
                ctx.set(dut.cmd_enq_valid[0], 1)
                rv = ctx.get(dut.rsp_valid[0])
                if rv:
                    responses += 1
                    ctx.set(dut.rsp_take[0], 1)
                await ctx.tick()
                if ctx.get(dut.cmd_enq_ready[0]): accepted += 1
                ctx.set(dut.cmd_enq_valid[0], 0)
            ctx.set(dut.cmd_enq_valid[0], 0)
            for cyc in range(200):
                rv = ctx.get(dut.rsp_valid[0])
                if rv:
                    responses += 1
                    ctx.set(dut.rsp_take[0], 1)
                await ctx.tick()
                if not rv:
                    ctx.set(dut.rsp_take[0], 1)
            print(f"    {lb}: accepted={accepted}/{total} responses={responses}/{total}")
        sim.add_testbench(proc); sim.run()


def test_single_txn_latency():
    print()
    print("  [单命令延迟]")
    for label, build in [
        ("Original ", lambda: GCSweepCoProc(ncores=1, fifo_depth=2)),
        ("Pipelined", lambda: GCSweepCoProcPipelined(ncores=1, fifo_depth=2, rsp_fifo_depth=8)),
    ]:
        dut = build()
        sim = Simulator(dut); sim.add_clock(1e-6)
        async def proc(ctx, lb=label):
            await ctx.tick()
            ctx.set(dut.rsp_take[0], 1)
            if lb == "Pipelined": ctx.set(dut.mv_upd_ready[0], 1)
            await ctx.tick()
            for op_name, op in [("GC_NEW", GC_NEW), ("GC_RELOC", GC_RELOC)]:
                ctx.set(dut.cmd_op[0], op)
                ctx.set(dut.cmd_rd[0], 1)
                ctx.set(dut.cmd_rs1[0], 0x100)
                ctx.set(dut.cmd_rs2[0], 0x200)
                ctx.set(dut.cmd_tag[0], 42)
                ctx.set(dut.cmd_enq_valid[0], 1)
                for cyc in range(20):
                    rv = ctx.get(dut.rsp_valid[0])
                    if rv:
                        ctx.set(dut.rsp_take[0], 1)
                        print(f"    {lb} {op_name}: rsp at cycle {cyc} (enq→rsp = {cyc+1} cyc)")
                        break
                    await ctx.tick()
                    ctx.set(dut.cmd_enq_valid[0], 0)
        sim.add_testbench(proc); sim.run()


if __name__ == "__main__":
    print("=" * 60)
    print("Pipelined GCSweepCoProc: Precision Throughput")
    print("=" * 60)
    print("  [背靠背执行跟踪]")
    test_back_to_back_original()
    test_back_to_back_pipelined()
    print()
    print("  [持续吞吐: 8 cmd → drain]")
    test_sustained_original()
    test_sustained_pipelined()
    test_continuous_peak()
    test_single_txn_latency()
    print("=== Done ===")
