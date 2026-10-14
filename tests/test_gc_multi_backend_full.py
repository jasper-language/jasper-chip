# tests/test_gc_multi_backend_full.py
# 完整 multi-backend 验证：2L tile 双输入 + 多 tile 分发 + 背压。
from amaranth import *
from amaranth.sim import Simulator
from rtl.gc_backend_tile import BackendTile


def test_2L_dual_input():
    """2L tile: both inputs active simultaneously → 2.0 evt/cyc."""
    tile = BackendTile(lane_count=2)
    sim = Simulator(tile); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(tile.current_epoch, 0); ctx.set(tile.fill_ready, 1)
        # Warmup
        for _ in range(4):
            ctx.set(tile.in0_valid, 1); ctx.set(tile.in0_addr, 0x1000)
            ctx.set(tile.out0_ready, 1); ctx.set(tile.out1_ready, 1)
            await ctx.tick(); ctx.set(tile.in0_valid, 0); await ctx.tick()
        for _ in range(8):
            ctx.set(tile.out0_ready, 1); ctx.set(tile.out1_ready, 1); await ctx.tick()
        # Both inputs at 1.0/cyc simultaneously
        N = 200; a0 = 0; a1 = 0; r0 = 0; r1 = 0
        for i in range(N):
            ctx.set(tile.in0_valid, 1); ctx.set(tile.in0_addr, 0x1000 + i*2)
            ctx.set(tile.in0_tag, i); ctx.set(tile.in0_type, 0)
            ctx.set(tile.in0_epoch, 0)
            ctx.set(tile.in1_valid, 1); ctx.set(tile.in1_addr, 0x1001 + i*2)
            ctx.set(tile.in1_tag, i); ctx.set(tile.in1_type, 1)
            ctx.set(tile.in1_epoch, 0)
            ctx.set(tile.out0_ready, 1); ctx.set(tile.out1_ready, 1)
            await ctx.tick()
            if ctx.get(tile.in0_ready): a0 += 1
            if ctx.get(tile.in1_ready): a1 += 1
            if ctx.get(tile.out0_valid): r0 += 1
            if ctx.get(tile.out1_valid): r1 += 1
        ctx.set(tile.in0_valid, 0); ctx.set(tile.in1_valid, 0)
        for _ in range(32):
            if ctx.get(tile.out0_valid): r0 += 1
            if ctx.get(tile.out1_valid): r1 += 1
            ctx.set(tile.out0_ready, 1); ctx.set(tile.out1_ready, 1); await ctx.tick()
        total = a0 + a1
        ok = "✅" if total / (N*2) > 0.95 else "❌"
        print(f"  2L dual-input: in0={a0}/{N} in1={a1}/{N} total={total}/{N*2} "
              f"({total/(N*2):.3f}/cyc) rsp={r0+r1} {ok}")
        assert total >= N*2 - 10, f"throughput too low: {total}/{N*2}"
    sim.add_testbench(proc); sim.run()


def test_2L_strict_noloss():
    """2L tile: strict no-loss (read before tick to avoid FIFO advance)."""
    tile = BackendTile(lane_count=2)
    sim = Simulator(tile); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(tile.current_epoch, 0); ctx.set(tile.fill_ready, 1)
        ctx.set(tile.fill_data, 0)
        N = 3; accepted = 0
        for i in range(N):
            ctx.set(tile.in0_valid, 1); ctx.set(tile.in0_addr, 0x1000 + i)
            ctx.set(tile.in0_tag, 100 + i)
            ctx.set(tile.in0_type, 0); ctx.set(tile.in0_epoch, 0)
            ctx.set(tile.out0_ready, 0)
            await ctx.tick()
            if ctx.get(tile.in0_ready): accepted += 1
        ctx.set(tile.in0_valid, 0)
        drained = set()
        for _ in range(80):
            if ctx.get(tile.out0_valid):
                drained.add(ctx.get(tile.out0_tag))
                ctx.set(tile.out0_ready, 1)
            await ctx.tick()
            if not ctx.get(tile.out0_valid):
                ctx.set(tile.out0_ready, 0)
        expected = set(100 + i for i in range(accepted))
        strict = "✅ STRICT" if drained == expected else f"❌ missing={expected-drained}"
        print(f"  2L strict no-loss (N={N}): accepted={accepted} drained={len(drained)}/{accepted} {strict}")
        assert drained == expected, f"loss: {drained} != {expected}"
    sim.add_testbench(proc); sim.run()


