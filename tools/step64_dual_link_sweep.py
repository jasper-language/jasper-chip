# -*- coding: utf-8 -*-
"""Step64 helper: sweep BOTH inter-chip link depths (Scan->Clean cards, Clean->Move relocs).

Compared to Step63, we add a reloc workload (GC_NEW + GC_RELOC) and collect:
  - max dbg_card_link_level
  - max dbg_reloc_link_level
  - cycles until both (a) Clean accounts all cards, (b) all relocs are visible via MV_QUERY.

Example:
  python -m tools.step64_dual_link_sweep --cards 256 --relocs 64 --card-depths 1,2,4 --reloc-depths 1,2,4

Outputs a CSV in reports/step64_dual_link_sweep.csv by default.
"""

from __future__ import annotations

import argparse
import csv
import os
from dataclasses import dataclass
from typing import List, Dict, Tuple

from amaranth.sim import Simulator, Tick

from rtl.gc_3chip_system import GC3ChipSystem
from rtl.isa import GC_NEW, GC_RELOC
from rtl.gc_mv_coproc import MV_QUERY


@dataclass
class Result:
    card_link_depth: int
    reloc_link_depth: int
    cards: int
    relocs: int
    cycles: int
    max_card_link_level: int
    max_reloc_link_level: int
    mark_count_total: int
    mv_upd_overflow: int


def parse_int_list(s: str) -> List[int]:
    return [int(x.strip()) for x in s.split(",") if x.strip()]


def run_one(cards: int, relocs: int, card_depth: int, reloc_depth: int, ncores: int = 2) -> Result:
    dut = GC3ChipSystem(
        ncores=ncores,
        enable_scan=True,
        card_link_depth=card_depth,
        reloc_link_depth=reloc_depth,
        scan_kwargs=dict(fifo_depth=4, out_depth=4, dedup_enable=True, cardset_size=16),
        clean_kwargs=dict(fifo_depth=2, entries=128, card_table_size=16, card_table_ways=1, card_index_mode=0),
        move_kwargs=dict(fifo_depth=2, map_depth=64, chase_depth=1),
    )

    scan = dut.scan
    clean = dut.clean
    move = dut.move

    def wb_event(core: int, card_id: int):
        while (yield scan.wb_ready[core]) == 0:
            yield Tick()
        yield scan.wb_valid[core].eq(1)
        yield scan.wb_data[core].eq(card_id)
        yield Tick()
        yield scan.wb_valid[core].eq(0)

    def enq_clean(core: int, op: int, rd: int, rs1: int, rs2: int, tag: int) -> Tuple[int, int]:
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
        for _ in range(600):
            if (yield clean.rsp_valid[core]):
                data = (yield clean.rsp_data[core])
                trap = (yield clean.trap[core])
                yield clean.rsp_take[core].eq(1)
                yield Tick()
                yield clean.rsp_take[core].eq(0)
                return int(data), int(trap)
            yield Tick()
        raise RuntimeError("clean response timeout")

    def mv_query(core: int, val: int, tag: int = 1) -> int:
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
        for _ in range(600):
            if (yield move.rsp_valid[core]):
                got = (yield move.rsp_data[core])
                yield move.rsp_take[core].eq(1)
                yield Tick()
                yield move.rsp_take[core].eq(0)
                return int(got)
            yield Tick()
        raise RuntimeError("mv response timeout")

    max_card_lvl = 0
    max_reloc_lvl = 0
    cycles = 0
    handles: List[int] = []
    final_marks = 0
    final_overflow = 0

    def proc():
        nonlocal max_card_lvl, max_reloc_lvl, cycles, handles, final_marks, final_overflow

        yield dut.card_link_enable.eq(1)
        yield dut.reloc_link_enable.eq(1)
        yield dut.epoch_advance.eq(0)

        # Inject cards (round-robin across cores).
        for cid in range(cards):
            yield from wb_event(cid % ncores, cid)

        # Allocate and commit relocs (round-robin across cores).
        for i in range(relocs):
            h, trap = (yield from enq_clean(i % ncores, GC_NEW, rd=0, rs1=0, rs2=0, tag=100 + i))
            assert trap == 0
            handles.append(h)
            _, trap2 = (yield from enq_clean(i % ncores, GC_RELOC, rd=0, rs1=h, rs2=0x1000 + i, tag=200 + i))
            assert trap2 == 0

        # Run until clean counts all cards and both link FIFOs drain.
        max_cycles = (cards + relocs) * 20 + 1000
        while cycles < max_cycles:
            cl = (yield dut.dbg_card_link_level)
            rl = (yield dut.dbg_reloc_link_level)
            if cl > max_card_lvl:
                max_card_lvl = int(cl)
            if rl > max_reloc_lvl:
                max_reloc_lvl = int(rl)

            if (yield clean.u.mark_count_total) >= cards and cl == 0 and rl == 0:
                break
            yield Tick()
            cycles += 1

        final_marks = int((yield clean.u.mark_count_total))
        final_overflow = int((yield move.u.dbg_upd_overflow))

        # Verify reloc visibility with MV_QUERY (sample all).
        for i, h in enumerate(handles):
            got = (yield from mv_query(i % ncores, h, tag=300 + i))
            exp = 0x1000 + i
            assert got == exp, f"MV_QUERY mismatch: {h}->{got} expected {exp}"

    sim = Simulator(dut)
    sim.add_clock(1e-6)
    sim.add_sync_process(proc)
    sim.run()

    return Result(
        card_link_depth=card_depth,
        reloc_link_depth=reloc_depth,
        cards=cards,
        relocs=relocs,
        cycles=int(cycles),
        max_card_link_level=int(max_card_lvl),
        max_reloc_link_level=int(max_reloc_lvl),
        mark_count_total=int(final_marks),
        mv_upd_overflow=int(final_overflow),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cards", type=int, default=64)
    ap.add_argument("--relocs", type=int, default=16)
    ap.add_argument("--card-depths", type=str, default="1,2,4,8")
    ap.add_argument("--reloc-depths", type=str, default="1,2,4,8")
    ap.add_argument("--ncores", type=int, default=2)
    ap.add_argument("--out", type=str, default="reports/step64_dual_link_sweep.csv")
    args = ap.parse_args()

    card_depths = parse_int_list(args.card_depths)
    reloc_depths = parse_int_list(args.reloc_depths)

    rows: List[Dict[str, int]] = []
    os.makedirs(os.path.dirname(args.out), exist_ok=True)

    for cd in card_depths:
        for rd in reloc_depths:
            res = run_one(cards=args.cards, relocs=args.relocs, card_depth=cd, reloc_depth=rd, ncores=args.ncores)
            row = dict(
                card_link_depth=res.card_link_depth,
                reloc_link_depth=res.reloc_link_depth,
                cards=res.cards,
                relocs=res.relocs,
                cycles=res.cycles,
                max_card_link_level=res.max_card_link_level,
                max_reloc_link_level=res.max_reloc_link_level,
                mark_count_total=res.mark_count_total,
                mv_upd_overflow=res.mv_upd_overflow,
            )
            rows.append(row)
            print(
                f"card={cd:>3} reloc={rd:>3} cycles={res.cycles:>7} "
                f"max_card={res.max_card_link_level:>3} max_reloc={res.max_reloc_link_level:>3} "
                f"marks={res.mark_count_total} ovf={res.mv_upd_overflow}"
            )

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow(r)

    print(f"Wrote: {args.out}")


if __name__ == "__main__":
    main()
