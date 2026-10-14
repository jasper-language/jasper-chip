# -*- coding: utf-8 -*-
"""Step55: 3-chip contract — epoch broadcast invalidates MV map.

We use GC3ChipSystem. Clean commits a RELOC (old->new) which must update MV.
Then we pulse the system epoch_advance; Move must invalidate the stale mapping.

Run:
  python -m tests.test_step55_3chip_epoch_invalidate_mv
"""

from __future__ import annotations

from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.gc_3chip_system import GC3ChipSystem
from rtl.isa import GC_NEW, GC_RELOC
from rtl.gc_mv_coproc import MV_QUERY


class Tb(Elaboratable):
    def __init__(self):
        self.sys = GC3ChipSystem(
            ncores=1,
            scan_kwargs=dict(fifo_depth=2, consume_every=1, batch_size=1, dedup_enable=True, cardset_size=4, out_depth=2),
            clean_kwargs=dict(entries=32, fifo_depth=2, engine_latency=0, card_dedup_enable=True, card_table_size=4, card_table_ways=1, card_index_mode=0),
            move_kwargs=dict(fifo_depth=2, map_depth=8, chase_depth=1),
        )

    def elaborate(self, platform):
        m = Module()
        m.submodules.sys = self.sys
        return m


def main() -> None:
    tb = Tb()
    sim = Simulator(tb)
    sim.add_clock(1e-6)

    clean = tb.sys.clean
    move = tb.sys.move

    def enq_clean(op: int, rd: int, rs1: int, rs2: int, tag: int = 1):
        # generator helper
        while (yield clean.cmd_enq_ready[0]) == 0:
            yield Tick()
        yield clean.cmd_tag[0].eq(tag)
        yield clean.cmd_op[0].eq(op)
        yield clean.cmd_rd[0].eq(rd)
        yield clean.cmd_rs1[0].eq(rs1)
        yield clean.cmd_rs2[0].eq(rs2)
        yield clean.cmd_enq_valid[0].eq(1)
        yield Tick()
        yield clean.cmd_enq_valid[0].eq(0)

    def wait_clean_rsp():
        for _ in range(80):
            if (yield clean.rsp_valid[0]):
                return
            yield Tick()
        assert False, "clean response timeout"

    def take_clean_rsp():
        yield clean.rsp_take[0].eq(1)
        yield Tick()
        yield clean.rsp_take[0].eq(0)

    def mv_query(val: int, tag: int = 1) -> int:
        while (yield move.cmd_enq_ready[0]) == 0:
            yield Tick()
        yield move.cmd_tag[0].eq(tag)
        yield move.cmd_op[0].eq(MV_QUERY)
        yield move.cmd_rd[0].eq(3)
        yield move.cmd_rs1[0].eq(val)
        yield move.cmd_rs2[0].eq(0)
        yield move.cmd_enq_valid[0].eq(1)
        yield Tick()
        yield move.cmd_enq_valid[0].eq(0)
        for _ in range(80):
            if (yield move.rsp_valid[0]):
                got = (yield move.rsp_data[0])
                yield move.rsp_take[0].eq(1)
                yield Tick()
                yield move.rsp_take[0].eq(0)
                return got
            yield Tick()
        assert False, "mv response timeout"

    def proc():
        # Keep epoch low initially
        yield tb.sys.epoch_advance.eq(0)

        # GC_NEW -> handle (expect 1)
        yield from enq_clean(GC_NEW, rd=1, rs1=0, rs2=0, tag=1)
        yield from wait_clean_rsp()
        h = (yield clean.rsp_data[0])
        yield from take_clean_rsp()
        assert h == 1, f"expected handle 1 at reset, got {h}"

                # GC_RELOC 1 -> 10 (commit should update MV)
        yield from enq_clean(GC_RELOC, rd=0, rs1=h, rs2=10, tag=2)
        yield from wait_clean_rsp()
        trap_reloc = (yield clean.trap[0])
        yield from take_clean_rsp()
        assert trap_reloc == 0, "GC_RELOC should commit without trap"

        # Allow the Clean->Move link (with FIFO/backpressure) to deliver the mapping.
        got1 = h
        for _ in range(200):
            got1 = (yield from mv_query(h, tag=3))
            if got1 == 10:
                break
            # Not visible yet; give link a few cycles.
            for _ in range(3):
                yield Tick()
        assert got1 == 10, f"MV should map {h}->10 before epoch advance (got {got1})"

        # Pulse epoch_advance, then mapping must invalidate.
        yield tb.sys.epoch_advance.eq(1)
        yield Tick()
        yield tb.sys.epoch_advance.eq(0)

        for _ in range(5):
            yield Tick()

        got2 = (yield from mv_query(h, tag=4))
        assert got2 == h, f"MV mapping must invalidate on epoch advance (got {got2}, expected {h})"

        print("OK: epoch broadcast invalidates MV forwarding table (3-chip contract).")

    sim.add_sync_process(proc)
    sim.run()


if __name__ == "__main__":
    main()