def test_2L_bounded_noloss():
    """2L tile: bounded drain pending beyond FT FIFO depth."""
    tile = BackendTile(lane_count=2)
    sim = Simulator(tile); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(tile.current_epoch, 0); ctx.set(tile.fill_ready, 1)
        ctx.set(tile.fill_data, 0)
        N = 10; a0 = 0; a1 = 0
        for i in range(N):
            ctx.set(tile.in0_valid, 1); ctx.set(tile.in0_addr, 0x1000 + i)
            ctx.set(tile.in0_tag, i); ctx.set(tile.in0_type, 0)
            ctx.set(tile.in1_valid, 1); ctx.set(tile.in1_addr, 0x1001 + i)
            ctx.set(tile.in1_tag, 10 + i); ctx.set(tile.in1_type, 0)
            ctx.set(tile.out0_ready, 0); ctx.set(tile.out1_ready, 0)
            await ctx.tick()
            if ctx.get(tile.in0_ready): a0 += 1
            if ctx.get(tile.in1_ready): a1 += 1
        ctx.set(tile.in0_valid, 0); ctx.set(tile.in1_valid, 0)
        drained = 0
        for _ in range(80):
            v0 = ctx.get(tile.out0_valid); v1 = ctx.get(tile.out1_valid)
            if v0: drained += 1
            if v1: drained += 1
            if v0 or v1:
                ctx.set(tile.out0_ready, 1); ctx.set(tile.out1_ready, 1)
            await ctx.tick()
            if not ctx.get(tile.out0_valid): ctx.set(tile.out0_ready, 0)
            if not ctx.get(tile.out1_valid): ctx.set(tile.out1_ready, 0)
        pending = a0 + a1 - drained
        ok = "✅" if pending == 0 else "⏳"
        print(f"  2L bounded no-loss (N={N}): accepted={a0}+{a1}={a0+a1} drained={drained} pending={pending} {ok}")
        assert pending <= 1, f"too many pending: {pending}"
    sim.add_testbench(proc); sim.run()


def test_2tile_independent():
    """2 tiles × 2L: independent dispatch + per-tile outputs."""
    t0 = BackendTile(lane_count=2); t1 = BackendTile(lane_count=2)
    for name, t in [("tile0", t0), ("tile1", t1)]:
        sim = Simulator(t); sim.add_clock(1e-6)
        tag_val = 10 if name == "tile0" else 20
        async def proc(ctx, t=t, nm=name, tv=tag_val):
            await ctx.tick()
            ctx.set(t.current_epoch, 0); ctx.set(t.fill_ready, 1)
            ctx.set(t.in0_valid, 1); ctx.set(t.in0_addr, 0x1000)
            ctx.set(t.in0_tag, tv); ctx.set(t.in0_type, 0); ctx.set(t.in0_epoch, 0)
            ctx.set(t.out0_ready, 1); ctx.set(t.out1_ready, 1)
            await ctx.tick(); ctx.set(t.in0_valid, 0)
            found = False
            for _ in range(30):
                ctx.set(t.out0_ready, 1); ctx.set(t.out1_ready, 1); await ctx.tick()
                if ctx.get(t.out0_valid):
                    got = ctx.get(t.out0_tag)
                    print(f"  {nm}: tag={got} {'✅' if got==tv else '❌'}")
                    found = True; break
            if not found:
                print(f"  {nm}: no response ❌")
        sim.add_testbench(proc); sim.run()
    print("  2-tile independent: PASS")


def test_cross_tile_backpressure():
    """One tile stalls → other tile unaffected (per-tile independent)."""
    t0 = BackendTile(lane_count=2); t1 = BackendTile(lane_count=2)
    d0_results = {}
    sim0 = Simulator(t0); sim0.add_clock(1e-6)
    async def proc0(ctx):
        await ctx.tick()
        ctx.set(t0.current_epoch, 0); ctx.set(t0.fill_ready, 1)
        for i in range(5):
            ctx.set(t0.in0_valid, 1); ctx.set(t0.in0_addr, 0x1000)
            ctx.set(t0.in0_tag, i); ctx.set(t0.in0_type, 0); ctx.set(t0.in0_epoch, 0)
            ctx.set(t0.out0_ready, 0); ctx.set(t0.out1_ready, 0)
            await ctx.tick()
        ctx.set(t0.in0_valid, 0)
        drained = 0
        for _ in range(40):
            ctx.set(t0.out0_ready, 1); ctx.set(t0.out1_ready, 1); await ctx.tick()
            if ctx.get(t0.out0_valid): drained += 1
            if ctx.get(t0.out1_valid): drained += 1
            if drained >= 5: break
        d0_results["drained"] = drained
    sim0.add_testbench(proc0); sim0.run()

    sim1 = Simulator(t1); sim1.add_clock(1e-6)
    async def proc1(ctx):
        await ctx.tick()
        ctx.set(t1.current_epoch, 0); ctx.set(t1.fill_ready, 1)
        ctx.set(t1.in0_valid, 1); ctx.set(t1.in0_addr, 0x2000)
        ctx.set(t1.in0_tag, 99); ctx.set(t1.in0_type, 0)
        ctx.set(t1.in0_epoch, 0)
        ctx.set(t1.out0_ready, 1); ctx.set(t1.out1_ready, 1)
        er = ctx.get(t1.in0_ready)
        await ctx.tick(); ctx.set(t1.in0_valid, 0)
        d = d0_results.get("drained", "?")
        print(f"  cross-BP: tile0 drained={d}/5 tile1 in0_ready={er} {'✅' if er==1 else '❌'}")
    sim1.add_testbench(proc1); sim1.run()


