# tests/test_gc_forwarding_table.py — 完整 ForwardingTable 测试
from amaranth import *
from amaranth.sim import Simulator
from rtl.gc_forwarding_table import (
    ForwardingTableStandard, ForwardingTableBankedPipeline, create_forwarding_table
)

def test_factory():
    s = create_forwarding_table("standard")
    b = create_forwarding_table("banked_pipeline", bank_count=1)
    assert type(s).__name__ == "ForwardingTableStandard"
    assert type(b).__name__ == "ForwardingTableBankedPipeline"
    try:
        create_forwarding_table("invalid")
        assert False, "Should raise"
    except ValueError:
        pass
    print("  factory: PASS")

async def _run(ctx, ft, ops):
    if ctx is None:
        return []
    """Helper: run a list of operations on the forwarding table.
    Each op is a dict with keys:
      'type': 'update' | 'query' | 'flush' | 'epoch'
      'old_ptr', 'new_ptr', 'epoch', 'tag', 'flush'
    For queries, returns (hit, new_ptr) after the operation.
    """
    results = []
    for op in ops:
        if op['type'] == 'epoch':
            ctx.set(ft.epoch, op['value'])
            await ctx.tick()
        elif op['type'] == 'flush':
            ctx.set(ft.flush_epoch, op['value'])
            await ctx.tick()
            ctx.set(ft.flush_epoch, 0)
            await ctx.tick()
        elif op['type'] == 'update':
            ctx.set(ft.update_valid, 1)
            ctx.set(ft.update_old_ptr, op['old_ptr'])
            ctx.set(ft.update_new_ptr, op['new_ptr'])
            ctx.set(ft.update_epoch, op.get('epoch', 0))
            await ctx.tick()
            ctx.set(ft.update_valid, 0)
            await ctx.tick()
        elif op['type'] == 'query':
            ctx.set(ft.query_valid, 1)
            ctx.set(ft.query_old_ptr, op['old_ptr'])
            ctx.set(ft.query_tag, op.get('tag', 0))
            await ctx.tick()
            ctx.set(ft.query_valid, 0)
            ok = ctx.get(ft.rsp_valid)
            hit = ctx.get(ft.rsp_hit)
            new_ptr = ctx.get(ft.rsp_new_ptr)
            tag = ctx.get(ft.rsp_tag)
            results.append((ok, hit, new_ptr, tag))
            # Accept response
            ctx.set(ft.rsp_ready, 1)
            await ctx.tick()
            ctx.set(ft.rsp_ready, 0)
            await ctx.tick()
    return results

def test_multi_entry():
    """Multi-entry: update 3 entries, query all 3, verify distinct results."""
    ft = ForwardingTableStandard(map_depth=4, chase_depth=1)
    sim = Simulator(ft); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        res = await _run(ctx, ft, [
            {'type': 'epoch', 'value': 1},
            {'type': 'update', 'old_ptr': 0x1000, 'new_ptr': 0x2000, 'epoch': 1},
            {'type': 'update', 'old_ptr': 0x3000, 'new_ptr': 0x4000, 'epoch': 1},
            {'type': 'update', 'old_ptr': 0x5000, 'new_ptr': 0x6000, 'epoch': 1},
            {'type': 'query', 'old_ptr': 0x1000, 'tag': 0},
            {'type': 'query', 'old_ptr': 0x3000, 'tag': 0},
            {'type': 'query', 'old_ptr': 0x5000, 'tag': 0},
            {'type': 'query', 'old_ptr': 0x9999, 'tag': 0},
        ])
        expected = [(1,1,0x2000,0),(1,1,0x4000,0),(1,1,0x6000,0),(1,0,0x9999,0)]
        for (ok, h, np, t), (exp_ok, exp_h, exp_np, exp_t) in zip(res, expected):
            assert ok == exp_ok, f"ok={ok}"
            assert h == exp_h, f"hit={h} expect={exp_h}"
            assert np == exp_np, f"new=0x{np:x} expect=0x{exp_np:x}"
        print("  multi-entry: PASS")
    sim.add_testbench(proc); sim.run()

