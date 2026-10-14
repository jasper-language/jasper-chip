# -*- coding: utf-8 -*-
"""Step60: Stale Scan->Clean card records must be dropped across epoch.

Why:
- Step60 introduces an explicit Scan->Clean transport FIFO (to model inter-chip delay/backpressure).
- A card record produced in epoch=0 may be delivered after the system has already flipped to epoch=1.
- Clean must NOT let that stale record affect mark/dedup state of the new epoch.

Contract:
1) With card_link_enable=0, scan can enqueue a card record into the transport FIFO.
2) Pulse epoch_advance (scan + clean flip their epoch bits).
3) Re-enable card link; stale card is delivered.
4) Clean must accept & DROP it (dbg_card_stale_drop++), and mark_count_total must remain 0.

Run:
  python -m tests.test_step60_card_epoch_stale_drop
"""

from __future__ import annotations

from amaranth.sim import Simulator, Tick

from rtl.gc_3chip_system import GC3ChipSystem


def main():
    dut = GC3ChipSystem(ncores=1, enable_scan=True, card_link_depth=1)

    sim = Simulator(dut)
    sim.add_clock(1e-6)

    def proc():
        # Stall delivery to clean so the first card stays in-flight.
        yield dut.card_link_enable.eq(0)

        # Inject one write-barrier event (scan interprets wb_addr as card_id in this test harness).
        for _ in range(20):
            if (yield dut.scan.wb_ready[0]):
                break
            yield Tick()
        assert (yield dut.scan.wb_ready[0]) == 1, "scan wb_ready stuck low"

        yield dut.scan.wb_valid[0].eq(1)
        yield dut.scan.wb_addr[0].eq(5)
        yield dut.scan.wb_data[0].eq(0x123)
        yield Tick()
        yield dut.scan.wb_valid[0].eq(0)

        # Let scan consume and emit into the (stalled) card link FIFO.
        for _ in range(50):
            yield Tick()

        # Sanity: nothing reached clean yet.
        assert int((yield dut.clean.mark_count_total)) == 0

        # Flip epoch while the card is still in-flight.
        yield dut.epoch_advance.eq(1)
        yield Tick()
        yield dut.epoch_advance.eq(0)

        # Now allow delivery; clean should drop it as stale.
        yield dut.card_link_enable.eq(1)
        for _ in range(50):
            yield Tick()

        mark = int((yield dut.clean.mark_count_total))
        stale = int((yield dut.clean.dbg_card_stale_drop))
        assert mark == 0, f"mark_count_total changed unexpectedly: {mark}"
        assert stale == 1, f"expected 1 stale drop, got {stale}"

        # Also ensure the system is still live (no deadlock).
        for _ in range(10):
            yield Tick()

    sim.add_sync_process(proc)
    sim.run()
    print("OK: stale scan->clean card delivered after epoch is dropped (no new marks).")


if __name__ == "__main__":
    main()