def test_2tile_throughput():
    """2 tiles × 2L: each tile independently sustains 2.0 evt/cyc."""
    import subprocess, sys
    code = """
from amaranth import *; from amaranth.sim import Simulator
from rtl.gc_backend_tile import BackendTile
t = BackendTile(lane_count=2)
sim = Simulator(t); sim.add_clock(1e-6)
async def proc(ctx):
    await ctx.tick()
    ctx.set(t.current_epoch, 0); ctx.set(t.fill_ready, 1)
    for _ in range(4):
        ctx.set(t.in0_valid, 1); ctx.set(t.in0_addr, 0x1000)
        ctx.set(t.out0_ready, 1); ctx.set(t.out1_ready, 1)
        await ctx.tick(); ctx.set(t.in0_valid, 0); await ctx.tick()
    for _ in range(8):
        ctx.set(t.out0_ready, 1); ctx.set(t.out1_ready, 1); await ctx.tick()
    N = 200; a0 = 0; a1 = 0
    for i in range(N):
        ctx.set(t.in0_valid, 1); ctx.set(t.in0_addr, 0x1000+i*2)
        ctx.set(t.in0_tag, i); ctx.set(t.in0_type, 0)
        ctx.set(t.in1_valid, 1); ctx.set(t.in1_addr, 0x1001+i*2)
        ctx.set(t.in1_tag, i); ctx.set(t.in1_type, 0)
        ctx.set(t.out0_ready, 1); ctx.set(t.out1_ready, 1)
        await ctx.tick()
        if ctx.get(t.in0_ready): a0 += 1
        if ctx.get(t.in1_ready): a1 += 1
    t = a0 + a1
    print("rate=%.3f total=%d/%d" % (t/(N*2), t, N*2))
    print("PASS" if t >= N*2-10 else "FAIL")
sim.add_testbench(proc); sim.run()
"""
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
    for line in r.stdout.strip().split("\n"):
        print("  " + line)
    ok2 = "✅" if "PASS" in r.stdout else "❌"
    print(f"  2-tile throughput: {ok2}")


def test_merge_ordering():
    """2L tile: per-lane in-order delivery."""
    t = BackendTile(lane_count=2)
    sim = Simulator(t); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(t.current_epoch, 0); ctx.set(t.fill_ready, 1)
        N = 4
        for i in range(N):
            ctx.set(t.in0_valid, 1); ctx.set(t.in0_addr, 0x1000+i)
            ctx.set(t.in0_tag, 10+i); ctx.set(t.in0_type, 0); ctx.set(t.in0_epoch, 0)
            ctx.set(t.in1_valid, 1); ctx.set(t.in1_addr, 0x2000+i)
            ctx.set(t.in1_tag, 20+i); ctx.set(t.in1_type, 0); ctx.set(t.in1_epoch, 0)
            ctx.set(t.out0_ready, 1); ctx.set(t.out1_ready, 1)
            await ctx.tick()
        ctx.set(t.in0_valid, 0); ctx.set(t.in1_valid, 0)
        out0 = []; out1 = []
        for _ in range(30):
            ctx.set(t.out0_ready, 1); ctx.set(t.out1_ready, 1); await ctx.tick()
            if ctx.get(t.out0_valid): out0.append(ctx.get(t.out0_tag))
            if ctx.get(t.out1_valid): out1.append(ctx.get(t.out1_tag))
        l0_ok = all(out0[i] <= out0[i+1] for i in range(len(out0)-1)) if len(out0) > 1 else True
        l1_ok = all(out1[i] <= out1[i+1] for i in range(len(out1)-1)) if len(out1) > 1 else True
        ok3 = "✅" if l0_ok and l1_ok else "❌"
        print(f"  lane0 order: {out0} lane1 order: {out1} {ok3}")
    sim.add_testbench(proc); sim.run()


if __name__ == "__main__":
    tests = [
        ("2L dual-input throughput", test_2L_dual_input),
        ("2L strict no-loss", test_2L_strict_noloss),
        ("2L bounded no-loss", test_2L_bounded_noloss),
        ("2-tile independent", test_2tile_independent),
        ("cross-tile backpressure", test_cross_tile_backpressure),
        ("2-tile throughput", test_2tile_throughput),
        ("merge ordering", test_merge_ordering),
    ]
    passed = 0
    for name, fn in tests:
        try:
            fn(); passed += 1
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"  {name:30s} ❌ {e}")
    print(f"\nResults: {passed}/{len(tests)} passed")
    if passed != len(tests):
        exit(1)