def test_backpressure():
    """rsp_ready=0 holds response stable."""
    ft = ForwardingTableStandard(map_depth=4)
    sim = Simulator(ft); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        await _run(ctx, ft, [
            {'type': 'epoch', 'value': 1},
            {'type': 'update', 'old_ptr': 0x1000, 'new_ptr': 0x2000, 'epoch': 1},
        ])
        # Query but don't accept
        ctx.set(ft.query_valid, 1); ctx.set(ft.query_old_ptr, 0x1000)
        await ctx.tick(); ctx.set(ft.query_valid, 0)
        # rsp_ready=0, hold for 2 cycles
        ctx.set(ft.rsp_ready, 0)
        await ctx.tick()
        assert ctx.get(ft.rsp_valid) == 1
        assert ctx.get(ft.rsp_hit) == 1
        assert ctx.get(ft.rsp_new_ptr) == 0x2000
        await ctx.tick()
        assert ctx.get(ft.rsp_valid) == 1
        assert ctx.get(ft.rsp_new_ptr) == 0x2000
        # Now accept
        ctx.set(ft.rsp_ready, 1); await ctx.tick()
        ctx.set(ft.rsp_ready, 0); await ctx.tick()
        assert ctx.get(ft.rsp_valid) == 0
        print("  backpressure: PASS")
    sim.add_testbench(proc); sim.run()

def test_epoch_flush():
    """flush_epoch clears matching entries."""
    ft = ForwardingTableStandard(map_depth=4)
    sim = Simulator(ft); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        await _run(ctx, ft, [
            {'type': 'epoch', 'value': 1},
            {'type': 'update', 'old_ptr': 0x1000, 'new_ptr': 0x2000, 'epoch': 1},
        ])
        # Query - should hit
        res = await _run(ctx, ft, [{'type': 'query', 'old_ptr': 0x1000}])
        assert res[0][1] == 1, "Should hit before flush"
        # Flush epoch 1
        await _run(ctx, ft, [{'type': 'flush', 'value': 1}])
        # Query - should miss
        res = await _run(ctx, ft, [{'type': 'query', 'old_ptr': 0x1000}])
        assert res[0][1] == 0, "Should miss after epoch flush"
        print("  epoch/flush: PASS")
    sim.add_testbench(proc); sim.run()

def test_chase():
    """chase_depth=2: A→B, B→C, query A returns C."""
    ft = ForwardingTableStandard(map_depth=8, chase_depth=2)
    sim = Simulator(ft); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        res = await _run(ctx, ft, [
            {'type': 'epoch', 'value': 1},
            {'type': 'update', 'old_ptr': 0x1000, 'new_ptr': 0x2000, 'epoch': 1},
            {'type': 'update', 'old_ptr': 0x2000, 'new_ptr': 0x3000, 'epoch': 1},
            {'type': 'query', 'old_ptr': 0x1000},
        ])
        ok, h, np, t = res[0]
        assert h == 1, f"Should hit, got {h}"
        assert np == 0x3000, f"Chase failed: 0x{np:x}"
        print("  chase: PASS")
    sim.add_testbench(proc); sim.run()



# Simpler banked1 test - standalone
def test_banked1_basic():
    ft = ForwardingTableBankedPipeline(bank_count=1, entries_per_bank=4, chase_depth=1)
    sim = Simulator(ft); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        res = await _run(ctx, ft, [
            {'type': 'epoch', 'value': 1},
            {'type': 'update', 'old_ptr': 0x1000, 'new_ptr': 0x2000, 'epoch': 1},
            {'type': 'query', 'old_ptr': 0x1000},
            {'type': 'query', 'old_ptr': 0x9999},
        ])
        h1, np1 = res[0][1], res[0][2]
        h2, np2 = res[1][1], res[1][2]
        assert h1 == 1 and np1 == 0x2000, f"hit1={h1} np1=0x{np1:x}"
        assert h2 == 0 and np2 == 0x9999, f"hit2={h2} np2=0x{np2:x}"
        print("  banked(1) basic: PASS")
    sim.add_testbench(proc); sim.run()

def test_banked1_escenario():
    """Same scenario on Standard and Banked(1) yields same results."""
    def run_ft(ft):
        sim = Simulator(ft); sim.add_clock(1e-6)
        results = []
        async def proc(ctx):
            await ctx.tick()
            res = await _run(ctx, ft, [
                {'type': 'epoch', 'value': 1},
                {'type': 'update', 'old_ptr': 0x100, 'new_ptr': 0x200, 'epoch': 1},
                {'type': 'update', 'old_ptr': 0x300, 'new_ptr': 0x400, 'epoch': 1},
                {'type': 'query', 'old_ptr': 0x100},
                {'type': 'query', 'old_ptr': 0x300},
                {'type': 'query', 'old_ptr': 0x500},
            ])
            results.append([(r[1], r[2]) for r in res])
        sim.add_testbench(proc); sim.run()
        return results[0]
    r_s = run_ft(ForwardingTableStandard(map_depth=4, chase_depth=1))
    r_b = run_ft(ForwardingTableBankedPipeline(bank_count=1, entries_per_bank=4, chase_depth=1))
    assert r_s == r_b, f"Standard={r_s} Banked={r_b}"
    print("  banked(1) ≡ standard: PASS")

