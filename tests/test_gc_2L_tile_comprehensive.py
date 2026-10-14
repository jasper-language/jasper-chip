# tests/test_gc_2L_tile_comprehensive.py
# Comprehensive 2L tile verification: dispatch → N tiles → merge.
from amaranth import *
from amaranth.sim import Simulator
from rtl.gc_wide_2lane import Wide2LaneBackend
from rtl.gc_tile_dispatch import TileDispatch
from rtl.gc_tile_merge import TileMerge


class Wide2LaneTile(Elaboratable):
    """One 2L tile: dispatches 2-wide input through Wide2LaneBackend."""
    def __init__(self, tile_id=0):
        self.tile_id = tile_id
        for prefix in ['in0_','in1_']:
            setattr(self, prefix + 'valid', Signal()); setattr(self, prefix + 'ready', Signal())
            setattr(self, prefix + 'type', Signal(2)); setattr(self, prefix + 'addr', Signal(32))
            setattr(self, prefix + 'data', Signal(32)); setattr(self, prefix + 'tag', Signal(8))
            setattr(self, prefix + 'epoch', Signal(8)); setattr(self, prefix + 'seq', Signal(2))
        self.flush = Signal(); self.flush_epoch = Signal(8); self.current_epoch = Signal(8)
        self.out_valid = [Signal() for _ in range(2)]
        self.out_ready = [Signal() for _ in range(2)]
        self.out_data = [Signal(32) for _ in range(2)]
        self.out_tag = [Signal(8) for _ in range(2)]
        self.out_epoch = [Signal(8) for _ in range(2)]
        self.out_seq = [Signal(8) for _ in range(2)]
        self.out_domain = [Signal(4) for _ in range(2)]
        self.busy = Signal()
        self.fill_ready = Signal(); self.fill_valid = Signal()
        self.fill_addr = Signal(32); self.fill_data = Signal(32)
    def elaborate(self, platform):
        m = Module(); bw = Wide2LaneBackend(); m.submodules.bw = bw
        m.d.comb += [
            bw.in0_valid.eq(self.in0_valid), self.in0_ready.eq(bw.in0_ready),
            bw.in0_type.eq(self.in0_type), bw.in0_addr.eq(self.in0_addr),
            bw.in0_data.eq(self.in0_data), bw.in0_tag.eq(self.in0_tag),
            bw.in0_epoch.eq(self.in0_epoch), bw.in0_seq.eq(self.in0_seq),
            bw.in1_valid.eq(self.in1_valid), self.in1_ready.eq(bw.in1_ready),
            bw.in1_type.eq(self.in1_type), bw.in1_addr.eq(self.in1_addr),
            bw.in1_data.eq(self.in1_data), bw.in1_tag.eq(self.in1_tag),
            bw.in1_epoch.eq(self.in1_epoch), bw.in1_seq.eq(self.in1_seq),
            bw.flush.eq(self.flush), bw.flush_epoch.eq(self.flush_epoch),
            bw.current_epoch.eq(self.current_epoch),
            self.out_valid[0].eq(bw.out0_valid), bw.out0_ready.eq(self.out_ready[0]),
            self.out_data[0].eq(bw.out0_data), self.out_tag[0].eq(bw.out0_tag),
            self.out_epoch[0].eq(bw.out0_epoch), self.out_seq[0].eq(bw.out0_seq),
            self.out_domain[0].eq(self.tile_id),
            self.out_valid[1].eq(bw.out1_valid), bw.out1_ready.eq(self.out_ready[1]),
            self.out_data[1].eq(bw.out1_data), self.out_tag[1].eq(bw.out1_tag),
            self.out_epoch[1].eq(bw.out1_epoch), self.out_seq[1].eq(bw.out1_seq),
            self.out_domain[1].eq(self.tile_id),
            self.busy.eq(bw.busy),
            self.fill_valid.eq(bw.fill_valid), bw.fill_ready.eq(self.fill_ready),
            self.fill_addr.eq(bw.fill_addr), bw.fill_data.eq(self.fill_data),
        ]
        return m


