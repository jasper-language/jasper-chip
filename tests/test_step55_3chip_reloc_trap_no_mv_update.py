# -*- coding: utf-8 -*-
"""Step55: 3-chip contract — RELOC trap must NOT update MV map.

We use GC3ChipSystem (Scan/Clean/Move). CPU is a black box; we directly drive
the Clean chip command interface and query the Move chip.

Scenario:
  - Issue GC_RELOC for an *unused* old handle => must trap.
  - Since RELOC did not commit, the Clean->Move sideband must not update the
    forwarding table; therefore MV_QUERY(old) should return old.

Run:
  python -m tests.test_step55_3chip_reloc_trap_no_mv_update
"""

from __future__ import annotations

from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.gc_3chip_system import GC3ChipSystem
from rtl.isa import GC_RELOC
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

    def proc():
        # Ensure epoch_advance low
        yield tb.sys.epoch_advance.eq(0)

        # --- 1) Issue GC_RELOC old=1 -> new=10 WITHOUT allocating old.
        # This must trap because old handle 1 is unused at reset.
        old = 1
        new = 10

        # Wait until clean cmd ready
        while (yield clean.cmd_enq_ready[0]) == 0:
            yield Tick()

        yield clean.cmd_tag[0].eq(7)
        yield clean.cmd_op[0].eq(GC_RELOC)
        yield clean.cmd_rd[0].eq(0)
        yield clean.cmd_rs1[0].eq(old)
        yield clean.cmd_rs2[0].eq(new)
        yield clean.cmd_enq_valid[0].eq(1)
        yield Tick()  # enqueue
        yield clean.cmd_enq_valid[0].eq(0)

        saw_trap = False
        # Give the engine time to execute and potentially assert trap.
        for _ in range(30):
            if (yield clean.trap[0]):
                saw_trap = True
            yield Tick()

        assert saw_trap, "GC_RELOC on unused old handle must trap"

        # --- 2) Query MV map for old. It must return old (no update on trap).
        while (yield move.cmd_enq_ready[0]) == 0:
            yield Tick()

        yield move.cmd_tag[0].eq(1)
        yield move.cmd_op[0].eq(MV_QUERY)
        yield move.cmd_rd[0].eq(3)
        yield move.cmd_rs1[0].eq(old)
        yield move.cmd_rs2[0].eq(0)
        yield move.cmd_enq_valid[0].eq(1)
        yield Tick()
        yield move.cmd_enq_valid[0].eq(0)

        # Wait for response
        for _ in range(80):
            if (yield move.rsp_valid[0]):
                break
            yield Tick()
        assert (yield move.rsp_valid[0]), "MV_QUERY must produce a response"
        got = (yield move.rsp_data[0])
        assert got == old, f"MV map must not be updated when RELOC traps (got {got}, expected {old})"

        # take response
        yield move.rsp_take[0].eq(1)
        yield Tick()
        yield move.rsp_take[0].eq(0)

        print("OK: RELOC trap does not update MV forwarding table (3-chip contract).")

    sim.add_sync_process(proc)
    sim.run()


if __name__ == "__main__":
    main()
