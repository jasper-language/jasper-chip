#!/usr/bin/env python3
"""test_gc_slots_bank_integration.py — Integration tests for GCSlotsBank in GC frontend."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from amaranth.sim import Simulator
from amaranth import *
from rtl.gc_subsystem import GCSubsystem
from rtl.gc_subsystem_async import GCSubsystemAsync
from rtl.isa import GC_NEW
from rtl.gc_slots_bank import create_slots_bank, GCSlotsBankStandard, GCSlotsBanked


def test_standard_mode_identical_to_original():
    """Standard mode (bank_count=1) must match original inline behavior."""
    dut = GCSubsystemAsync(core_id=0, gc_slots=8,
                           gc_slots_bank_impl="standard", gc_slots_bank_count=1)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def proc(ctx):
        ctx.set(dut.is_opcode, 11)
        ctx.set(dut.is_funct3, GC_NEW)
        ctx.set(dut.is_rd, 1)
        ctx.set(dut.fence_active, 0)
        ctx.set(dut.stall, 0)
        ctx.set(dut.gc_enq_ready, 1)

        fills = 0
        tags = []
        for i in range(10):
            ctx.set(dut.is_valid, 1)
            await ctx.tick()
            gf = ctx.get(dut.gc_fire)
            if gf:
                tags.append(ctx.get(dut.gc_tag))
                fills += 1
            ctx.set(dut.is_valid, 0)
            if fills >= 7:
                break

        assert fills == 7, f"Should fill all 8 slots (7 observable fires), got {fills}"

        # Match & free one
        ctx.set(dut.gc_rsp_valid, 1)
        ctx.set(dut.gc_rsp_tag, tags[0])
        ctx.set(dut.gc_rsp_rd, 1)
        rm = ctx.get(dut.gc_rsp_match)
        assert rm, f"Should match tag {tags[0]}"
        await ctx.tick()
        ctx.set(dut.gc_rsp_valid, 0)

        # Now gc_fire should work again (slot freed)
        ctx.set(dut.is_valid, 1)
        await ctx.tick()
        gf2 = ctx.get(dut.gc_fire)
        assert gf2, "gc_fire should work after freeing a slot"
        ctx.set(dut.is_valid, 0)
        await ctx.tick()

        print("  PASS: standard_mode_identical_to_original")

    sim.add_testbench(proc)
    sim.run()


def test_banked_mode_through_async():
    """Banked mode through async subsystem: basic alloc/free/match cycle works."""
    GC = 8
    BK = 2
    dut = GCSubsystemAsync(core_id=0, gc_slots=GC,
                           gc_slots_bank_impl="banked", gc_slots_bank_count=BK)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def proc(ctx):
        ctx.set(dut.is_opcode, 11)
        ctx.set(dut.is_funct3, GC_NEW)
        ctx.set(dut.is_rd, 1)
        ctx.set(dut.fence_active, 0)
        ctx.set(dut.stall, 0)
        ctx.set(dut.gc_enq_ready, 1)

        # Fire GC_NEW — alloc goes to a bank (gc_tag_ctr=0 → low bit 0 → bank 0)
        ctx.set(dut.is_valid, 1)
        await ctx.tick()
        gf = ctx.get(dut.gc_fire)
        assert gf, "gc_fire should be 1 in banked mode"
        tag = ctx.get(dut.gc_tag)
        ctx.set(dut.is_valid, 0)
        await ctx.tick()

        # Fire again — goes to other bank (gc_tag_ctr=1 → low bit 1 → bank 1)
        ctx.set(dut.is_valid, 1)
        await ctx.tick()
        gf2 = ctx.get(dut.gc_fire)
        assert gf2, "Second gc_fire should work"
        ctx.set(dut.is_valid, 0)
        await ctx.tick()

        # Match response for first alloc
        ctx.set(dut.gc_rsp_valid, 1)
        ctx.set(dut.gc_rsp_tag, tag)
        ctx.set(dut.gc_rsp_rd, 1)
        rm = ctx.get(dut.gc_rsp_match)
        assert rm, "gc_rsp_match should be 1 in banked mode"
        await ctx.tick()
        ctx.set(dut.gc_rsp_valid, 0)

        # gc_fire works after slot freed
        ctx.set(dut.is_valid, 1)
        await ctx.tick()
        gf3 = ctx.get(dut.gc_fire)
        assert gf3, "gc_fire should work after freeing"
        ctx.set(dut.is_valid, 0)
        await ctx.tick()

        print("  PASS: banked_mode_through_async")

    sim.add_testbench(proc)
    sim.run()


def test_banked_numa_routing():
    """NUMA routing: same tag always routes to same bank."""
    BK = 4
    dut = GCSlotsBanked(gc_slots=8, bank_count=BK)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def proc(ctx):
        async def do_alloc(tag):
            ctx.set(dut.alloc_tag, tag)
            ctx.set(dut.alloc_valid, 1)
            while not ctx.get(dut.alloc_ready):
                await ctx.tick()
            await ctx.tick()
            ctx.set(dut.alloc_valid, 0)
            await ctx.tick()

        async def do_free(tag):
            ctx.set(dut.free_tag, tag)
            ctx.set(dut.free_valid, 1)
            await ctx.tick()
            ctx.set(dut.free_valid, 0)
            await ctx.tick()

        async def do_query(tag):
            ctx.set(dut.match_tag, tag)
            ctx.set(dut.match_valid, 1)
            await ctx.tick()
            ctx.set(dut.match_valid, 0)
            found = ctx.get(dut.match_found)
            idx = ctx.get(dut.match_idx)
            return found, idx

        await do_alloc(0x00)
        found1, idx1 = await do_query(0x00)
        assert found1, "tag 0x00 should be found after alloc"

        await do_free(0x00)

        await do_alloc(0x00)
        found2, idx2 = await do_query(0x00)
        assert found2, "tag 0x00 should be found after re-alloc"

        # Both should be in same bank (bank 0 = global indices 0-1)
        assert idx1 // 2 == 0 and idx2 // 2 == 0, \
            f"Both allocs of tag 0x00 should route to bank 0, got idx1={idx1} idx2={idx2}"

        print("  PASS: banked_numa_routing")

    sim.add_testbench(proc)
    sim.run()


def test_banked_match_across_banks():
    """Match finds tag regardless of which bank holds it."""
    BK = 4
    dut = GCSlotsBanked(gc_slots=8, bank_count=BK)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def proc(ctx):
        async def do_alloc(tag):
            ctx.set(dut.alloc_tag, tag)
            ctx.set(dut.alloc_valid, 1)
            while not ctx.get(dut.alloc_ready):
                await ctx.tick()
            await ctx.tick()
            ctx.set(dut.alloc_valid, 0)
            await ctx.tick()

        # Alloc tags in different banks
        tags = [0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07]
        for t in tags:
            await do_alloc(t)

        # Match each tag — all must be found
        for t in tags:
            ctx.set(dut.match_tag, t)
            await ctx.tick()
            assert ctx.get(dut.match_found) == 1, f"tag 0x{t:02x} not found"
            idx = ctx.get(dut.match_idx)
            expected_bank = t & 0x03
            actual_bank = idx // 2
            assert actual_bank == expected_bank, \
                f"tag 0x{t:02x} idx={idx} bank={actual_bank} != expected={expected_bank}"

        print("  PASS: banked_match_across_banks")

    sim.add_testbench(proc)
    sim.run()


def test_standard_mode_through_gc_subsystem_sync():
    """Standard mode through sync subsystem (gc_fire depends on gc_enq_ready)."""
    dut = GCSubsystem(core_id=0, gc_slots=8,
                      gc_slots_bank_impl="standard", gc_slots_bank_count=1)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def proc(ctx):
        ctx.set(dut.is_opcode, 11)
        ctx.set(dut.is_funct3, GC_NEW)
        ctx.set(dut.is_rd, 1)
        ctx.set(dut.fence_active, 0)
        ctx.set(dut.stall, 0)
        ctx.set(dut.gc_enq_ready, 1)

        # Fire GC_NEW — read tag BEFORE tick (pre-increment = stored value)
        ctx.set(dut.is_valid, 1)
        tag = ctx.get(dut.gc_tag)
        await ctx.tick()
        gf = ctx.get(dut.gc_fire)
        assert gf, "gc_fire should be 1"
        ctx.set(dut.is_valid, 0)
        await ctx.tick()

        # Match response
        ctx.set(dut.gc_rsp_valid, 1)
        ctx.set(dut.gc_rsp_tag, tag)
        ctx.set(dut.gc_rsp_rd, 1)
        rm = ctx.get(dut.gc_rsp_match)
        assert rm, "gc_rsp_match should be 1"
        await ctx.tick()
        ctx.set(dut.gc_rsp_valid, 0)
        await ctx.tick()

        # Fire again after slot freed
        ctx.set(dut.is_valid, 1)
        await ctx.tick()
        gf2 = ctx.get(dut.gc_fire)
        assert gf2, "gc_fire should work again"
        ctx.set(dut.is_valid, 0)
        await ctx.tick()

        print("  PASS: standard_mode_through_gc_subsystem_sync")

    sim.add_testbench(proc)
    sim.run()


def test_stall_gc_issue_in_sync():
    """In sync subsystem, stall_gc_issue when gc_enq_ready=0 but alloc_ready=1."""
    dut = GCSubsystem(core_id=0, gc_slots=8,
                      gc_slots_bank_impl="standard", gc_slots_bank_count=1)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def proc(ctx):
        ctx.set(dut.is_opcode, 11)
        ctx.set(dut.is_funct3, GC_NEW)
        ctx.set(dut.is_rd, 1)
        ctx.set(dut.fence_active, 0)
        ctx.set(dut.stall, 0)
        ctx.set(dut.gc_enq_ready, 0)

        ctx.set(dut.is_valid, 1)
        await ctx.tick()
        gf = ctx.get(dut.gc_fire)
        si = ctx.get(dut.stall_gc_issue)
        so = ctx.get(dut.stall_gc_order)
        assert gf == 0, "gc_fire should be 0 when gc_enq_ready=0"
        assert si == 1, "stall_gc_issue should be 1 when gc_enq_ready=0"
        assert so == 0, "stall_gc_order should be 0 when slots available"
        ctx.set(dut.is_valid, 0)
        await ctx.tick()

        print("  PASS: stall_gc_issue_in_sync")

    sim.add_testbench(proc)
    sim.run()


def main():
    tests = [
        ("Standard mode identical to original",   test_standard_mode_identical_to_original),
        ("Banked mode through async",             test_banked_mode_through_async),
        ("Banked NUMA routing",                   test_banked_numa_routing),
        ("Banked match across banks",             test_banked_match_across_banks),
        ("Standard mode through sync subsystem",  test_standard_mode_through_gc_subsystem_sync),
        ("Stall gc issue in sync",                test_stall_gc_issue_in_sync),
    ]

    passed = 0
    failed = 0
    for name, fn in tests:
        print(f"[{name}]")
        try:
            fn()
            passed += 1
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"    FAIL: {e}")
            failed += 1

    total = passed + failed
    print(f"\n{'='*50}")
    print(f"Results: {passed}/{total} passed"
          + ("" if failed == 0 else f", {failed} FAILED"))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