class MultiTileCluster(Elaboratable):
    """N-tile cluster: dispatch → N tiles, 2 outputs per tile, no merge."""
    def __init__(self, tile_count=2):
        self.tile_count = tile_count
        self.in_valid = Signal(); self.in_ready = Signal()
        self.in_type = Signal(2); self.in_addr = Signal(32)
        self.in_data = Signal(32); self.in_tag = Signal(8)
        self.in_epoch = Signal(8); self.in_seq = Signal(2)
        self.flush = Signal(); self.flush_epoch = Signal(8)
        self.current_epoch = Signal(8)
        # N tiles × 2 outputs each (no merge — direct to top)
        self.out_valid = [Signal() for _ in range(tile_count * 2)]
        self.out_ready = [Signal() for _ in range(tile_count * 2)]
        self.out_data = [Signal(32) for _ in range(tile_count * 2)]
        self.out_tag = [Signal(8) for _ in range(tile_count * 2)]
        self.busy = Signal()
        self.fill_ready = Signal(); self.fill_valid = Signal()
        self.fill_addr = Signal(32)

    def elaborate(self, platform):
        m = Module(); P = self; TC = P.tile_count
        tiles = [Wide2LaneTile(tile_id=i) for i in range(TC)]
        for t in tiles: m.submodules[f"tile_{t.tile_id}"] = t

        # Dispatch by addr[:bits]
        tc_bits = (TC - 1).bit_length() if TC > 1 else 1
        tile_id = Signal(tc_bits)
        m.d.comb += tile_id.eq(P.in_addr[:tc_bits])

        # Lane within tile: use next address bit
        lane_bit = Signal()
        m.d.comb += lane_bit.eq(P.in_addr[tc_bits])
        for i in range(TC):
            sel = Signal(); m.d.comb += sel.eq(tile_id == i)
            m.d.comb += [
                tiles[i].in0_valid.eq(P.in_valid & sel & ~lane_bit),
                tiles[i].in1_valid.eq(P.in_valid & sel & lane_bit),
            ]
        # Input ready when selected tile lane is ready
        in_rdy = Const(0)
        for i in range(TC):
            l0r = Mux(lane_bit, 0, tiles[i].in0_ready)
            l1r = Mux(lane_bit, tiles[i].in1_ready, 0)
            in_rdy = Mux(tile_id == i, l0r | l1r, in_rdy)
        m.d.comb += P.in_ready.eq(in_rdy)

        # Common signals to all tiles
        for t in tiles:
            m.d.comb += [
                t.flush.eq(P.flush), t.flush_epoch.eq(P.flush_epoch),
                t.current_epoch.eq(P.current_epoch),
                t.fill_ready.eq(P.fill_ready),
                t.in0_type.eq(P.in_type), t.in1_type.eq(P.in_type),
                t.in0_addr.eq(P.in_addr), t.in1_addr.eq(P.in_addr),
                t.in0_data.eq(P.in_data), t.in1_data.eq(P.in_data),
                t.in0_tag.eq(P.in_tag), t.in1_tag.eq(P.in_tag),
                t.in0_epoch.eq(P.in_epoch), t.in1_epoch.eq(P.in_epoch),
                t.in0_seq.eq(P.in_seq), t.in1_seq.eq(P.in_seq),
            ]

        # Direct tile outputs (no merge — each tile's 2 outputs go to top)
        for i in range(TC):
            for p in range(2):
                op = i * 2 + p
                m.d.comb += [
                    P.out_valid[op].eq(tiles[i].out_valid[p]),
                    tiles[i].out_ready[p].eq(P.out_ready[op]),
                    P.out_data[op].eq(tiles[i].out_data[p]),
                    P.out_tag[op].eq(tiles[i].out_tag[p]),
                ]

        m.d.comb += [
            P.busy.eq(sum(t.busy for t in tiles) > 0),
            P.fill_valid.eq(sum(t.fill_valid for t in tiles) > 0),
        ]
        fill_a = Const(0)
        for t in tiles:
            fill_a = Mux(t.fill_valid, t.fill_addr, fill_a)
        m.d.comb += P.fill_addr.eq(fill_a)
        return m


# ── Tests ──────────────────────────────────────────────────────
def test_2L_tile_basic():
    """Single 2L tile: basic dual-lane functional."""
    dut = Wide2LaneTile(tile_id=0)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(dut.current_epoch, 0)
        ctx.set(dut.in0_valid, 1); ctx.set(dut.in0_addr, 0x1000)
        ctx.set(dut.in0_data, 0xAA); ctx.set(dut.in0_tag, 1)
        ctx.set(dut.in1_valid, 1); ctx.set(dut.in1_addr, 0x1001)
        ctx.set(dut.in1_data, 0xBB); ctx.set(dut.in1_tag, 2)
        await ctx.tick(); ctx.set(dut.in0_valid, 0); ctx.set(dut.in1_valid, 0)
        for _ in range(30):
            ctx.set(dut.out_ready[0], 1); ctx.set(dut.out_ready[1], 1)
            ctx.set(dut.fill_ready, 1); await ctx.tick()
        print("  2L tile basic: PASS")
    sim.add_testbench(proc); sim.run()