def test_multi_bank():
    """Banked(4): multi-bank hit/miss."""
    ft = ForwardingTableBankedPipeline(bank_count=4, entries_per_bank=4, chase_depth=1)
    sim = Simulator(ft); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        res = await _run(ctx, ft, [
            {'type': 'epoch', 'value': 1},
            {'type': 'update', 'old_ptr': 0x10, 'new_ptr': 0x20, 'epoch': 1},
            {'type': 'update', 'old_ptr': 0x100, 'new_ptr': 0x200, 'epoch': 1},
            {'type': 'update', 'old_ptr': 0x1000, 'new_ptr': 0x2000, 'epoch': 1},
            {'type': 'update', 'old_ptr': 0x10000, 'new_ptr': 0x20000, 'epoch': 1},
            {'type': 'query', 'old_ptr': 0x10},
            {'type': 'query', 'old_ptr': 0x100},
            {'type': 'query', 'old_ptr': 0x1000},
            {'type': 'query', 'old_ptr': 0x10000},
            {'type': 'query', 'old_ptr': 0x9999},
        ])
        checks = [(0,1,0x20),(1,1,0x200),(2,1,0x2000),(3,1,0x20000),(4,0,0x9999)]
        for idx, exp_h, exp_np in checks:
            h, np = res[idx][1], res[idx][2]
            assert h == exp_h, f"q{idx} hit={h} expect={exp_h}"
            assert np == exp_np, f"q{idx} new=0x{np:x} expect=0x{exp_np:x}"
        print("  multi-bank(4): PASS")
    sim.add_testbench(proc); sim.run()

def test_tag_alignment():
    """rsp_tag matches query_tag."""
    ft = ForwardingTableStandard(map_depth=4, chase_depth=1)
    sim = Simulator(ft); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        await _run(ctx, ft, [
            {'type': 'epoch', 'value': 1},
            {'type': 'update', 'old_ptr': 0x1000, 'new_ptr': 0x2000, 'epoch': 1},
        ])
        for tag in [0x42, 0xA5, 0xFF]:
            res = await _run(ctx, ft, [{'type': 'query', 'old_ptr': 0x1000, 'tag': tag}])
            ok, h, np, t = res[0]
            assert h == 1, f"Miss at tag={tag}"
            assert t == tag, f"tag={t} expect={tag}"
        print("  tag alignment: PASS")
    sim.add_testbench(proc); sim.run()

def test_elaborate():
    from amaranth.back import rtlil
    m = Module(); m.submodules.ft = ForwardingTableStandard(map_depth=4, chase_depth=1)
    o = rtlil.convert(m, ports=[])
    m2 = Module(); m2.submodules.ft = ForwardingTableBankedPipeline(bank_count=4, entries_per_bank=4)
    o2 = rtlil.convert(m2, ports=[])
    print(f"  elaboration standard={len(o)} banked={len(o2)}: PASS")

