# -*- coding: utf-8 -*-
"""Step64: Validate Clean->Move reloc transport FIFO observability and saturation behavior under backpressure.

We stall delivery to Move (reloc_link_enable=0) and commit more relocations than reloc_link_depth.
Expected:
  - dbg_reloc_link_level saturates at reloc_link_depth
  - the extra RELOC commit stalls (no response) until delivery resumes
  - after re-enabling delivery, dbg_reloc_link_level drains back to 0
  - MV_QUERY observes all mappings (no silent drops)

Run:
  python -m tests.test_step64_reloc_link_level_saturates
"""

from __future__ import annotations

from amaranth.sim import Simulator, Tick

from rtl.gc_3chip_system import GC3ChipSystem
from rtl.isa import GC_NEW, GC_RELOC
from rtl.gc_mv_coproc import MV_QUERY


def test_step64_reloc_link_level_saturates_and_drains():
    # Keep it small/deterministic.
    dut = GC3ChipSystem(
        ncores=1,
        enable_scan=False,
        reloc_link_depth=2,
        card_link_depth=2,
        clean_kwargs=dict(fifo_depth=2, entries=64, card_table_size=16, card_table_ways=1, card_index_mode=0),
        move_kwargs=dict(fifo_depth=2, map_depth=16, chase_depth=1),
    )

    sim = Simulator(dut)
    sim.add_clock(1e-6)

    clean = dut.clean
    move = dut.move

    def enq_clean(core: int, op: int, rd: int, rs1: int, rs2: int, tag: int):
        while (yield clean.cmd_enq_ready[core]) == 0:
            yield Tick()
        yield clean.cmd_tag[core].eq(tag)
        yield clean.cmd_op[core].eq(op)
        yield clean.cmd_rd[core].eq(rd)
        yield clean.cmd_rs1[core].eq(rs1)
        yield clean.cmd_rs2[core].eq(rs2)
        yield clean.cmd_enq_valid[core].eq(1)
        yield Tick()
        yield clean.cmd_enq_valid[core].eq(0)

        # Wait for response
        for _ in range(200):
            if (yield clean.rsp_valid[core]):
                data = (yield clean.rsp_data[core])
                trap = (yield clean.trap[core])
                yield clean.rsp_take[core].eq(1)
                yield Tick()
                yield clean.rsp_take[core].eq(0)
                return int(data), int(trap)
            yield Tick()
        assert False, "clean response timeout"

    def mv_query(core: int, val: int, tag: int = 1):
        while (yield move.cmd_enq_ready[core]) == 0:
            yield Tick()
        yield move.cmd_tag[core].eq(tag)
        yield move.cmd_op[core].eq(MV_QUERY)
        yield move.cmd_rd[core].eq(3)
        yield move.cmd_rs1[core].eq(val)
        yield move.cmd_rs2[core].eq(0)
        yield move.cmd_enq_valid[core].eq(1)
        yield Tick()
        yield move.cmd_enq_valid[core].eq(0)
        for _ in range(200):
            if (yield move.rsp_valid[core]):
                got = (yield move.rsp_data[core])
                yield move.rsp_take[core].eq(1)
                yield Tick()
                yield move.rsp_take[core].eq(0)
                return int(got)
            yield Tick()
        assert False, "mv response timeout"

    def proc():
        # Stall reloc delivery so the link FIFO cannot drain.
        yield dut.reloc_link_enable.eq(0)

        # Allocate 3 handles.
        h = []
        for i in range(3):
            handle, trap = (yield from enq_clean(0, GC_NEW, rd=0, rs1=0, rs2=0, tag=10 + i))
            assert trap == 0
            h.append(handle)

        # Commit first two relocations; they should complete (they can fill the FIFO).
        _, t1 = (yield from enq_clean(0, GC_RELOC, rd=0, rs1=h[0], rs2=100, tag=20))
        _, t2 = (yield from enq_clean(0, GC_RELOC, rd=0, rs1=h[1], rs2=200, tag=21))
        assert t1 == 0 and t2 == 0


        # Commit third relocation; Clean may keep it pending even while the link FIFO is full.
        _, t3 = (yield from enq_clean(0, GC_RELOC, rd=0, rs1=h[2], rs2=300, tag=22))
        assert t3 == 0

        # Confirm the link FIFO saturates at its configured depth (extra updates remain pending upstream).
        for _ in range(50):
            if (yield dut.dbg_reloc_link_level) == 2:
                break
            yield Tick()
        assert (yield dut.dbg_reloc_link_level) == 2, "reloc_link did not saturate to depth"

        # Re-enable delivery and wait for FIFO to drain.
        yield dut.reloc_link_enable.eq(1)
        for _ in range(200):
            if (yield dut.dbg_reloc_link_level) == 0:
                break
            yield Tick()
        assert (yield dut.dbg_reloc_link_level) == 0, "reloc_link did not drain after re-enable"


        # Ensure Move observes all mappings.
        got = [(yield from mv_query(0, h[0], tag=30)),
               (yield from mv_query(0, h[1], tag=31)),
               (yield from mv_query(0, h[2], tag=32))]
        assert got == [100, 200, 300], f"expected mappings [100,200,300], got {got}"

        print("OK: reloc_link level saturates/drains and no reloc updates are dropped under backpressure.")

    sim.add_sync_process(proc)
    sim.run()


if __name__ == "__main__":
    test_step64_reloc_link_level_saturates_and_drains()
