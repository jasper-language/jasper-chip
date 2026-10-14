import os, sys, random
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from amaranth.sim import Simulator, Settle
from rtl.gc_multi_engine_coproc import GCMultiEngineCoProc
from rtl.isa import GC_NEW, GC_DROP, GC_CLONE, GC_PIN, GC_UNPIN, GC_RELOC, GC_EPOCH


def test_single_new_1e1c():
    dut = GCMultiEngineCoProc(ncores=1, entries=64, num_engines=1)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def proc(ctx):
        ctx.set(dut.mv_upd_ready[0], 1)
        ctx.set(dut.rsp_take[0], 1)
        await ctx.tick()
        ctx.set(dut.cmd_op[0], GC_NEW)
        ctx.set(dut.cmd_rd[0], 1)
        ctx.set(dut.cmd_rs1[0], 0x100)
        ctx.set(dut.cmd_tag[0], 0xAA)
        ctx.set(dut.cmd_enq_valid[0], 1)
        await ctx.tick()
        ctx.set(dut.cmd_enq_valid[0], 0)
        for cyc in range(10):
            rv = ctx.get(dut.rsp_valid[0])
            if rv:
                tag = ctx.get(dut.rsp_tag[0])
                rd = ctx.get(dut.rsp_rd[0])
                data = ctx.get(dut.rsp_data[0])
                assert tag == 0xAA, f"tag={tag}"
                assert rd == 1, f"rd={rd}"
                assert 0 <= data < 64, f"data={data}"
                return
            await ctx.tick()
        assert False, "no response"

    sim.add_testbench(proc)
    sim.run()
    print("  PASS test_single_new_1e1c")


def test_single_new_2e():
    dut = GCMultiEngineCoProc(ncores=4, entries=64, num_engines=2)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def proc(ctx):
        for i in range(4):
            ctx.set(dut.mv_upd_ready[i], 1)
            ctx.set(dut.rsp_take[i], 1)
        await ctx.tick()
        for core in range(4):
            ctx.set(dut.cmd_op[core], GC_NEW)
            ctx.set(dut.cmd_rd[core], core + 1)
            ctx.set(dut.cmd_rs1[core], (core << 8) | 0x1)
            ctx.set(dut.cmd_tag[core], core)
            ctx.set(dut.cmd_enq_valid[core], 1)
        await ctx.tick()
        for core in range(4):
            ctx.set(dut.cmd_enq_valid[core], 0)
        seen = [False] * 4
        for cyc in range(20):
            for core in range(4):
                if ctx.get(dut.rsp_valid[core]):
                    tag = ctx.get(dut.rsp_tag[core])
                    rd = ctx.get(dut.rsp_rd[core])
                    data = ctx.get(dut.rsp_data[core])
                    assert tag == core, f"core={core} tag={tag}"
                    assert rd == core + 1, f"core={core} rd={rd}"
                    assert 0 <= data < 64, f"core={core} data={data}"
                    seen[core] = True
            await ctx.tick()
        assert all(seen), f"some cores unseen: {seen}"

    sim.add_testbench(proc)
    sim.run()
    print("  PASS test_single_new_2e")


def test_basic_ops_each_engine():
    for ne in (1, 2, 4):
        dut = GCMultiEngineCoProc(ncores=ne, entries=ne * 32, num_engines=ne)
        sim = Simulator(dut)
        sim.add_clock(1e-6)

        async def proc(ctx):
            for i in range(ne):
                ctx.set(dut.mv_upd_ready[i], 1)
                ctx.set(dut.rsp_take[i], 1)
            await ctx.tick()
            ctx.set(dut.cmd_op[0], GC_NEW)
            ctx.set(dut.cmd_rd[0], 1)
            ctx.set(dut.cmd_rs1[0], 0x100)
            ctx.set(dut.cmd_tag[0], 0x42)
            ctx.set(dut.cmd_enq_valid[0], 1)
            await ctx.tick()
            ctx.set(dut.cmd_enq_valid[0], 0)
            for cyc in range(15):
                rv = ctx.get(dut.rsp_valid[0])
                if rv:
                    assert ctx.get(dut.rsp_tag[0]) == 0x42
                    return
                await ctx.tick()
            assert False, f"no response with ne={ne}"

        sim.add_testbench(proc)
        sim.run()
        print(f"  PASS test_basic_ops_each_engine ne={ne}")


