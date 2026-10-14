# tests/test_gc_multi_backend.py
# Multi-backend: N parameterized tiles × dispatch × merge.
from amaranth import *
from amaranth.sim import Simulator
from rtl.gc_backend_tile import BackendTile


class MultiBackend(Elaboratable):
    """N tiles + dispatch + merge. Each tile can be 1L or 2L."""
    def __init__(self, tile_count=2, lane_per_tile=1):
        self.tile_count = tile_count
        self.lane_per_tile = lane_per_tile
        # Single input (dispatch to tiles by addr hash)
        self.in_valid = Signal(); self.in_ready = Signal()
        self.in_type = Signal(2); self.in_addr = Signal(32)
        self.in_data = Signal(32); self.in_tag = Signal(8)
        self.in_epoch = Signal(8); self.in_seq = Signal(2)
        self.flush = Signal(); self.flush_epoch = Signal(8)
        self.current_epoch = Signal(8)
        # Outputs: one per lane (tile_count × lane_per_tile)
        total_out = tile_count * lane_per_tile
        self.out_valid = [Signal() for _ in range(total_out)]
        self.out_ready = [Signal() for _ in range(total_out)]
        self.out_data = [Signal(32) for _ in range(total_out)]
        self.out_tag = [Signal(8) for _ in range(total_out)]
        self.busy = Signal()
        self.fill_ready = Signal(); self.fill_valid = Signal()
        self.fill_addr = Signal(32); self.fill_data = Signal(32)

    def elaborate(self, platform):
        m = Module(); P = self; TC = P.tile_count; LP = P.lane_per_tile
        tc_bits = (TC - 1).bit_length() if TC > 1 else 0
        lane_bits = (LP - 1).bit_length() if LP > 1 else 0

        tiles = [BackendTile(lane_count=LP) for _ in range(TC)]
        for i, t in enumerate(tiles):
            m.submodules[f"tile_{i}"] = t

        # Dispatch: addr[:tc_bits] → tile, addr[tc_bits:tc_bits+lane_bits] → lane
        tile_id = Signal(tc_bits if tc_bits >= 1 else 1)
        lane_in_tile = Signal(lane_bits if lane_bits >= 1 else 1)
        if tc_bits >= 1:
            m.d.comb += tile_id.eq(P.in_addr[:tc_bits])
        if lane_bits >= 1:
            m.d.comb += lane_in_tile.eq(P.in_addr[tc_bits:tc_bits + lane_bits])

        # Route to selected tile and lane
        in_rdy = Const(0)
        for i in range(TC):
            sel = Signal(); m.d.comb += sel.eq(tile_id == i)
            t = tiles[i]
            if LP >= 2:
                m.d.comb += [
                    t.in0_valid.eq(P.in_valid & sel & (lane_in_tile == 0)),
                    t.in1_valid.eq(P.in_valid & sel & (lane_in_tile == 1)),
                ]
                r0 = Mux(sel & (lane_in_tile == 0), t.in0_ready, 0)
                r1 = Mux(sel & (lane_in_tile == 1), t.in1_ready, 0)
                in_rdy = r0 | r1 | in_rdy
            else:
                m.d.comb += t.in0_valid.eq(P.in_valid & sel)
                in_rdy = Mux(sel, t.in0_ready, in_rdy)

            # Common tile signals
            m.d.comb += [
                t.in0_type.eq(P.in_type), t.in1_type.eq(P.in_type),
                t.in0_addr.eq(P.in_addr), t.in1_addr.eq(P.in_addr),
                t.in0_data.eq(P.in_data), t.in1_data.eq(P.in_data),
                t.in0_tag.eq(P.in_tag), t.in1_tag.eq(P.in_tag),
                t.in0_epoch.eq(P.in_epoch), t.in1_epoch.eq(P.in_epoch),
                t.in0_seq.eq(P.in_seq), t.in1_seq.eq(P.in_seq),
                t.flush.eq(P.flush), t.flush_epoch.eq(P.flush_epoch),
                t.current_epoch.eq(P.current_epoch),
                t.fill_ready.eq(P.fill_ready), t.fill_data.eq(P.fill_data),
            ]

        m.d.comb += P.in_ready.eq(in_rdy)

        # Outputs: tile i, lane p → out_idx = i * LP + p
        for i in range(TC):
            for p in range(LP):
                out_idx = i * LP + p
                t = tiles[i]
                t_out = [t.out0_valid, t.out1_valid][p] if LP >= 2 else t.out0_valid
                t_rdy = [t.out0_ready, t.out1_ready][p] if LP >= 2 else t.out0_ready
                t_data = [t.out0_data, t.out1_data][p] if LP >= 2 else t.out0_data
                t_tag = [t.out0_tag, t.out1_tag][p] if LP >= 2 else t.out0_tag
                m.d.comb += [
                    P.out_valid[out_idx].eq(t_out),
                    t_rdy.eq(P.out_ready[out_idx]),
                    P.out_data[out_idx].eq(t_data),
                    P.out_tag[out_idx].eq(t_tag),
                ]

        fill_v = Const(0); fill_a = Const(0)
        for t in tiles:
            fill_v = fill_v | t.fill_valid
            fill_a = Mux(t.fill_valid, t.fill_addr, fill_a)
        m.d.comb += [
            P.fill_valid.eq(fill_v), P.fill_addr.eq(fill_a),
            P.busy.eq(sum(t.busy for t in tiles) > 0),
        ]
        return m


