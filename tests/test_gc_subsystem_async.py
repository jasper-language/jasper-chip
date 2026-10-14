#!/usr/bin/env python3
"""test_gc_subsystem_async.py — 验证异步 GC 退休永不 stall 流水线。"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from amaranth.sim import Simulator
from rtl.gc_subsystem_async import GCSubsystemAsync
from rtl.isa import GC_NEW


def test_gc_fire_independent_of_enq_ready():
    """gc_enq_ready=false 时 gc_fire=1，stall_gc_issue=0。"""
    dut = GCSubsystemAsync(core_id=0, gc_slots=16)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def proc(ctx):
        ctx.set(dut.is_valid, 1)
        ctx.set(dut.is_opcode, 11)
        ctx.set(dut.is_funct3, GC_NEW)
        ctx.set(dut.is_rd, 1)
        ctx.set(dut.is_rs1, 5)
        ctx.set(dut.is_rs2, 6)
        ctx.set(dut.fence_active, 0)
        ctx.set(dut.stall, 0)
        ctx.set(dut.gc_enq_ready, 0)

        await ctx.tick()
        gf = ctx.get(dut.gc_fire)
        so = ctx.get(dut.stall_gc_order)
        si = ctx.get(dut.stall_gc_issue)
        assert gf == 1, f"gc_fire should be 1, got {gf}"
        assert si == 0, f"stall_gc_issue should be 0, got {si}"
        print(f"  gc_fire={gf} stall_order={so} stall_issue={si}")

        # After posedge, replay captured data → gc_enq_valid=1
        ev = ctx.get(dut.gc_enq_valid)
        assert ev == 1, f"gc_enq_valid should be 1 after fire, got {ev}"
        print(f"  gc_enq_valid={ev} (replay holding, stuck by enq_ready=0)")

        # Drain
        ctx.set(dut.gc_enq_ready, 1)
        ctx.set(dut.is_valid, 0)
        await ctx.tick()
        ev2 = ctx.get(dut.gc_enq_valid)
        print(f"  after drain: gc_enq_valid={ev2}")

        print("  PASS test_gc_fire_independent_of_enq_ready")

    sim.add_testbench(proc)
    sim.run()


def test_no_stall_on_gc_issue():
    """连续发 GC_NEW 不被 gc_enq_ready 阻塞（但 replay 满时 stall_gc_issue=1）。"""
    dut = GCSubsystemAsync(core_id=0, gc_slots=16)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def proc(ctx):
        ctx.set(dut.is_opcode, 11)
        ctx.set(dut.is_funct3, GC_NEW)
        ctx.set(dut.is_rd, 1)
        ctx.set(dut.is_rs1, 5)
        ctx.set(dut.is_rs2, 6)
        ctx.set(dut.fence_active, 0)
        ctx.set(dut.stall, 0)
        ctx.set(dut.gc_enq_ready, 0)

        stalls = 0
        fires = 0
        for i in range(6):
            ctx.set(dut.is_valid, 1)
            await ctx.tick()
            gf = ctx.get(dut.gc_fire)
            si = ctx.get(dut.stall_gc_issue)
            print(f"  cyc={i}: gc_fire={gf} stall_issue={si}")
            if gf: fires += 1
            if si: stalls += 1
            ctx.set(dut.is_valid, 0)

        # gc_fire depends on slot avail (16) → all 6 fire
        # stall_gc_issue when replay full (depth=2) + gc_enq_ready=0
        print(f"  fires={fires} stalls={stalls}")
        assert fires == 6, f"should fire 6 times, got {fires}"
        assert stalls > 0, "should stall when replay full"

        # Drain replay → gc_fire should still work
        ctx.set(dut.gc_enq_ready, 1)
        await ctx.tick()
        ctx.set(dut.is_valid, 1)
        await ctx.tick()
        gf2 = ctx.get(dut.gc_fire)
        si2 = ctx.get(dut.stall_gc_issue)
        print(f"  after drain: gc_fire={gf2} stall_issue={si2}")
        assert gf2 == 1, "gc_fire should work after replay drains"

        print("  PASS test_no_stall_on_gc_issue")

    sim.add_testbench(proc)
    sim.run()


def test_response_match_and_slot_free():
    """GC 响应正确匹配 tag 并释放 slot。"""
    dut = GCSubsystemAsync(core_id=0, gc_slots=16)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def proc(ctx):
        ctx.set(dut.is_valid, 1)
        ctx.set(dut.is_opcode, 11)
        ctx.set(dut.is_funct3, GC_NEW)
        ctx.set(dut.is_rd, 5)
        ctx.set(dut.is_rs1, 5)
        ctx.set(dut.is_rs2, 6)
        ctx.set(dut.fence_active, 0)
        ctx.set(dut.stall, 0)
        ctx.set(dut.gc_enq_ready, 1)

        # Fire 1st GC_NEW → slot allocated
        await ctx.tick()
        gf = ctx.get(dut.gc_fire)
        tag = ctx.get(dut.gc_tag)
        assert gf, "gc_fire should be 1"
        print(f"  1st fire: gc_fire={gf} tag={tag}")
        ctx.set(dut.is_valid, 0)

        # Set GC response — read match BEFORE tick (combinational)
        ctx.set(dut.gc_rsp_valid, 1)
        ctx.set(dut.gc_rsp_tag, tag)
        ctx.set(dut.gc_rsp_rd, 5)
        ctx.set(dut.gc_rsp_data, 0x42)

        rm = ctx.get(dut.gc_rsp_match)
        ri = ctx.get(dut.gc_rsp_match_idx)
        rt = ctx.get(dut.gc_rsp_take)
        print(f"  before tick: gc_rsp_match={rm} idx={ri} rsp_take={rt}")
        assert rm, "gc_rsp_match should be 1 before tick"

        # Tick: posedge clears gw[idx], gc_rsp_match becomes 0
        await ctx.tick()
        rm2 = ctx.get(dut.gc_rsp_match)
        assert rm2 == 0, "gc_rsp_match should be 0 after clearance"
        print(f"  after tick: gc_rsp_match={rm2}")

        ctx.set(dut.gc_rsp_valid, 0)
        ctx.set(dut.gc_rsp_tag, 0)
        ctx.set(dut.gc_rsp_rd, 0)
        ctx.set(dut.gc_rsp_data, 0)

        # Free slot → can fire again
        ctx.set(dut.is_valid, 1)
        await ctx.tick()
        gf2 = ctx.get(dut.gc_fire)
        assert gf2, "gc_fire should be 1 again (slot freed)"
        print(f"  2nd fire: gc_fire={gf2} (slot recycled)")

        print("  PASS test_response_match_and_slot_free")

    sim.add_testbench(proc)
    sim.run()


def test_slot_exhaustion_still_stalls():
    """gc_slots=4 时第 5 次 gc_fire=0，stall_gc_order=1。"""
    dut = GCSubsystemAsync(core_id=0, gc_slots=4)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def proc(ctx):
        ctx.set(dut.is_opcode, 11)
        ctx.set(dut.is_funct3, GC_NEW)
        ctx.set(dut.is_rd, 1)
        ctx.set(dut.is_rs1, 5)
        ctx.set(dut.is_rs2, 6)
        ctx.set(dut.fence_active, 0)
        ctx.set(dut.stall, 0)
        ctx.set(dut.gc_enq_ready, 1)

        fires = 0
        orders = 0
        for i in range(10):
            ctx.set(dut.is_valid, 1)
            await ctx.tick()
            gf = ctx.get(dut.gc_fire)
            so = ctx.get(dut.stall_gc_order)
            print(f"  cyc={i}: gc_fire={gf} stall_order={so}")
            if gf: fires += 1
            if so: orders += 1
            ctx.set(dut.is_valid, 0)

        print(f"  fires={fires} orders={orders}")
        # N slots → N-1 observable fires (last allocation happens at posedge,
        # read after tick shows 0 free slots).
        assert fires == 3, f"should fire S-1=3 times (slots=4), got {fires}"
        assert orders > 0, "should stall_order when slots full"

        print("  PASS test_slot_exhaustion_still_stalls")

    sim.add_testbench(proc)
    sim.run()


if __name__ == "__main__":
    test_gc_fire_independent_of_enq_ready()
    test_no_stall_on_gc_issue()
    test_response_match_and_slot_free()
    test_slot_exhaustion_still_stalls()
    print("\nAll tests PASS")