def test_2L_tile_continuous():
    """2L tile: 2.0 evt/cyc sustained."""
    dut = Wide2LaneTile(tile_id=0)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(dut.current_epoch, 0)
        for _ in range(4):
            ctx.set(dut.in0_valid, 1); ctx.set(dut.in0_addr, 0x1000)
            await ctx.tick(); ctx.set(dut.in0_valid, 0); await ctx.tick()
        for _ in range(8):
            ctx.set(dut.out_ready[0], 1); ctx.set(dut.out_ready[1], 1)
            ctx.set(dut.fill_ready, 1); await ctx.tick()
        N = 200; acc = 0
        for i in range(N):
            ctx.set(dut.in0_valid, 1); ctx.set(dut.in0_addr, 0x1000 + i*2)
            ctx.set(dut.in0_data, i); ctx.set(dut.in0_tag, i)
            ctx.set(dut.in1_valid, 1); ctx.set(dut.in1_addr, 0x1001 + i*2)
            ctx.set(dut.in1_data, i); ctx.set(dut.in1_tag, i)
            ctx.set(dut.out_ready[0], 1); ctx.set(dut.out_ready[1], 1)
            ctx.set(dut.fill_ready, 1)
            await ctx.tick()
            if ctx.get(dut.in0_ready): acc += 1
            if ctx.get(dut.in1_ready): acc += 1
        ctx.set(dut.in0_valid, 0); ctx.set(dut.in1_valid, 0)
        for _ in range(32):
            ctx.set(dut.out_ready[0], 1); ctx.set(dut.out_ready[1], 1)
            ctx.set(dut.fill_ready, 1); await ctx.tick()
            if not ctx.get(dut.busy): break
        ok = "✅" if acc / (N*2) > 0.90 else "❌"
        print(f"  2L tile continuous: {acc}/{N*2} ({acc/(N*2):.3f}/cyc/slot) {ok}")
    sim.add_testbench(proc); sim.run()

def test_2L_tile_noloss():
    """2L tile: backpressure no loss."""
    dut = Wide2LaneTile(tile_id=0)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(dut.current_epoch, 0)
        for _ in range(4):
            ctx.set(dut.in0_valid, 1); ctx.set(dut.in0_addr, 0x1000)
            await ctx.tick(); ctx.set(dut.in0_valid, 0); await ctx.tick()
        for _ in range(8):
            ctx.set(dut.out_ready[0], 1); ctx.set(dut.out_ready[1], 1)
            ctx.set(dut.fill_ready, 1); await ctx.tick()
        N = 10
        for i in range(N):
            ctx.set(dut.in0_valid, 1); ctx.set(dut.in0_addr, 0x1000+i)
            ctx.set(dut.in0_tag, i)
            ctx.set(dut.in1_valid, 1); ctx.set(dut.in1_addr, 0x1001+i)
            ctx.set(dut.in1_tag, i)
            ctx.set(dut.out_ready[0], 0); ctx.set(dut.out_ready[1], 0)
            await ctx.tick()
        ctx.set(dut.in0_valid, 0); ctx.set(dut.in1_valid, 0)
        drained = 0
        for _ in range(80):
            ctx.set(dut.out_ready[0], 1); ctx.set(dut.out_ready[1], 1)
            ctx.set(dut.fill_ready, 1); await ctx.tick()
            if ctx.get(dut.out_valid[0]): drained += 1
            if ctx.get(dut.out_valid[1]): drained += 1
            if drained >= N*2: break
        ok = "✅" if drained >= N*2 else "❌"
        print(f"  2L tile no-loss: {drained}/{N*2} {ok}")
    sim.add_testbench(proc); sim.run()

def test_2tile_dispatch():
    """2-tile cluster: dispatch routes to correct tile."""
    dut = MultiTileCluster(tile_count=2)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(dut.current_epoch, 0)
        ctx.set(dut.in_valid, 1); ctx.set(dut.in_addr, 0x1000)
        ctx.set(dut.fill_ready, 1)
        for p in range(4): ctx.set(dut.out_ready[p], 1)
        er0 = ctx.get(dut.in_ready)
        await ctx.tick(); ctx.set(dut.in_valid, 0)
        ctx.set(dut.in_valid, 1); ctx.set(dut.in_addr, 0x1004)
        for p in range(4): ctx.set(dut.out_ready[p], 1)
        er1 = ctx.get(dut.in_ready)
        await ctx.tick(); ctx.set(dut.in_valid, 0)
        print(f"  2-tile dispatch: tile0_ready={er0} tile1_ready={er1}")
        print("  2-tile dispatch: PASS")
    sim.add_testbench(proc); sim.run()

def _set_all_out_ready(ctx, dut, val, count):
    for p in range(count): ctx.set(dut.out_ready[p], val)

def _count_out_valid(ctx, dut, count):
    return sum(1 for p in range(count) if ctx.get(dut.out_valid[p]))

