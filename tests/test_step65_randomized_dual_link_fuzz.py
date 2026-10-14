# -*- coding: utf-8 -*-
"""Step65: Randomized end-to-end fuzz regression for 3-chip GC system (deterministic, fast, no hangs).

Key idea: during randomized phase we allow reloc updates and scan cards to overlap with
backpressure and epoch flips, but we only *validate MV_QUERY results after draining*
to avoid modeling the Move chip's internal query scheduling.

Contracts validated:
  - Clean drops stale scan cards after epoch flip: dbg_card_stale_drop matches expected count.
  - Clean never drops reloc updates under backpressure: dbg_reloc_overflow==0.
  - Both inter-chip FIFOs drain to 0 after re-enabling delivery.
  - After drain, MV_QUERY results match a software model updated at the true commit point
    (move.reloc_in handshake), keyed by the update's own epoch.

Run:
  python -m tests.test_step65_randomized_dual_link_fuzz
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from amaranth.sim import Simulator, Tick

from rtl.gc_3chip_system import GC3ChipSystem
from rtl.isa import GC_NEW, GC_RELOC
from rtl.gc_mv_coproc import MV_QUERY


@dataclass
class FuzzCfg:
    seed: int = 0xC0FFEE
    cycles: int = 180
    ncores: int = 1
    entries: int = 256
    card_link_depth: int = 2
    reloc_link_depth: int = 2
    drain_cycles: int = 260
    query_count: int = 8


def chase2(mapping: dict[int, int], x: int) -> int:
    y = mapping.get(x, x)
    z = mapping.get(y, y)
    return z


def run_fuzz(cfg: FuzzCfg, *, return_stats: bool = False) -> dict[str, int] | None:
    rng = random.Random(cfg.seed)

    dut = GC3ChipSystem(
        ncores=cfg.ncores,
        enable_scan=True,
        card_link_depth=cfg.card_link_depth,
        reloc_link_depth=cfg.reloc_link_depth,
        clean_kwargs=dict(entries=cfg.entries),
    )
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    cur_epoch = 0
    mv_map = {0: {}, 1: {}}

    used_idx: set[int] = set()
    live_handles: list[int] = []
    clean_cmd_q: list[tuple[int, int, int]] = []  # (op, rs1, rs2)

    expected_stale_drop = 0
    next_tag = 1

    # Optional stats collection (filled by the sim process).
    stats: dict[str, int] = {
        "seed": int(cfg.seed),
        "cycles": int(cfg.cycles),
        "drain_cycles": int(cfg.drain_cycles),
        "card_link_depth": int(cfg.card_link_depth),
        "reloc_link_depth": int(cfg.reloc_link_depth),
        "epoch_flips": 0,
        "wb_events": 0,
        "clean_new_enq": 0,
        "clean_reloc_enq": 0,
        "reloc_commits": 0,
        "expected_stale_drop": 0,
        "actual_stale_drop": 0,
        "reloc_overflow": 0,
        "max_card_link_level": 0,
        "max_reloc_link_level": 0,
        "ok": 0,
    }

    def pick_free_idx() -> int | None:
        if len(used_idx) >= cfg.entries:
            return None
        for _ in range(16):
            cand = rng.randrange(cfg.entries)
            if cand not in used_idx:
                return cand
        for cand in range(cfg.entries):
            if cand not in used_idx:
                return cand
        return None

    def issue_mv_query(q: int, tag: int):
        # assumes cmd_enq_ready is high
        yield dut.move.cmd_enq_valid[0].eq(1)
        yield dut.move.cmd_op[0].eq(MV_QUERY)
        yield dut.move.cmd_rd[0].eq(1)
        yield dut.move.cmd_rs1[0].eq(int(q))
        yield dut.move.cmd_tag[0].eq(int(tag))
        yield Tick()
        yield dut.move.cmd_enq_valid[0].eq(0)

    def proc():
        nonlocal cur_epoch, expected_stale_drop, next_tag

        # Always take responses.
        yield dut.clean.rsp_take[0].eq(1)
        yield dut.move.rsp_take[0].eq(1)

        # Local link enable state.
        card_en = 1
        reloc_en = 1
        yield dut.card_link_enable.eq(card_en)
        yield dut.reloc_link_enable.eq(reloc_en)

        # settle
        for _ in range(5):
            yield Tick()

        for _ in range(cfg.cycles):
            # Track max link occupancy.
            cl = int((yield dut.dbg_card_link_level))
            rl = int((yield dut.dbg_reloc_link_level))
            if cl > stats["max_card_link_level"]:
                stats["max_card_link_level"] = cl
            if rl > stats["max_reloc_link_level"]:
                stats["max_reloc_link_level"] = rl

            # Observe commit points / deliveries
            if (yield dut.move.reloc_in_valid) and (yield dut.move.reloc_in_ready):
                old = int((yield dut.move.reloc_in_old))
                new = int((yield dut.move.reloc_in_new))
                upd_epoch = int((yield dut.move.reloc_in_epoch)) & 1
                mv_map[upd_epoch][old] = new
                stats["reloc_commits"] += 1

            if (yield dut.clean.card_in_valid) and (yield dut.clean.card_in_ready):
                cin_epoch = int((yield dut.clean.card_in_epoch)) & 1
                if cin_epoch != cur_epoch:
                    expected_stale_drop += 1

            if (yield dut.clean.rsp_valid[0]):
                assert clean_cmd_q, "clean rsp without queued cmd"
                op, rs1, rs2 = clean_cmd_q.pop(0)
                trap = int((yield dut.clean.trap[0]))
                assert trap == 0, f"unexpected clean trap on op={op}"
                rsp = int((yield dut.clean.rsp_data[0]))
                if op == GC_NEW:
                    h = rsp
                    used_idx.add(h & 0xFF)
                    if h not in live_handles:
                        live_handles.append(h)
                elif op == GC_RELOC:
                    used_idx.discard(rs1 & 0xFF)
                    used_idx.add(rs2 & 0xFF)
                    try:
                        live_handles.remove(rs1)
                    except ValueError:
                        pass
                    if rs2 not in live_handles:
                        live_handles.append(rs2)

            # Randomly toggle links
            if rng.random() < 0.10:
                card_en = 1 if rng.random() < 0.70 else 0
                yield dut.card_link_enable.eq(card_en)
            if rng.random() < 0.10:
                reloc_en = 1 if rng.random() < 0.70 else 0
                yield dut.reloc_link_enable.eq(reloc_en)

            # Epoch flip only when both stalled.
            if card_en == 0 and reloc_en == 0 and rng.random() < 0.03:
                yield dut.epoch_advance.eq(1)
                yield Tick()
                yield dut.epoch_advance.eq(0)
                cur_epoch ^= 1
                stats["epoch_flips"] += 1
                continue

            action = rng.random()

            # WB event
            if action < 0.30 and (yield dut.scan.wb_ready[0]) and rng.random() < 0.85:
                yield dut.scan.wb_valid[0].eq(1)
                yield dut.scan.wb_addr[0].eq(rng.getrandbits(16))
                yield dut.scan.wb_data[0].eq(rng.getrandbits(16))
                yield Tick()
                yield dut.scan.wb_valid[0].eq(0)
                stats["wb_events"] += 1
                continue

            # Clean cmd: only one in-flight to keep RELOC legal (avoid modeling deep speculative used-set).
            if action < 0.65 and (not clean_cmd_q) and (yield dut.clean.cmd_enq_ready[0]):
                op = GC_NEW if (rng.random() < 0.65 or not live_handles) else GC_RELOC
                tag = next_tag & 0xFFFF
                next_tag += 1

                if op == GC_NEW:
                    yield dut.clean.cmd_enq_valid[0].eq(1)
                    yield dut.clean.cmd_op[0].eq(GC_NEW)
                    yield dut.clean.cmd_rd[0].eq(0)
                    yield dut.clean.cmd_rs1[0].eq(0)
                    yield dut.clean.cmd_rs2[0].eq(0)
                    yield dut.clean.cmd_tag[0].eq(tag)
                    clean_cmd_q.append((GC_NEW, 0, 0))
                    yield Tick()
                    yield dut.clean.cmd_enq_valid[0].eq(0)
                    stats["clean_new_enq"] += 1
                    continue

                # RELOC
                src = int(rng.choice(live_handles))
                dst_idx = pick_free_idx()
                if dst_idx is not None:
                    dst = int(dst_idx)
                    yield dut.clean.cmd_enq_valid[0].eq(1)
                    yield dut.clean.cmd_op[0].eq(GC_RELOC)
                    yield dut.clean.cmd_rd[0].eq(0)
                    yield dut.clean.cmd_rs1[0].eq(src)
                    yield dut.clean.cmd_rs2[0].eq(dst)
                    yield dut.clean.cmd_tag[0].eq(tag)
                    clean_cmd_q.append((GC_RELOC, src, dst))
                    yield Tick()
                    yield dut.clean.cmd_enq_valid[0].eq(0)
                    stats["clean_reloc_enq"] += 1
                    continue

            yield Tick()

        # Drain
        yield dut.card_link_enable.eq(1)
        yield dut.reloc_link_enable.eq(1)
        for _ in range(cfg.drain_cycles):
            cl = int((yield dut.dbg_card_link_level))
            rl = int((yield dut.dbg_reloc_link_level))
            if cl > stats["max_card_link_level"]:
                stats["max_card_link_level"] = cl
            if rl > stats["max_reloc_link_level"]:
                stats["max_reloc_link_level"] = rl

            if (yield dut.move.reloc_in_valid) and (yield dut.move.reloc_in_ready):
                old = int((yield dut.move.reloc_in_old))
                new = int((yield dut.move.reloc_in_new))
                upd_epoch = int((yield dut.move.reloc_in_epoch)) & 1
                mv_map[upd_epoch][old] = new
                stats["reloc_commits"] += 1
            if (yield dut.clean.card_in_valid) and (yield dut.clean.card_in_ready):
                cin_epoch = int((yield dut.clean.card_in_epoch)) & 1
                if cin_epoch != cur_epoch:
                    expected_stale_drop += 1
            if (yield dut.clean.rsp_valid[0]):
                assert clean_cmd_q, "clean rsp without queued cmd (drain)"
                op, rs1, rs2 = clean_cmd_q.pop(0)
                trap = int((yield dut.clean.trap[0]))
                assert trap == 0
                rsp = int((yield dut.clean.rsp_data[0]))
                if op == GC_NEW:
                    h = rsp
                    used_idx.add(h & 0xFF)
                    if h not in live_handles:
                        live_handles.append(h)
                elif op == GC_RELOC:
                    used_idx.discard(rs1 & 0xFF)
                    used_idx.add(rs2 & 0xFF)
                    try:
                        live_handles.remove(rs1)
                    except ValueError:
                        pass
                    if rs2 not in live_handles:
                        live_handles.append(rs2)
            yield Tick()

        # Contract checks: stale drop counters and no overflow/drops.
        assert int((yield dut.clean.dbg_reloc_overflow)) == 0
        assert int((yield dut.clean.dbg_card_stale_drop)) == expected_stale_drop
        assert int((yield dut.dbg_card_link_level)) == 0
        assert int((yield dut.dbg_reloc_link_level)) == 0
        assert not clean_cmd_q

        stats["expected_stale_drop"] = int(expected_stale_drop)
        stats["actual_stale_drop"] = int((yield dut.clean.dbg_card_stale_drop))
        stats["reloc_overflow"] = int((yield dut.clean.dbg_reloc_overflow))

        # Validate MV_QUERY after drain (sequential, bounded wait).
        # Make sure the move cmd queue is empty-ish by issuing one at a time.
        def wait_mv_rsp(max_ticks=200):
            for _ in range(max_ticks):
                if (yield dut.move.rsp_valid[0]):
                    return int((yield dut.move.rsp_tag[0])), int((yield dut.move.rsp_data[0]))
                yield Tick()
            assert False, "mv rsp timeout"

        # query a handful of live handles (or random if none)
        queries = list(live_handles[:cfg.query_count]) if live_handles else [0, 1, 2, 3][:cfg.query_count]
        for q in queries:
            for _ in range(200):
                if (yield dut.move.cmd_enq_ready[0]):
                    break
                yield Tick()
            assert (yield dut.move.cmd_enq_ready[0]), "mv cmd enqueue timeout"
            tag = next_tag & 0xFFFF
            next_tag += 1
            yield from issue_mv_query(q, tag)
            rt, data = (yield from wait_mv_rsp())
            assert rt == tag, "mv tag mismatch"
            exp = chase2(mv_map[cur_epoch], int(q))
            assert data == exp, f"mv query mismatch q={q}: got {data} exp {exp}"

        # Optional: flip epoch once and verify query against the other epoch-bucket.
        yield dut.epoch_advance.eq(1)
        yield Tick()
        yield dut.epoch_advance.eq(0)
        cur_epoch ^= 1

        q = queries[0]
        for _ in range(200):
            if (yield dut.move.cmd_enq_ready[0]):
                break
            yield Tick()
        tag = next_tag & 0xFFFF
        next_tag += 1
        yield from issue_mv_query(q, tag)
        rt, data = (yield from wait_mv_rsp())
        assert rt == tag
        exp = chase2(mv_map[cur_epoch], int(q))
        assert data == exp

        stats["ok"] = 1

    sim.add_sync_process(proc)
    sim.run()

    return stats if return_stats else None


def test_step65_randomized_dual_link_fuzz():
    run_fuzz(FuzzCfg())


if __name__ == "__main__":
    test_step65_randomized_dual_link_fuzz()
    print("OK: randomized dual-link fuzz passed (drain-validated).")