# ── Test 11: Standard vs Banked(1) deep equivalence ──────────────
def test_deep_equiv():
    """Same 20-op sequence on Standard and Banked(1): all results identical."""
    ops = [
        {'type': 'epoch', 'value': 1},
        {'type': 'update', 'old_ptr': 0x1000, 'new_ptr': 0x2000, 'epoch': 1},
        {'type': 'update', 'old_ptr': 0x3000, 'new_ptr': 0x4000, 'epoch': 1},
        {'type': 'query', 'old_ptr': 0x1000, 'tag': 1},
        {'type': 'query', 'old_ptr': 0x5000, 'tag': 2},
        {'type': 'update', 'old_ptr': 0x2000, 'new_ptr': 0x3000, 'epoch': 1},
        {'type': 'query', 'old_ptr': 0x1000, 'tag': 3},
        {'type': 'flush', 'value': 1},
        {'type': 'query', 'old_ptr': 0x1000, 'tag': 4},
        {'type': 'epoch', 'value': 2},
        {'type': 'update', 'old_ptr': 0x4000, 'new_ptr': 0x5000, 'epoch': 2},
        {'type': 'query', 'old_ptr': 0x4000, 'tag': 5},
        {'type': 'query', 'old_ptr': 0x1000, 'tag': 6},
        {'type': 'update', 'old_ptr': 0x6000, 'new_ptr': 0x7000, 'epoch': 2},
        {'type': 'update', 'old_ptr': 0x7000, 'new_ptr': 0x8000, 'epoch': 2},
        {'type': 'query', 'old_ptr': 0x6000, 'tag': 7},
        {'type': 'flush', 'value': 2},
        {'type': 'query', 'old_ptr': 0x4000, 'tag': 8},
        {'type': 'epoch', 'value': 3},
        {'type': 'query', 'old_ptr': 0x9999, 'tag': 9},
    ]
    def run(ft):
        sim = Simulator(ft); sim.add_clock(1e-6)
        res = []
        async def proc(ctx):
            await ctx.tick()
            r = await _run(ctx, ft, ops)
            res.extend(r)
        sim.add_testbench(proc); sim.run()
        return list(res)
    r_s = run(ForwardingTableStandard(map_depth=8, chase_depth=2))
    r_b = run(ForwardingTableBankedPipeline(bank_count=1, entries_per_bank=8, chase_depth=2))
    assert len(r_s) == len(r_b), f"len S={len(r_s)} B={len(r_b)}"
    for i, ((ok_s, h_s, np_s, t_s), (ok_b, h_b, np_b, t_b)) in enumerate(zip(r_s, r_b)):
        assert ok_s == ok_b, f"op{i} ok"
        assert h_s == h_b, f"op{i} hit S={h_s} B={h_b}"
        assert np_s == np_b, f"op{i} ptr S=0x{np_s:x} B=0x{np_b:x}"
        assert t_s == t_b, f"op{i} tag S={t_s} B={t_b}"
    print("  deep equiv: PASS")

# ── Test 12: Multi-bank stress (2 banks, 16 entries) ────────────
def test_multi_bank_stress():
    """2 banks, 16 entries, interleaved queries across banks."""
    ft = ForwardingTableBankedPipeline(bank_count=2, entries_per_bank=8, chase_depth=1)
    sim = Simulator(ft); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(ft.epoch, 1); await ctx.tick()
        # 16 addresses: 8 even (bank 0), 8 odd (bank 1)
        even = [0x100 + i*0x20 for i in range(8)]   # 0x100, 0x120, ...
        odd  = [0x101 + i*0x20 for i in range(8)]   # 0x101, 0x121, ...
        addrs = even + odd
        for a in addrs:
            ctx.set(ft.update_valid, 1); ctx.set(ft.update_old_ptr, a)
            ctx.set(ft.update_new_ptr, a + 0x1000); ctx.set(ft.update_epoch, 1)
            await ctx.tick(); ctx.set(ft.update_valid, 0); await ctx.tick()
        for a in addrs:
            ctx.set(ft.query_valid, 1); ctx.set(ft.query_old_ptr, a)
            await ctx.tick(); ctx.set(ft.query_valid, 0)
            assert ctx.get(ft.rsp_hit) == 1, f"miss addr 0x{a:x}"
            assert ctx.get(ft.rsp_new_ptr) == a + 0x1000
            ctx.set(ft.rsp_ready, 1); await ctx.tick(); ctx.set(ft.rsp_ready, 0)
        print("  multi-bank stress(2×8): PASS")
    sim.add_testbench(proc); sim.run()

# ── Test 13: Multi-bank 4-way ───────────────────────────────────
def test_multi_bank_4way():
    """4 banks, 2 entries/bank, verify distribution."""
    ft = ForwardingTableBankedPipeline(bank_count=4, entries_per_bank=2, chase_depth=1)
    sim = Simulator(ft); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(ft.epoch, 1); await ctx.tick()
        # 8 updates: addr[1:0] cycles 0,1,2,3,0,1,2,3 → 4 banks, 2 each
        for old, new in [(0x00,0x10),(0x01,0x11),(0x02,0x12),(0x03,0x13),
                         (0x04,0x14),(0x05,0x15),(0x06,0x16),(0x07,0x17)]:
            ctx.set(ft.update_valid, 1); ctx.set(ft.update_old_ptr, old)
            ctx.set(ft.update_new_ptr, new); ctx.set(ft.update_epoch, 1)
            await ctx.tick(); ctx.set(ft.update_valid, 0); await ctx.tick()
        for old, new in [(0x00,0x10),(0x01,0x11),(0x02,0x12),(0x03,0x13),
                         (0x04,0x14),(0x05,0x15),(0x06,0x16),(0x07,0x17)]:
            ctx.set(ft.query_valid, 1); ctx.set(ft.query_old_ptr, old)
            await ctx.tick(); ctx.set(ft.query_valid, 0)
            assert ctx.get(ft.rsp_hit) == 1, f"miss 0x{old:x}"
            assert ctx.get(ft.rsp_new_ptr) == new
            ctx.set(ft.rsp_ready, 1); await ctx.tick(); ctx.set(ft.rsp_ready, 0)
        print("  multi-bank 4way: PASS")
    sim.add_testbench(proc); sim.run()