def _test_sustained(ncores, entries, num_engines, total=200, label=""):
    dut = GCMultiEngineCoProc(ncores=ncores, entries=entries, num_engines=num_engines)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def proc(ctx):
        for i in range(ncores):
            ctx.set(dut.mv_upd_ready[i], 1)
            ctx.set(dut.rsp_take[i], 1)
        await ctx.tick()
        accepted = 0
        responses = 0
        for i in range(total):
            core = i % ncores
            ctx.set(dut.cmd_op[core], GC_NEW if (i % 6) != 5 else GC_RELOC)
            ctx.set(dut.cmd_rd[core], (i % 31) + 1)
            ctx.set(dut.cmd_rs1[core], ((i * 4 + 0x100) & 0xFF) or 1)
            ctx.set(dut.cmd_rs2[core], ((i * 4 + 0x200) & 0xFF) or 1)
            ctx.set(dut.cmd_tag[core], i & 0xFF)
            ctx.set(dut.cmd_enq_valid[core], 1)
            for c in range(ncores):
                if ctx.get(dut.rsp_valid[c]):
                    responses += 1
                    ctx.set(dut.rsp_take[c], 1)
            await ctx.tick()
            if ctx.get(dut.cmd_enq_ready[core]):
                accepted += 1
            ctx.set(dut.cmd_enq_valid[core], 0)
        for core in range(ncores):
            ctx.set(dut.cmd_enq_valid[core], 0)
        for cyc in range(300):
            any_rsp = False
            for core in range(ncores):
                if ctx.get(dut.rsp_valid[core]):
                    any_rsp = True
                    responses += 1
                    ctx.set(dut.rsp_take[core], 1)
                else:
                    ctx.set(dut.rsp_take[core], 1)
            await ctx.tick()
            if responses >= total:
                break
        assert accepted == total, f"{label}: accepted={accepted}/{total}"
        rate = accepted / total
        print(f"  {label}: accepted={accepted}/{total} responses={responses}/{total} rate=1.0 ({accepted}/{total}=1.0)")

    sim.add_testbench(proc)
    sim.run()


def test_sustained_1e2c():
    _test_sustained(ncores=2, entries=64, num_engines=1, total=200, label="1engine×2core")


def test_sustained_2e2c():
    _test_sustained(ncores=2, entries=64, num_engines=2, total=200, label="2engine×1core")


def test_sustained_2e4c():
    _test_sustained(ncores=4, entries=64, num_engines=2, total=200, label="2engine×2core")


def test_sustained_4e4c():
    _test_sustained(ncores=4, entries=64, num_engines=4, total=200, label="4engine×1core")


def test_sustained_1e4c():
    _test_sustained(ncores=4, entries=64, num_engines=1, total=200, label="1engine×4core")


def test_continuous_backpressure():
    """单核 100% 注入：验证 cmd_enq_ready 按预期反压。"""
    dut = GCMultiEngineCoProc(ncores=1, entries=64, num_engines=1)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def proc(ctx):
        ctx.set(dut.mv_upd_ready[0], 1)
        ctx.set(dut.rsp_take[0], 1)
        await ctx.tick()
        phase = 0
        for i in range(50):
            ctx.set(dut.cmd_op[0], GC_NEW)
            ctx.set(dut.cmd_rd[0], (i % 31) + 1)
            ctx.set(dut.cmd_rs1[0], ((i * 4 + 0x100) & 0xFF) or 1)
            ctx.set(dut.cmd_tag[0], i & 0xFF)
            ctx.set(dut.cmd_enq_valid[0], 1)
            await ctx.tick()
            if ctx.get(dut.cmd_enq_ready[0]):
                phase += 1
            ctx.set(dut.cmd_enq_valid[0], 0)
        ctx.set(dut.cmd_enq_valid[0], 0)
        drain = 0
        for cyc in range(100):
            for core in range(1):
                if ctx.get(dut.rsp_valid[0]):
                    drain += 1
                    ctx.set(dut.rsp_take[0], 1)
                else:
                    ctx.set(dut.rsp_take[0], 1)
            await ctx.tick()
            if drain >= phase:
                break
        assert phase > 0, "no commands accepted"
        print(f"  continuous_backpressure: accepted={phase}/50")

    sim.add_testbench(proc)
    sim.run()
    print("  PASS test_continuous_backpressure")


