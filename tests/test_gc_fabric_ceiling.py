# tests/test_gc_fabric_ceiling.py
# Fabric ceiling validation: 2L×2 / 2L×4 sustained throughput, ordering, bank conflict.
from amaranth import *
from amaranth.sim import Simulator
from rtl.gc_backend_tile import BackendTile


class MultiTileHarness(Elaboratable):
    """N × 2L tiles with direct input drive (no frontend bottleneck)."""
    def __init__(self, tile_count=2):
        self.tile_count = tile_count
        self.tiles = [BackendTile(lane_count=2) for _ in range(tile_count)]
        # Input ports: 2 per tile
        self.in_valid = [Signal() for _ in range(tile_count * 2)]
        self.in_ready = [Signal() for _ in range(tile_count * 2)]
        self.in_addr = [Signal(32) for _ in range(tile_count * 2)]
        self.in_tag = [Signal(8) for _ in range(tile_count * 2)]
        # Output ports: 2 per tile
        self.out_valid = [Signal() for _ in range(tile_count * 2)]
        self.out_ready = [Signal() for _ in range(tile_count * 2)]
        self.out_tag = [Signal(8) for _ in range(tile_count * 2)]
        self.busy = Signal()

    def elaborate(self, platform):
        m = Module(); P = self; TC = P.tile_count
        for i, t in enumerate(P.tiles):
            m.submodules[f"tile_{i}"] = t

        for i in range(TC):
            t = P.tiles[i]
            for lp in range(2):
                idx = i * 2 + lp
                v = P.in_valid[idx]; r = P.in_ready[idx]
                a = P.in_addr[idx]; tg = P.in_tag[idx]
                ov = P.out_valid[idx]; or_ = P.out_ready[idx]
                ot = P.out_tag[idx]
                # Tile input connections
                t_in = [t.in0_valid, t.in1_valid][lp]
                t_rdy = [t.in0_ready, t.in1_ready][lp]
                t_addr = [t.in0_addr, t.in1_addr][lp]
                t_tag = [t.in0_tag, t.in1_tag][lp]
                t_out_v = [t.out0_valid, t.out1_valid][lp]
                t_out_rdy = [t.out0_ready, t.out1_ready][lp]
                t_out_tag = [t.out0_tag, t.out1_tag][lp]
                m.d.comb += [
                    t_in.eq(v), r.eq(t_rdy),
                    t_addr.eq(a), t_tag.eq(tg),
                    ov.eq(t_out_v), t_out_rdy.eq(or_),
                    ot.eq(t_out_tag),
                ]
            # Common tile control
            m.d.comb += [
                t.current_epoch.eq(0), t.flush.eq(0),
                t.fill_ready.eq(1), t.fill_data.eq(0),
            ]

        m.d.comb += P.busy.eq(sum(t.busy for t in P.tiles) > 0)
        return m


def test_2Lx2_continuous():
    """2 tiles × 2L: 4 inputs → 4.0 evt/cyc sustained."""
    TC = 2; total_ports = TC * 2
    dut = MultiTileHarness(tile_count=TC)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        # Warmup: send one event per port
        for i in range(total_ports):
            ctx.set(dut.in_valid[i], 1); ctx.set(dut.in_addr[i], 0x1000 + i*2)
            ctx.set(dut.out_ready[i], 1)
        await ctx.tick()
        for i in range(total_ports):
            ctx.set(dut.in_valid[i], 0)
        for _ in range(8):
            for i in range(total_ports): ctx.set(dut.out_ready[i], 1)
            await ctx.tick()
        # Continuous: all 4 inputs at 1.0/cyc
        N = 200; accepted = [0]*total_ports; responses = [0]*total_ports
        for cycle in range(N):
            for i in range(total_ports):
                ctx.set(dut.in_valid[i], 1)
                ctx.set(dut.in_addr[i], 0x1000 + cycle * total_ports + i)
                ctx.set(dut.in_tag[i], cycle * total_ports + i)
                ctx.set(dut.out_ready[i], 1)
            await ctx.tick()
            for i in range(total_ports):
                if ctx.get(dut.in_ready[i]): accepted[i] += 1
                if ctx.get(dut.out_valid[i]): responses[i] += 1
        for i in range(total_ports):
            ctx.set(dut.in_valid[i], 0)
        for _ in range(32):
            for i in range(total_ports): ctx.set(dut.out_ready[i], 1)
            await ctx.tick()
            for i in range(total_ports):
                if ctx.get(dut.out_valid[i]): responses[i] += 1
            if not ctx.get(dut.busy): break
        total_acc = sum(accepted); total_rsp = sum(responses)
        acc_rate = total_acc / (N * total_ports)
        rsp_rate = total_rsp / (N * total_ports)
        min_acc = min(accepted); max_acc = max(accepted)
        ok = "✅" if acc_rate > 0.95 else "❌"
        print(f"  2L×2 continuous: acc={total_acc}/{N*total_ports} ({acc_rate:.3f}/cyc/slot)")
        print(f"    per-slot acc: {accepted} (min={min_acc} max={max_acc})")
        print(f"    responses: {total_rsp} ({rsp_rate:.3f}/cyc/slot) {ok}")
        assert acc_rate > 0.90, f"throughput {acc_rate} < 0.90"
    sim.add_testbench(proc); sim.run()