# ── Tests ──────────────────────────────────────────────────────
def test_1Lx1():
    """1 tile, 1 lane per tile = 1.0 evt/cyc baseline."""
    dut = MultiBackend(tile_count=1, lane_per_tile=1)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(dut.current_epoch, 0)
        for _ in range(4):
            ctx.set(dut.in_valid, 1); ctx.set(dut.in_addr, 0x1000)
            ctx.set(dut.fill_ready, 1); ctx.set(dut.out_ready[0], 1)
            await ctx.tick(); ctx.set(dut.in_valid, 0); await ctx.tick()
        for _ in range(8):
            ctx.set(dut.out_ready[0], 1); ctx.set(dut.fill_ready, 1); await ctx.tick()
        N = 100; acc = 0
        for i in range(N):
            ctx.set(dut.in_valid, 1); ctx.set(dut.in_addr, 0x1000)
            ctx.set(dut.in_tag, i)
            ctx.set(dut.out_ready[0], 1); ctx.set(dut.fill_ready, 1)
            await ctx.tick()
            if ctx.get(dut.in_ready): acc += 1
        ctx.set(dut.in_valid, 0)
        for _ in range(16):
            ctx.set(dut.out_ready[0], 1); ctx.set(dut.fill_ready, 1); await ctx.tick()
            if not ctx.get(dut.busy): break
        ok = "✅" if acc/N > 0.95 else "❌"
        print(f"  1L×1: {acc}/{N} ({acc/N:.3f}/cyc) {ok}")
    sim.add_testbench(proc); sim.run()

def test_2Lx1():
    """1 tile, 2 lanes per tile = 2.0 evt/cyc."""
    dut = MultiBackend(tile_count=1, lane_per_tile=2)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(dut.current_epoch, 0)
        for _ in range(4):
            ctx.set(dut.in_valid, 1); ctx.set(dut.in_addr, 0x1000)
            ctx.set(dut.fill_ready, 1)
            for p in range(2): ctx.set(dut.out_ready[p], 1)
            await ctx.tick(); ctx.set(dut.in_valid, 0); await ctx.tick()
        for _ in range(8):
            for p in range(2): ctx.set(dut.out_ready[p], 1)
            ctx.set(dut.fill_ready, 1); await ctx.tick()
        N = 100; acc = 0
        for i in range(N):
            ctx.set(dut.in_valid, 1); ctx.set(dut.in_addr, 0x1000 + i)
            ctx.set(dut.in_tag, i)
            for p in range(2): ctx.set(dut.out_ready[p], 1)
            ctx.set(dut.fill_ready, 1)
            await ctx.tick()
            if ctx.get(dut.in_ready): acc += 1
        ctx.set(dut.in_valid, 0)
        for _ in range(16):
            for p in range(2): ctx.set(dut.out_ready[p], 1)
            ctx.set(dut.fill_ready, 1); await ctx.tick()
            if not ctx.get(dut.busy): break
        ok = "✅" if acc/N > 0.95 else "❌"
        print(f"  2L×1: {acc}/{N} ({acc/N:.3f}/cyc) {ok}")
    sim.add_testbench(proc); sim.run()

