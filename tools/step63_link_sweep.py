# -*- coding: utf-8 -*-
"""Step63 helper: sweep inter-chip link depths and report simple throughput/occupancy metrics.

This script is intentionally small and deterministic: it simulates a fixed number of write-barrier events
(cards) entering Scan and measures how many cycles are needed until Clean accounts them, while collecting:
  - max dbg_card_link_level observed
  - final mark_count_total

Example:
  python -m tools.step63_link_sweep --cards 256 --card-depths 1,2,4,8

Outputs a CSV in reports/step63_link_sweep.csv by default.
"""

from __future__ import annotations

import argparse
import csv
import os

from amaranth.sim import Simulator, Tick

from rtl.gc_3chip_system import GC3ChipSystem


def run_one(cards: int, card_link_depth: int) -> dict:
    dut = GC3ChipSystem(
        ncores=1,
        card_link_depth=card_link_depth,
        reloc_link_depth=2,
        scan_kwargs=dict(fifo_depth=min(64, max(8, cards)), out_depth=64, dedup_enable=False),
        clean_kwargs=dict(fifo_depth=16, engine_latency=0, card_dedup_enable=False),
        move_kwargs=dict(),
        enable_scan=True,
    )
    scan = dut.scan
    clean = dut.clean

    result = {"card_link_depth": card_link_depth, "cards": cards, "cycles": None, "max_link_level": 0, "mark_count_total": None}

    def wb_event(card_id, obj_id=0, core=0):
        for _ in range(10000):
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
        yield dut.epoch_advance.eq(0)
        yield dut.card_link_enable.eq(1)
        # inject
        for cid in range(cards):
            yield from wb_event(cid)

        # run until clean counts all
        cycles = 0
        max_lvl = 0
        max_cycles = cards * 50 + 2000
        while cycles < max_cycles:
            lvl = (yield dut.dbg_card_link_level)
            if lvl > max_lvl:
                max_lvl = lvl
            if (yield clean.u.mark_count_total) == cards:
                break
            yield Tick()
            cycles += 1

        result["cycles"] = cycles
        result["max_link_level"] = int(max_lvl)
        result["mark_count_total"] = int((yield clean.u.mark_count_total))

    sim = Simulator(dut)
    sim.add_clock(1e-6)
    sim.add_sync_process(proc)
    sim.run()

    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cards", type=int, default=256)
    ap.add_argument("--card-depths", type=str, default="1,2,4,8")
    ap.add_argument("--out", type=str, default="reports/step63_link_sweep.csv")
    args = ap.parse_args()

    depths = [int(x.strip()) for x in args.card_depths.split(",") if x.strip()]
    rows = [run_one(args.cards, d) for d in depths]

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow(r)

    # Print a short summary.
    for r in rows:
        print(f"depth={r['card_link_depth']:>3} cycles={r['cycles']:>7} max_link={r['max_link_level']:>3} marks={r['mark_count_total']}")

    print(f"Wrote: {args.out}")


if __name__ == "__main__":
    main()
