# -*- coding: utf-8 -*-
"""Step61: Scan must tag epoch per dirty-card event, even if the card is delayed inside Scan.

Why:
- Step60 added an explicit Scan->Clean transport FIFO, and Clean drops stale cards across epoch.
- BUT a dirty-card event might be stuck *inside the Scan chip* (per-core FIFO / out_q) when epoch_advance flips.
- If Scan tags epoch at "consume time" (instead of "event enqueue time"), that delayed card would be mislabeled
  as the new epoch and would incorrectly affect the new epoch's mark state.

Contract (minimal repro):
1) Stall delivery to Clean (card_link_enable=0), so the Scan->Clean transport FIFO fills and backpressures Scan.
2) Enqueue 3 dirty-card events in epoch=0:
   - First card makes it into card_link FIFO (fills link).
   - Second card makes it into Scan out_q (fills out_q because link is full).
   - Third card is stuck in Scan per-core FIFO (cannot be consumed because out_q is full).
3) Flip epoch (epoch_advance pulse).
4) Re-enable delivery (card_link_enable=1) and let the pipeline drain.
Expected:
- All 3 cards were created in epoch=0, so after epoch flip they are all stale.
- Clean must drop them all: dbg_card_stale_drop == 3, and mark_count_total stays 0.

Run:
  python -m tests.test_step61_scan_epoch_tag_for_delayed_card
"""

from amaranth.sim import Simulator, Tick

from rtl.gc_3chip_system import GC3ChipSystem


def main():
    dut = GC3ChipSystem(
        ncores=1,
        card_link_depth=1,
        scan_kwargs=dict(
            dedup_enable=True,
            cardset_size=4,
            fifo_depth=4,
            out_depth=1,
            consume_every=1,
        ),
        clean_kwargs=dict(
            # keep defaults; wrapper will count stale drops
        ),
        move_kwargs=dict(),
        reloc_link_depth=1,
    )

    def send_card(card_id: int):
        # Drive a single WB event, honoring ready/valid.
        while True:
            rdy = (yield dut.scan.wb_ready[0])
            if rdy:
                break
            yield Tick()
        yield dut.scan.wb_valid[0].eq(1)
        yield dut.scan.wb_addr[0].eq(card_id)
        yield dut.scan.wb_data[0].eq(0)
        yield Tick()
        yield dut.scan.wb_valid[0].eq(0)

    def proc():
        # Stop delivery to clean, so transport FIFO will fill and create backpressure.
        yield dut.card_link_enable.eq(0)
        yield Tick()

        # Enqueue 3 cards in epoch=0.
        yield from send_card(100)  # should reach card_link FIFO
        for _ in range(10):
            yield Tick()

        yield from send_card(101)  # should reach scan out_q (link full)
        for _ in range(10):
            yield Tick()

        yield from send_card(102)  # should remain in per-core FIFO (out_q full)
        for _ in range(5):
            yield Tick()

        # Flip epoch.
        yield dut.epoch_advance.eq(1)
        yield Tick()
        yield dut.epoch_advance.eq(0)

        # Re-enable delivery and drain.
        yield dut.card_link_enable.eq(1)

        # Wait for all 3 stale drops to be observed.
        for _ in range(400):
            stale = (yield dut.clean.dbg_card_stale_drop)
            mark = (yield dut.clean.mark_count_total)
            if stale >= 3:
                assert mark == 0, f"mark_count_total changed unexpectedly: {mark}"
                assert stale == 3, f"expected 3 stale drops, got {stale}"
                break
            yield Tick()
        else:
            stale = (yield dut.clean.dbg_card_stale_drop)
            mark = (yield dut.clean.mark_count_total)
            raise AssertionError(f"timeout waiting for stale drops. stale={stale}, mark={mark}")

        # Also ensure scan did not dedup-drop any of these unique cards.
        dup = (yield dut.scan.u.dup_drop[0])
        assert dup == 0, f"unexpected dup_drop under backpressure: {dup}"

        for _ in range(10):
            yield Tick()

    sim = Simulator(dut)
    sim.add_clock(1e-6)
    sim.add_sync_process(proc)
    sim.run()

    print("OK: delayed cards keep original epoch tag; clean drops them after epoch flip.")


if __name__ == "__main__":
    main()