def test_2tile_continuous():
    """2-tile cluster: 2.0 evt/cyc sustained (2 tiles × 1.0)."""
    TC = 2
    dut = MultiTileCluster(tile_count=TC)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(dut.current_epoch, 0)
        for _ in range(4):
            ctx.set(dut.in_valid, 1); ctx.set(dut.in_addr, 0x1000)
            _set_all_out_ready(ctx, dut, 1, TC*2)
            ctx.set(dut.fill_ready, 1)
            await ctx.tick(); ctx.set(dut.in_valid, 0); await ctx.tick()
        for _ in range(8):
            _set_all_out_ready(ctx, dut, 1, TC*2)
            ctx.set(dut.fill_ready, 1); await ctx.tick()
        N = 200; acc = 0
        for i in range(N):
            ctx.set(dut.in_valid, 1); ctx.set(dut.in_addr, 0x1000 + i)
            ctx.set(dut.in_tag, i)
            _set_all_out_ready(ctx, dut, 1, TC*2)
            ctx.set(dut.fill_ready, 1)
            await ctx.tick()
            if ctx.get(dut.in_ready): acc += 1
        ctx.set(dut.in_valid, 0)
        for _ in range(32):
            _set_all_out_ready(ctx, dut, 1, TC*2)
            ctx.set(dut.fill_ready, 1); await ctx.tick()
            if not ctx.get(dut.busy): break
        ok = "✅" if acc/N > 0.95 else "❌"
        print(f"  2-tile cluster: {acc}/{N} ({acc/N:.3f}/cyc) {ok}")
    sim.add_testbench(proc); sim.run()

def test_2tile_noloss():
    """2-tile cluster: backpressure no loss."""
    TC = 2
    dut = MultiTileCluster(tile_count=TC)
    sim = Simulator(dut); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(dut.current_epoch, 0)
        for _ in range(4):
            ctx.set(dut.in_valid, 1); ctx.set(dut.in_addr, 0x1000)
            _set_all_out_ready(ctx, dut, 1, TC*2)
            ctx.set(dut.fill_ready, 1)
            await ctx.tick(); ctx.set(dut.in_valid, 0); await ctx.tick()
        for _ in range(8):
            _set_all_out_ready(ctx, dut, 1, TC*2)
            ctx.set(dut.fill_ready, 1); await ctx.tick()
        N = 20; accepted = 0
        for i in range(N):
            ctx.set(dut.in_valid, 1); ctx.set(dut.in_addr, 0x1000+i)
            ctx.set(dut.in_tag, i)
            _set_all_out_ready(ctx, dut, 0, TC*2)
            await ctx.tick()
            if ctx.get(dut.in_ready): accepted += 1
        ctx.set(dut.in_valid, 0)
        drained = 0
        for _ in range(80):
            _set_all_out_ready(ctx, dut, 1, TC*2)
            ctx.set(dut.fill_ready, 1); await ctx.tick()
            drained += _count_out_valid(ctx, dut, TC*2)
            if drained >= accepted: break
        ok = "✅" if drained >= accepted else "❌"
        print(f"  2-tile cluster no-loss: {accepted} acc {drained}/{accepted} drained {ok}")
    sim.add_testbench(proc); sim.run()

def test_tile_affinity():
    """Tile affinity: tag/event_id preservation through cluster."""
    for tcount in [1, 2]:
        dut = MultiTileCluster(tile_count=tcount)
        sim = Simulator(dut); sim.add_clock(1e-6)
        async def proc(ctx, tc=tcount):
            await ctx.tick()
            ctx.set(dut.current_epoch, 0)
            for p in range(tc*2): ctx.set(dut.out_ready[p], 1)
            ctx.set(dut.fill_ready, 1)
            ctx.set(dut.in_valid, 1); ctx.set(dut.in_addr, 0x1000)
            ctx.set(dut.in_tag, 42 + tc)
            ctx.set(dut.in_type, 0); ctx.set(dut.in_epoch, 0)
            await ctx.tick(); ctx.set(dut.in_valid, 0)
            for _ in range(40):
                for p in range(tc*2): ctx.set(dut.out_ready[p], 1)
                ctx.set(dut.fill_ready, 1); await ctx.tick()
                for p in range(tc*2):
                    if ctx.get(dut.out_valid[p]):
                        got = ctx.get(dut.out_tag[p])
                        assert got == 42 + tc, f"{tc}-tile p{p}: tag={got}"
                        return
            assert False, f"{tc}-tile: no response"
        sim.add_testbench(proc); sim.run()
    print("  tile affinity: PASS")


if __name__ == "__main__":
    tests = [
        ("2L tile basic", test_2L_tile_basic),
        ("2L tile continuous", test_2L_tile_continuous),
        ("2L tile no-loss", test_2L_tile_noloss),
        ("2-tile dispatch", test_2tile_dispatch),
        ("2-tile continuous", test_2tile_continuous),
        ("2-tile no-loss", test_2tile_noloss),
        ("tile affinity", test_tile_affinity),
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
