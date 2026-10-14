# -*- coding: utf-8 -*-
"""Step56: Clean->Move reloc stream must tolerate link backpressure.

We stall GC3ChipSystem.reloc_link_enable so the link FIFO cannot drain.
Then we commit two relocations from different cores. One update will enter the
link FIFO, the other must remain pending at Clean until the link resumes.

Run:
  python -m tests.test_step56_reloc_stream_backpressure
"""

from __future__ import annotations

from amaranth.sim import Simulator, Tick

from rtl.gc_3chip_system import GC3ChipSystem
from rtl.isa import GC_NEW, GC_RELOC
from rtl.gc_mv_coproc import MV_QUERY


def main():
    tb = GC3ChipSystem(
        ncores=2,
        reloc_link_depth=1,
        enable_scan=False,
        clean_kwargs=dict(entries=32, fifo_depth=2, engine_latency=0,
                         card_dedup_enable=True, card_table_size=4, card_table_ways=1, card_index_mode=0),
        move_kwargs=dict(fifo_depth=2, map_depth=8, chase_depth=1),
    )

    sim = Simulator(tb)
    sim.add_clock(1e-6)

    clean = tb.clean
    move = tb.move

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

        # Wait response
        for _ in range(80):
            if (yield clean.rsp_valid[core]):
                data = (yield clean.rsp_data[core])
                trap = (yield clean.trap[core])
                yield clean.rsp_take[core].eq(1)
                yield Tick()
                yield clean.rsp_take[core].eq(0)
                return data, trap
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
        for _ in range(80):
            if (yield move.rsp_valid[core]):
                got = (yield move.rsp_data[core])
                yield move.rsp_take[core].eq(1)
                yield Tick()
                yield move.rsp_take[core].eq(0)
                return got
            yield Tick()
        assert False, "mv response timeout"

    def proc():
        # Stall reloc link delivery
        yield tb.reloc_link_enable.eq(0)

        # Allocate two handles on different cores
        h1, trap1 = (yield from enq_clean(0, GC_NEW, rd=1, rs1=0, rs2=0, tag=1))
        assert trap1 == 0
        h2, trap2 = (yield from enq_clean(1, GC_NEW, rd=1, rs1=0, rs2=0, tag=2))
        assert trap2 == 0

        # Commit relocations (core0 and core1)
        _, t3 = (yield from enq_clean(0, GC_RELOC, rd=0, rs1=h1, rs2=10, tag=3))
        assert t3 == 0
        _, t4 = (yield from enq_clean(1, GC_RELOC, rd=0, rs1=h2, rs2=20, tag=4))
        assert t4 == 0

        # Let things settle (link still stalled)
        for _ in range(5):
            yield Tick()

        # Resume link
        yield tb.reloc_link_enable.eq(1)

        # Wait a bit for FIFO drain + move update capture
        for _ in range(20):
            yield Tick()

        got1 = (yield from mv_query(0, h1, tag=11))
        got2 = (yield from mv_query(1, h2, tag=12))
        assert got1 == 10, f"expected mapping {h1}->10, got {got1}"
        assert got2 == 20, f"expected mapping {h2}->20, got {got2}"

        print("OK: reloc stream survives link backpressure without dropping updates.")

    sim.add_sync_process(proc)
    sim.run()


if __name__ == "__main__":
    main()