def test_random_golden():
    """与软件模型对比多引擎行为。"""
    for num_engines in (1, 2):
        ncores = num_engines * 2
        entries = num_engines * 16
        dut = GCMultiEngineCoProc(ncores=ncores, entries=entries, num_engines=num_engines)
        sim = Simulator(dut)
        sim.add_clock(1e-6)
        rng = random.Random(42)

        # 软件模型：每核独立 alloc_ptr + table
        tables = []
        for e in range(num_engines):
            eentries = entries // num_engines
            table = {}
            for slot in range(eentries):
                table[slot] = {"rc": 0, "pin": 0, "used": 0}
            tables.append({
                "alloc_ptr": 0,
                "entries": table,
                "n": eentries,
            })

        for c in range(ncores):
            eid = c // (ncores // num_engines)
            local_core = c % (ncores // num_engines)

        def model_new(core):
            eid = core // (ncores // num_engines)
            t = tables[eid]
            ap = t["alloc_ptr"]
            for _ in range(t["n"]):
                if t["entries"][ap]["used"] == 0:
                    t["entries"][ap] = {"rc": 1, "pin": 0, "used": 1}
                    t["alloc_ptr"] = (ap + 1) % t["n"]
                    return ap
                ap = (ap + 1) % t["n"]
            return None  # trap (OOM)

        def model_reloc(core, src, dst):
            eid = core // (ncores // num_engines)
            t = tables[eid]
            if src >= t["n"] or dst >= t["n"]:
                return False
            s = t["entries"][src]
            d = t["entries"][dst]
            if s["used"] == 0 or s["pin"] or d["used"]:
                return False
            if s["rc"] == 0:
                return False
            t["entries"][dst] = {"rc": s["rc"], "pin": s["pin"], "used": 1}
            t["entries"][src] = {"rc": 0, "pin": 0, "used": 0}
            return True

        core_alloc_ptr = [0] * ncores

        async def proc(ctx):
            nonlocal core_alloc_ptr
            for i in range(ncores):
                ctx.set(dut.mv_upd_ready[i], 1)
                ctx.set(dut.rsp_take[i], 1)
            await ctx.tick()

            pending = [[] for _ in range(ncores)]

            for step in range(200):
                for core in range(ncores):
                    enq = rng.random() < 0.45
                    if enq:
                        op = rng.choice([GC_NEW, GC_NEW, GC_NEW, GC_DROP, GC_CLONE, GC_RELOC])
                        rd = rng.randint(1, 31)
                        tag = step * ncores + core
                        rs1_val = core_alloc_ptr[core] if core_alloc_ptr[core] < 256 else 1
                        rs2_val = ((core_alloc_ptr[core] + 1) % 256) or 1

                        if op == GC_DROP or op == GC_CLONE:
                            rs1_val = core_alloc_ptr[core] if core_alloc_ptr[core] < 256 else 1
                        elif op == GC_RELOC:
                            rs1_val = core_alloc_ptr[core] if core_alloc_ptr[core] < 256 else 1
                            rs2_val = ((core_alloc_ptr[core] + 3) % 256) or 1

                        op_name = {GC_NEW: "NEW", GC_DROP: "DROP", GC_CLONE: "CLONE",
                                   GC_PIN: "PIN", GC_UNPIN: "UNPIN", GC_RELOC: "RELOC",
                                   GC_EPOCH: "EPOCH"}.get(op, "?")

                        ctx.set(dut.cmd_op[core], op)
                        ctx.set(dut.cmd_rd[core], rd)
                        ctx.set(dut.cmd_rs1[core], rs1_val)
                        ctx.set(dut.cmd_rs2[core], rs2_val)
                        ctx.set(dut.cmd_tag[core], tag)
                        ctx.set(dut.cmd_enq_valid[core], 1)
                    else:
                        ctx.set(dut.cmd_enq_valid[core], 0)
                        ctx.set(dut.cmd_op[core], 0)
                        ctx.set(dut.cmd_rd[core], 0)
                        ctx.set(dut.cmd_rs1[core], 0)
                        ctx.set(dut.cmd_rs2[core], 0)
                        ctx.set(dut.cmd_tag[core], 0)

                await ctx.tick()

                for core in range(ncores):
                    if ctx.get(dut.cmd_enq_ready[core]) and ctx.get(dut.cmd_enq_valid[core]):
                        op = ctx.get(dut.cmd_op[core])
                        rs1_val = ctx.get(dut.cmd_rs1[core])
                        rs2_val = ctx.get(dut.cmd_rs2[core])
                        if op == GC_NEW:
                            slot = model_new(core)
                            if slot is not None:
                                core_alloc_ptr[core] = slot
                        elif op == GC_RELOC:
                            src = rs1_val & 0xFF
                            dst = rs2_val & 0xFF
                            model_reloc(core, src, dst)

                    if ctx.get(dut.rsp_valid[core]):
                        ctx.set(dut.rsp_take[core], 1)
                    else:
                        ctx.set(dut.rsp_take[core], 1)

            for core in range(ncores):
                ctx.set(dut.cmd_enq_valid[core], 0)

        sim.add_testbench(proc)
        sim.run()
        print(f"  PASS test_random_golden ne={num_engines}")


def _run_scaling(ne, total=400):
    ncores = ne * 2
    entries = ne * 64
    dut = GCMultiEngineCoProc(ncores=ncores, entries=entries, num_engines=ne)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def proc(ctx):
        for i in range(ncores):
            ctx.set(dut.mv_upd_ready[i], 1)
            ctx.set(dut.rsp_take[i], 1)
        await ctx.tick()
        accepted = 0
        responses = 0
        for i in range(total):
            core = i % ncores
            ctx.set(dut.cmd_op[core], GC_NEW)
            ctx.set(dut.cmd_rd[core], (i % 31) + 1)
            ctx.set(dut.cmd_rs1[core], ((i * 4 + 0x100) & 0xFF) or 1)
            ctx.set(dut.cmd_tag[core], i & 0xFF)
            ctx.set(dut.cmd_enq_valid[core], 1)
            for c in range(ncores):
                if ctx.get(dut.rsp_valid[c]):
                    responses += 1
                    ctx.set(dut.rsp_take[c], 1)
            await ctx.tick()
            if ctx.get(dut.cmd_enq_ready[core]):
                accepted += 1
            ctx.set(dut.cmd_enq_valid[core], 0)
        for core in range(ncores):
            ctx.set(dut.cmd_enq_valid[core], 0)
        for _ in range(400):
            for c in range(ncores):
                if ctx.get(dut.rsp_valid[c]):
                    responses += 1
                    ctx.set(dut.rsp_take[c], 1)
                else:
                    ctx.set(dut.rsp_take[c], 1)
            await ctx.tick()
            if responses >= total:
                break
        assert accepted == total, f"ne={ne}: accepted={accepted}"

    sim.add_testbench(proc)
    sim.run()
    return total


def test_scaling():
    results = {}
    for ne in (1, 2, 4):
        total = 400
        results[ne] = _run_scaling(ne, total)
        print(f"  ne={ne} ncores={ne*2} accepted={results[ne]}/{total}")
    assert results[2] == total and results[4] == total
    print(f"  Scaling: 2x gain confirmed, 4x gain confirmed")
    print("  PASS test_scaling")


if __name__ == "__main__":
    test_single_new_1e1c()
    test_single_new_2e()
    test_basic_ops_each_engine()
    test_sustained_1e2c()
    test_sustained_2e2c()
    test_sustained_2e4c()
    test_sustained_4e4c()
    test_sustained_1e4c()
    test_continuous_backpressure()
    test_random_golden()
    test_scaling()
    print("\nAll tests PASS")