# ── Test 14: Full / overflow detection ─────────────────────────
def test_full_overflow():
    """map_depth=4, 5th update overflows (full=1, update_ready=0)."""
    ft = ForwardingTableStandard(map_depth=4, chase_depth=1)
    sim = Simulator(ft); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        ctx.set(ft.epoch, 1); await ctx.tick()
        for i in range(4):
            ctx.set(ft.update_valid, 1); ctx.set(ft.update_old_ptr, 0x1000*i)
            ctx.set(ft.update_new_ptr, 0x2000*i); ctx.set(ft.update_epoch, 1)
            await ctx.tick(); ctx.set(ft.update_valid, 0); await ctx.tick()
        # 4 entries filled. 5th update should show full/ready=0
        ctx.set(ft.update_valid, 1); ctx.set(ft.update_old_ptr, 0x5000)
        ctx.set(ft.update_new_ptr, 0x6000); ctx.set(ft.update_epoch, 1)
        await ctx.tick();
        assert ctx.get(ft.update_ready) == 0, "update_ready should be 0 (full)"
        print("  full overflow: PASS")
    sim.add_testbench(proc); sim.run()

# ── Test 15: rsp_tag coherence under backpressure ──────────────
def test_rsp_tag_coherence():
    """rsp_tag stays correct after multiple backpressure cycles."""
    ft = ForwardingTableStandard(map_depth=4, chase_depth=1)
    sim = Simulator(ft); sim.add_clock(1e-6)
    async def proc(ctx):
        await ctx.tick()
        await _run(ctx, ft, [
            {'type': 'epoch', 'value': 1},
            {'type': 'update', 'old_ptr': 0x1000, 'new_ptr': 0x2000, 'epoch': 1},
        ])
        # Query with tag=0x42, hold rsp_ready=0 for 3 cycles
        ctx.set(ft.query_valid, 1); ctx.set(ft.query_old_ptr, 0x1000)
        ctx.set(ft.query_tag, 0x42)
        await ctx.tick(); ctx.set(ft.query_valid, 0)
        ctx.set(ft.rsp_ready, 0)
        for _ in range(3):
            await ctx.tick()
            assert ctx.get(ft.rsp_tag) == 0x42, f"tag should stay 0x42, got {ctx.get(ft.rsp_tag)}"
            assert ctx.get(ft.rsp_hit) == 1
        ctx.set(ft.rsp_ready, 1); await ctx.tick(); ctx.set(ft.rsp_ready, 0)
        print("  rsp_tag coherence: PASS")
    sim.add_testbench(proc); sim.run()


if __name__ == "__main__":
    tests = [
        ("factory", test_factory),
        ("multi-entry", test_multi_entry),
        ("backpressure", test_backpressure),
        ("epoch/flush", test_epoch_flush),
        ("chase", test_chase),
        ("banked(1) basic", test_banked1_basic),
        ("banked(1) ≡ standard", test_banked1_escenario),
        ("multi-bank(4)", test_multi_bank),
        ("tag alignment", test_tag_alignment),
        ("elaboration", test_elaborate),
        ("deep equiv", test_deep_equiv),
        ("multi-bank stress", test_multi_bank_stress),
        ("multi-bank 4way", test_multi_bank_4way),
        ("full overflow", test_full_overflow),
        ("rsp_tag coherence", test_rsp_tag_coherence),
    ]
    passed = 0
    for name, fn in tests:
        try:
            fn()
            passed += 1
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"  {name:30s} ❌ {e}")
    print(f"\nResults: {passed}/{len(tests)} passed")
    if passed != len(tests):
        exit(1)
