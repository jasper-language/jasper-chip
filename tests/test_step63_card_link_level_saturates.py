# -*- coding: utf-8 -*-
"""Step63: Validate Scan->Clean transport FIFO observability and saturation behavior under backpressure.

We stall delivery to Clean (card_link_enable=0) and inject more WB events than card_link_depth.
Expected:
  - dbg_card_link_level saturates at card_link_depth
  - after re-enabling delivery, dbg_card_link_level drains back to 0
  - mark_count_total equals number of unique cards injected (no silent drops)
"""

from amaranth.sim import Simulator, Tick

from rtl.gc_3chip_system import GC3ChipSystem


def test_step63_card_link_level_saturates_and_drains():
    # Small depths to force saturation quickly.
    dut = GC3ChipSystem(
        ncores=1,
        card_link_depth=2,
        reloc_link_depth=2,
        scan_kwargs=dict(fifo_depth=8, out_depth=8, dedup_enable=False),
        clean_kwargs=dict(fifo_depth=4, engine_latency=0, card_dedup_enable=False),
        move_kwargs=dict(),
        enable_scan=True,
    )

    scan = dut.scan
    clean = dut.clean

    def wb_event(card_id, obj_id=0, core=0):
        # Handshake into scan write-barrier input.
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

    def proc():
        # Hold epoch steady.
        yield dut.epoch_advance.eq(0)

        # Stall delivery on the inter-chip link.
        yield dut.card_link_enable.eq(0)

        # Inject more cards than link depth.
        for cid in [10, 11, 12]:
            yield from wb_event(cid)

        # Allow scan engine to run and push into transport until it saturates.
        for _ in range(80):
            lvl = (yield dut.dbg_card_link_level)
            if lvl == 2:
                break
            yield Tick()

        assert (yield dut.dbg_card_link_level) == 2, "card_link did not saturate to depth"

        # Now re-enable delivery and ensure it drains fully.
        yield dut.card_link_enable.eq(1)

        for _ in range(200):
            if (yield dut.dbg_card_link_level) == 0:
                break
            yield Tick()
        assert (yield dut.dbg_card_link_level) == 0, "card_link did not drain after re-enable"

        # Allow clean to account the delivered cards.
        for _ in range(200):
            if (yield clean.u.mark_count_total) >= 3:
                break
            yield Tick()

        assert (yield clean.u.mark_count_total) == 3, "clean did not consume all cards"

    sim = Simulator(dut)
    sim.add_clock(1e-6)
    sim.add_sync_process(proc)
    sim.run()