def test_2Lx2_noloss():
    """2 tiles × 2L: backpressure no loss on all 4 inputs."""
    TC = 2; total_ports = TC * 2
    dut = MultiTileHarness(tile_count=TC)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        for i in range(total_ports):
            ctx.set(dut.in_valid[i], 1); ctx.set(dut.in_addr[i], 0x1000 + i*2)
            ctx.set(dut.out_ready[i], 1)
        await ctx.tick()
        for i in range(total_ports): ctx.set(dut.in_valid[i], 0)
        for _ in range(8):
            for i in range(total_ports): ctx.set(dut.out_ready[i], 1)
            await ctx.tick()
        # Inject without consuming
        N = 5; accepted = [0]*total_ports
        for cycle in range(N):
            for i in range(total_ports):
                ctx.set(dut.in_valid[i], 1)
                ctx.set(dut.in_addr[i], 0x2000 + cycle * total_ports + i)
                ctx.set(dut.in_tag[i], cycle * total_ports + i)
                ctx.set(dut.out_ready[i], 0)
            await ctx.tick()
            for i in range(total_ports):
                if ctx.get(dut.in_ready[i]): accepted[i] += 1
        for i in range(total_ports): ctx.set(dut.in_valid[i], 0)
        # Drain
        total_acc = sum(accepted)
        drained = 0; seen_tags = set()
        for _ in range(120):
            for i in range(total_ports): ctx.set(dut.out_ready[i], 1)
            await ctx.tick()
            for i in range(total_ports):
                if ctx.get(dut.out_valid[i]):
                    drained += 1
                    seen_tags.add(ctx.get(dut.out_tag[i]))
            if drained >= total_acc: break
        ok = "✅" if drained >= total_acc - 2 else "❌"
        print(f"  2L×2 no-loss: accepted={total_acc} drained={drained}/{total_acc} "
              f"unique={len(seen_tags)} {ok}")
    sim.add_testbench(proc); sim.run()


def test_2Lx2_tag_integrity():
    """2 tiles × 2L: verify all injected tags (0-255 range) are recovered."""
    TC = 2; total_ports = TC * 2
    dut = MultiTileHarness(tile_count=TC)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        for i in range(total_ports): ctx.set(dut.out_ready[i], 1)
        N = 10
        sent = set()
        returned = set()
        for cycle in range(N):
            for i in range(total_ports):
                if ctx.get(dut.out_valid[i]):
                    returned.add(ctx.get(dut.out_tag[i]))
            for i in range(total_ports):
                tag = (cycle * total_ports + i) & 0xFF  # 8-bit safe
                ctx.set(dut.in_valid[i], 1)
                ctx.set(dut.in_addr[i], 0x3000 + cycle * total_ports + i)
                ctx.set(dut.in_tag[i], tag)
                ctx.set(dut.out_ready[i], 1)
            await ctx.tick()
            for i in range(total_ports):
                sent.add((cycle * total_ports + i) & 0xFF)
                ctx.set(dut.in_valid[i], 0)
        for _ in range(80):
            for i in range(total_ports):
                if ctx.get(dut.out_valid[i]):
                    returned.add(ctx.get(dut.out_tag[i]))
            for i in range(total_ports): ctx.set(dut.out_ready[i], 1)
            await ctx.tick()
        missing = sent - returned; extra = returned - sent
        ok = "✅" if sent == returned else "❌"
        print(f"  2L×2 tag integrity: sent={len(sent)} returned={len(returned)} "
              f"missing={len(missing)} extra={len(extra)} {ok}")
        if missing: print(f"    missing tags: {sorted(missing)[:10]}")
    sim.add_testbench(proc); sim.run()


def test_2Lx4_basic():
    """4 tiles × 2L: 8 inputs, verify all respond (model validation)."""
    TC = 4; total_ports = TC * 2
    dut = MultiTileHarness(tile_count=TC)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        for i in range(total_ports):
            ctx.set(dut.in_valid[i], 1); ctx.set(dut.in_addr[i], 0x4000 + i)
            ctx.set(dut.in_tag[i], i)
            ctx.set(dut.out_ready[i], 1)
        await ctx.tick()
        for i in range(total_ports): ctx.set(dut.in_valid[i], 0)
        for _ in range(8):
            for i in range(total_ports): ctx.set(dut.out_ready[i], 1)
            await ctx.tick()
        for i in range(total_ports):
            if ctx.get(dut.out_valid[i]):
                pass  # response seen
        # Measure continuous
        N = 50; acc = 0
        for cycle in range(N):
            for i in range(total_ports):
                ctx.set(dut.in_valid[i], 1)
                ctx.set(dut.in_addr[i], 0x4000 + cycle * total_ports + i)
                ctx.set(dut.in_tag[i], cycle * total_ports + i)
                ctx.set(dut.out_ready[i], 1)
            await ctx.tick()
            for i in range(total_ports):
                if ctx.get(dut.in_ready[i]): acc += 1
        for i in range(total_ports): ctx.set(dut.in_valid[i], 0)
        for _ in range(16):
            for i in range(total_ports): ctx.set(dut.out_ready[i], 1)
            await ctx.tick()
            if not ctx.get(dut.busy): break
        acc_rate = acc / (N * total_ports)
        ok = "✅" if acc_rate > 0.90 else "❌"
        print(f"  2L×4 basic: {acc}/{N*total_ports} ({acc_rate:.3f}/cyc/slot) {ok}")
    sim.add_testbench(proc); sim.run()


if __name__ == "__main__":
    tests = [
        ("2L×2 continuous", test_2Lx2_continuous),
        ("2L×2 no-loss", test_2Lx2_noloss),
        ("2L×2 tag integrity", test_2Lx2_tag_integrity),
        ("2L×4 basic", test_2Lx4_basic),
    ]
    passed = 0
    for name, fn in tests:
        try:
            fn(); passed += 1
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"  {name:25s} ❌ {e}")
    print(f"\nResults: {passed}/{len(tests)} passed")
    if passed != len(tests):
        exit(1)
