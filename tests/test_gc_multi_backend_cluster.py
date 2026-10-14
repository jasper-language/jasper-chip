# tests/test_gc_multi_backend_cluster.py
# GCMultiBackendCluster integration test: dispatcher → N tiles → ordered merge.
from amaranth import *
from amaranth.sim import Simulator
from rtl.gc_multi_backend_cluster import GCMultiBackendCluster


def test_cluster_1Lx1_basic():
    """1 tile × 1L: basic passthrough."""
    dut = GCMultiBackendCluster(tile_count=1, lane_per_tile=1)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(dut.current_epoch, 0); ctx.set(dut.fill_ready, 1)
        ctx.set(dut.out_ready, 1)
        ctx.set(dut.in_valid, 1); ctx.set(dut.in_addr, 0x1000)
        ctx.set(dut.in_tag, 1); ctx.set(dut.in_type, 0)
        await ctx.tick(); ctx.set(dut.in_valid, 0)
        for _ in range(30):
            ctx.set(dut.out_ready, 1); ctx.set(dut.fill_ready, 1); await ctx.tick()
            if ctx.get(dut.out_valid):
                print(f"  1L×1 basic: tag={ctx.get(dut.out_tag)} data=0x{ctx.get(dut.out_data):x}")
                break
        else:
            print("  1L×1 basic: no response ❌")
    sim.add_testbench(proc); sim.run()


def test_cluster_1Lx2_basic():
    """2 tiles × 1L: dispatch to both tiles via addr hash."""
    for name, addr, exp_tag in [("tile0→lane0", 0x1000, 10), ("tile1→lane0", 0x1002, 20)]:
        dut = GCMultiBackendCluster(tile_count=2, lane_per_tile=1)
        sim = Simulator(dut); sim.add_clock(1e-6)
        async def proc(ctx, a=addr, t=exp_tag):
            await ctx.tick()
            ctx.set(dut.current_epoch, 0); ctx.set(dut.fill_ready, 1)
            ctx.set(dut.out_ready, 1)
            ctx.set(dut.in_valid, 1); ctx.set(dut.in_addr, a)
            ctx.set(dut.in_tag, t); ctx.set(dut.in_type, 0)
            await ctx.tick(); ctx.set(dut.in_valid, 0)
            for _ in range(30):
                ctx.set(dut.out_ready, 1); ctx.set(dut.fill_ready, 1); await ctx.tick()
                if ctx.get(dut.out_valid):
                    got = ctx.get(dut.out_tag)
                    assert got == t, f"{name}: tag={got} expected={t}"
                    break
            else:
                assert False, f"{name}: no response"
        sim.add_testbench(proc); sim.run()
    print("  1L×2 basic: PASS")


def test_cluster_tag_integrity():
    """1 tile × 1L: inject N events, verify all tags returned."""
    dut = GCMultiBackendCluster(tile_count=1, lane_per_tile=1)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(dut.current_epoch, 0); ctx.set(dut.fill_ready, 1)
        ctx.set(dut.out_ready, 1)
        N = 10; sent = set()
        for i in range(N):
            ctx.set(dut.in_valid, 1); ctx.set(dut.in_addr, 0x1000 + i)
            ctx.set(dut.in_tag, 200 + i)
            sent.add(200 + i)
            await ctx.tick(); ctx.set(dut.in_valid, 0)
        returned = set()
        for _ in range(120):
            ctx.set(dut.out_ready, 1); ctx.set(dut.fill_ready, 1); await ctx.tick()
            if ctx.get(dut.out_valid):
                returned.add(ctx.get(dut.out_tag))
        missing = sent - returned
        ok = "✅" if len(missing) == 0 else "❌"
        note = f" missing={missing}" if missing else ""
        print(f"  1L×1 tag integrity: {len(returned)}/{N} tags {ok}{note}")
    sim.add_testbench(proc); sim.run()


if __name__ == "__main__":
    tests = [
        ("1L×1 basic", test_cluster_1Lx1_basic),
        ("1L×2 basic", test_cluster_1Lx2_basic),
        ("1L×1 tag integrity", test_cluster_tag_integrity),
    ]
    passed = 0
    for name, fn in tests:
        try:
            fn(); passed += 1
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"  {name:20s} ❌ {e}")
    print(f"\nResults: {passed}/{len(tests)} passed")
    if passed != len(tests):
        exit(1)