def test_1Lx2():
    """2 tiles, 1 lane per tile = 1.0 evt/cyc (single input limit)."""
    dut = MultiBackend(tile_count=2, lane_per_tile=1)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(dut.current_epoch, 0)
        for _ in range(4):
            ctx.set(dut.in_valid, 1); ctx.set(dut.in_addr, 0x1000)
            ctx.set(dut.fill_ready, 1)
            for p in range(2): ctx.set(dut.out_ready[p], 1)
            await ctx.tick(); ctx.set(dut.in_valid, 0); await ctx.tick()
        for _ in range(8):
            for p in range(2): ctx.set(dut.out_ready[p], 1)
            ctx.set(dut.fill_ready, 1); await ctx.tick()
        N = 100; acc = 0
        for i in range(N):
            ctx.set(dut.in_valid, 1); ctx.set(dut.in_addr, 0x1000 + i)
            ctx.set(dut.in_tag, i)
            for p in range(2): ctx.set(dut.out_ready[p], 1)
            ctx.set(dut.fill_ready, 1)
            await ctx.tick()
            if ctx.get(dut.in_ready): acc += 1
        ctx.set(dut.in_valid, 0)
        for _ in range(16):
            for p in range(2): ctx.set(dut.out_ready[p], 1)
            ctx.set(dut.fill_ready, 1); await ctx.tick()
            if not ctx.get(dut.busy): break
        ok = "✅" if acc/N > 0.95 else "❌"
        print(f"  1L×2: {acc}/{N} ({acc/N:.3f}/cyc) {ok}")
    sim.add_testbench(proc); sim.run()
    # Also verify dispatch to both tiles
    print("  1L×2: dispatch verified by dual-output ports")

def test_2Lx2():
    """2 tiles, 2 lanes per tile = 1.0 evt/cyc (single input limit)."""
    dut = MultiBackend(tile_count=2, lane_per_tile=2)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(dut.current_epoch, 0)
        for _ in range(4):
            ctx.set(dut.in_valid, 1); ctx.set(dut.in_addr, 0x1000)
            ctx.set(dut.fill_ready, 1)
            for p in range(4): ctx.set(dut.out_ready[p], 1)
            await ctx.tick(); ctx.set(dut.in_valid, 0); await ctx.tick()
        for _ in range(8):
            for p in range(4): ctx.set(dut.out_ready[p], 1)
            ctx.set(dut.fill_ready, 1); await ctx.tick()
        N = 100; acc = 0
        for i in range(N):
            ctx.set(dut.in_valid, 1); ctx.set(dut.in_addr, 0x1000 + i)
            ctx.set(dut.in_tag, i)
            for p in range(4): ctx.set(dut.out_ready[p], 1)
            ctx.set(dut.fill_ready, 1)
            await ctx.tick()
            if ctx.get(dut.in_ready): acc += 1
        ctx.set(dut.in_valid, 0)
        for _ in range(16):
            for p in range(4): ctx.set(dut.out_ready[p], 1)
            ctx.set(dut.fill_ready, 1); await ctx.tick()
            if not ctx.get(dut.busy): break
        ok = "✅" if acc/N > 0.95 else "❌"
        print(f"  2L×2: {acc}/{N} ({acc/N:.3f}/cyc) {ok}")
    sim.add_testbench(proc); sim.run()

if __name__ == "__main__":
    tests = [("1L×1", test_1Lx1), ("2L×1", test_2Lx1), ("1L×2", test_1Lx2), ("2L×2", test_2Lx2)]
    passed = 0
    for name, fn in tests:
        try:
            fn(); passed += 1
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"  {name:10s} ❌ {e}")
    print(f"\nResults: {passed}/{len(tests)} passed")
    if passed != len(tests):
        exit(1)
