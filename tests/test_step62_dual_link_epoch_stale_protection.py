# -*- coding: utf-8 -*-
"""Step62: End-to-end 3-chip contract — dual-link backpressure + epoch flip must not leak stale state.

We simultaneously stall:
  - Scan->Clean card transport (card_link_enable=0)
  - Clean->Move reloc transport (reloc_link_enable=0)

Then we generate:
  - one scan card record (epoch 0) that will be delivered *after* epoch flip
  - one clean RELOC commit (epoch 0) whose update will be delivered *after* epoch flip

After pulsing epoch_advance, we re-enable both links and drain.
Expected:
  - Clean drops the stale card record (dbg_card_stale_drop increments; mark_count_total stays 0)
  - Move does not resurrect stale mapping in the new epoch (MV_QUERY(old) returns old)

This test exercises Step58/60/61 together under realistic cross-chip backpressure.

Run:
  python -m tests.test_step62_dual_link_epoch_stale_protection
"""

from __future__ import annotations

from amaranth.sim import Simulator, Tick

from rtl.gc_3chip_system import GC3ChipSystem
from rtl.isa import GC_NEW, GC_RELOC
from rtl.gc_mv_coproc import MV_QUERY


def main():
    tb = GC3ChipSystem(
        ncores=1,
        scan_kwargs=dict(
            fifo_depth=2,
            consume_every=1,
            batch_size=1,
            dedup_enable=True,
            cardset_size=4,
            out_depth=2,
        ),
        clean_kwargs=dict(
            entries=32,
            fifo_depth=2,
            engine_latency=0,
            card_dedup_enable=True,
            card_table_size=4,
            card_table_ways=1,
            card_index_mode=0,
        ),
        move_kwargs=dict(
            fifo_depth=2,
            map_depth=8,
            chase_depth=1,
        ),
        reloc_link_depth=1,
        card_link_depth=1,
        enable_scan=True,
    )

    sim = Simulator(tb)
    sim.add_clock(1e-6)

    scan = tb.scan
    clean = tb.clean
    move = tb.move

    def enq_clean(op, rd, rs1, rs2, tag=0, core=0):
        for _ in range(200):
            if (yield clean.cmd_enq_ready[core]):
                break
            yield Tick()
        assert (yield clean.cmd_enq_ready[core]), "clean cmd enqueue timeout"

        yield clean.cmd_enq_valid[core].eq(1)
        yield clean.cmd_op[core].eq(op)
        yield clean.cmd_rd[core].eq(rd)
        yield clean.cmd_rs1[core].eq(rs1)
        yield clean.cmd_rs2[core].eq(rs2)
        yield clean.cmd_tag[core].eq(tag)
        yield Tick()
        yield clean.cmd_enq_valid[core].eq(0)

        for _ in range(400):
            if (yield clean.rsp_valid[core]):
                data = (yield clean.rsp_data[core])
                trap = (yield clean.trap[core])
                yield clean.rsp_take[core].eq(1)
                yield Tick()
                yield clean.rsp_take[core].eq(0)
                return data, trap
            yield Tick()
        assert False, "clean rsp timeout"

    def wb_event(card_id, obj_id=0, core=0):
        for _ in range(200):
            if (yield scan.wb_ready[core]):
                break
            yield Tick()
        assert (yield scan.wb_ready[core]), "scan wb enqueue timeout"

        yield scan.wb_valid[core].eq(1)
        yield scan.wb_addr[core].eq(card_id)
        yield scan.wb_data[core].eq(obj_id)
        yield Tick()
        yield scan.wb_valid[core].eq(0)

    def mv_query(old, tag=1, rd=1, core=0):
        for _ in range(200):
            if (yield move.cmd_enq_ready[core]):
                break
            yield Tick()
        assert (yield move.cmd_enq_ready[core]), "move cmd enqueue timeout"

        yield move.cmd_tag[core].eq(tag)
        yield move.cmd_op[core].eq(MV_QUERY)
        yield move.cmd_rd[core].eq(rd)
        yield move.cmd_rs1[core].eq(old)
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
                return got
            yield Tick()
        assert False, "mv rsp timeout"

    def proc():
        for _ in range(5):
            yield Tick()

        # Stall both transports
        yield tb.card_link_enable.eq(0)
        yield tb.reloc_link_enable.eq(0)

        # Produce one scan card record (will be stuck in card_link FIFO)
        yield from wb_event(card_id=0x5)

        # Wait until it is buffered in Scan->Clean transport
        for _ in range(200):
            if (yield tb.dbg_card_link_level) >= 1:
                break
            yield Tick()
        assert (yield tb.dbg_card_link_level) >= 1, "expected card_link FIFO to hold >=1 entry under stall"

        # Clean: allocate handle=1
        h, trap_new = (yield from enq_clean(GC_NEW, rd=1, rs1=0, rs2=0, tag=10))
        assert trap_new == 0
        assert h == 1, f"expected handle 1, got {h}"

        # Clean: commit RELOC (old=1 -> new=100). Update will be stuck in reloc_link FIFO.
        _, trap_reloc = (yield from enq_clean(GC_RELOC, rd=0, rs1=h, rs2=100, tag=11))
        assert trap_reloc == 0, "GC_RELOC should commit without trap"

        # Wait until reloc update is buffered in Clean->Move transport
        for _ in range(400):
            if (yield tb.dbg_reloc_link_level) >= 1:
                break
            yield Tick()
        assert (yield tb.dbg_reloc_link_level) >= 1, "expected reloc_link FIFO to hold >=1 entry under stall"

        # Flip epoch while both updates are in flight
        yield tb.epoch_advance.eq(1)
        yield Tick()
        yield tb.epoch_advance.eq(0)

        # Re-enable links and drain
        yield tb.card_link_enable.eq(1)
        yield tb.reloc_link_enable.eq(1)

        for _ in range(400):
            if (yield tb.dbg_card_link_level) == 0 and (yield tb.dbg_reloc_link_level) == 0:
                break
            yield Tick()

        assert (yield tb.dbg_card_link_level) == 0, "card_link did not drain"
        assert (yield tb.dbg_reloc_link_level) == 0, "reloc_link did not drain"

        # Stale card must be dropped by clean (and must not mark)
        assert (yield clean.dbg_card_stale_drop) >= 1, "expected clean to drop stale card after epoch flip"
        assert (yield clean.mark_count_total) == 0, "stale card must not contribute to marks in new epoch"

        # Stale reloc update delivered after epoch flip must not resurrect mapping in new epoch
        got = (yield from mv_query(old=h, tag=12, rd=2))
        assert got == h, f"expected MV_QUERY miss in new epoch, got {got} (should equal old={h})"

        print("OK: dual-link backpressure + epoch flip does not leak stale card or stale reloc mapping.")

    sim.add_sync_process(proc)
    sim.run()


if __name__ == "__main__":
    main()
