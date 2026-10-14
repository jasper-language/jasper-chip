# rtl/gc_chip_clean.py
# Step53: Clean chip top-level wrapper (sweep + allocator + reloc commit).

from __future__ import annotations

from amaranth import Array, Const, Module, Mux, Signal
from amaranth.hdl import Elaboratable

from .gc_sweep_coproc import GCSweepCoProc


class GCCleanChipTop(Elaboratable):
    """Clean chip wrapper (re-exporting GCSweepCoProc ports)."""

    def __init__(self, **kwargs):
        self.u = GCSweepCoProc(**kwargs)

        # NOTE (Step54): do NOT alias internal Signals as top-level ports.
        # Create explicit chip boundary ports and wire them in `elaborate()`.

        # CPU command/response interface (per-core arrays)
        self.cmd_tag = Array(Signal.like(self.u.cmd_tag[i], name=f"clean_cmd{i}_tag") for i in range(self.u.ncores))
        self.cmd_enq_valid = Array(Signal.like(self.u.cmd_enq_valid[i], name=f"clean_cmd{i}_valid") for i in range(self.u.ncores))
        self.cmd_enq_ready = Array(Signal.like(self.u.cmd_enq_ready[i], name=f"clean_cmd{i}_ready") for i in range(self.u.ncores))
        self.cmd_op = Array(Signal.like(self.u.cmd_op[i], name=f"clean_cmd{i}_op") for i in range(self.u.ncores))
        self.cmd_rd = Array(Signal.like(self.u.cmd_rd[i], name=f"clean_cmd{i}_rd") for i in range(self.u.ncores))
        self.cmd_rs1 = Array(Signal.like(self.u.cmd_rs1[i], name=f"clean_cmd{i}_rs1") for i in range(self.u.ncores))
        self.cmd_rs2 = Array(Signal.like(self.u.cmd_rs2[i], name=f"clean_cmd{i}_rs2") for i in range(self.u.ncores))

        self.rsp_valid = Array(Signal.like(self.u.rsp_valid[i], name=f"clean_rsp{i}_valid") for i in range(self.u.ncores))
        self.rsp_tag = Array(Signal.like(self.u.rsp_tag[i], name=f"clean_rsp{i}_tag") for i in range(self.u.ncores))
        self.rsp_rd = Array(Signal.like(self.u.rsp_rd[i], name=f"clean_rsp{i}_rd") for i in range(self.u.ncores))
        self.rsp_data = Array(Signal.like(self.u.rsp_data[i], name=f"clean_rsp{i}_data") for i in range(self.u.ncores))
        self.rsp_take = Array(Signal.like(self.u.rsp_take[i], name=f"clean_rsp{i}_take") for i in range(self.u.ncores))
        self.trap = Array(Signal.like(self.u.trap[i], name=f"clean_trap{i}") for i in range(self.u.ncores))

        # Epoch tick outputs (optional; can be OR'ed at SoC)
        self.epoch_tick = Array(Signal.like(self.u.epoch_tick[i], name=f"clean_epoch{i}_tick") for i in range(self.u.ncores))

        # Scan->clean card stream input
        self.card_in_valid = Signal.like(self.u.card_in_valid, name="clean_card_in_valid")
        self.card_in_ready = Signal.like(self.u.card_in_ready, name="clean_card_in_ready")
        self.card_in_card_id = Signal.like(self.u.card_in_card_id, name="clean_card_in_card_id")
        self.card_in_core_id = Signal.like(self.u.card_in_core_id, name="clean_card_in_core_id")
        self.card_in_epoch = Signal.like(self.u.card_in_epoch, name="clean_card_in_epoch")

        # Reloc commit sideband to Move chip (per-core arrays)
        self.mv_upd_valid = Array(Signal.like(self.u.mv_upd_valid[i], name=f"clean_mvupd{i}_valid") for i in range(self.u.ncores))
        self.mv_upd_old = Array(Signal.like(self.u.mv_upd_old[i], name=f"clean_mvupd{i}_old") for i in range(self.u.ncores))
        self.mv_upd_new = Array(Signal.like(self.u.mv_upd_new[i], name=f"clean_mvupd{i}_new") for i in range(self.u.ncores))

        # Step56: Optional reloc update stream output (ready/valid).
        # This is the preferred inter-chip link form for Clean -> Move.
        core_id_w = max(1, (self.u.ncores - 1).bit_length())
        self.reloc_out_valid = Signal(name="clean_reloc_out_valid")
        self.reloc_out_ready = Signal(name="clean_reloc_out_ready")
        self.reloc_out_old   = Signal(32, name="clean_reloc_out_old")
        self.reloc_out_new   = Signal(32, name="clean_reloc_out_new")
        self.reloc_out_core  = Signal(core_id_w, name="clean_reloc_out_core")
        self.reloc_out_epoch = Signal(1, name="clean_reloc_out_epoch")

        # Epoch broadcast (SoC-wide). Used to stamp reloc stream entries with their originating epoch.
        self.epoch_advance = Signal(name="clean_epoch_advance")

        # Debug: number of reloc pulses dropped because per-core pending slot was full.
        self.dbg_reloc_overflow = Signal(32, name="clean_dbg_reloc_overflow")

        # Step60: number of stale scan->clean card records dropped due to epoch mismatch.
        self.dbg_card_stale_drop = Signal(32, name="clean_dbg_card_stale_drop")

        # Optional stats
        self.mark_count_total = Signal.like(self.u.mark_count_total, name="clean_mark_count_total")
        self.mark_dup_drop_total = Signal.like(self.u.mark_dup_drop_total, name="clean_mark_dup_drop_total")
        self.mark_hit_total = Signal.like(self.u.mark_hit_total, name="clean_mark_hit_total")
        self.mark_miss_total = Signal.like(self.u.mark_miss_total, name="clean_mark_miss_total")
        self.mark_replace_total = Signal.like(self.u.mark_replace_total, name="clean_mark_replace_total")

    def elaborate(self, platform):
        m = Module()
        m.submodules.clean = self.u

        # Step58: epoch bit for stamping reloc updates (toggles on epoch_advance).
        epoch = Signal(1, reset=0, name="clean_epoch")
        with m.If(self.epoch_advance):
            m.d.sync += epoch.eq(~epoch)

        # CPU cmd/rsp wiring (per-core)
        for i in range(self.u.ncores):
            m.d.comb += [
                # cmd -> clean
                self.u.cmd_tag[i].eq(self.cmd_tag[i]),
                self.u.cmd_enq_valid[i].eq(self.cmd_enq_valid[i]),
                self.cmd_enq_ready[i].eq(self.u.cmd_enq_ready[i]),
                self.u.cmd_op[i].eq(self.cmd_op[i]),
                self.u.cmd_rd[i].eq(self.cmd_rd[i]),
                self.u.cmd_rs1[i].eq(self.cmd_rs1[i]),
                self.u.cmd_rs2[i].eq(self.cmd_rs2[i]),
                # rsp -> cpu
                self.rsp_valid[i].eq(self.u.rsp_valid[i]),
                self.rsp_tag[i].eq(self.u.rsp_tag[i]),
                self.rsp_rd[i].eq(self.u.rsp_rd[i]),
                self.rsp_data[i].eq(self.u.rsp_data[i]),
                self.u.rsp_take[i].eq(self.rsp_take[i]),
                self.trap[i].eq(self.u.trap[i]),
                # epoch tick
                self.epoch_tick[i].eq(self.u.epoch_tick[i]),
            ]

        # Card stream (scan -> clean)
        # Step60: drop stale card records delivered after an epoch flip.
        # Rationale: scan->clean transport may delay old-epoch cards; they must not affect the new epoch.
        stale_card = Signal(name="clean_card_stale")
        m.d.comb += stale_card.eq(self.card_in_valid & (self.card_in_epoch != epoch))

        # Always drive data fields; only gate valid. For stale records we "accept & drop"
        # (ready=1) so the upstream can drain without being blocked by sweep's queue.
        m.d.comb += [
            self.u.card_in_valid.eq(self.card_in_valid & ~stale_card),
            self.card_in_ready.eq(Mux(stale_card, 1, self.u.card_in_ready)),
            self.u.card_in_card_id.eq(self.card_in_card_id),
            self.u.card_in_core_id.eq(self.card_in_core_id),
            self.u.card_in_epoch.eq(self.card_in_epoch),
        ]

        # Count dropped stale records when they handshake.
        with m.If(stale_card & self.card_in_valid & self.card_in_ready):
            m.d.sync += self.dbg_card_stale_drop.eq(self.dbg_card_stale_drop + 1)


        # Reloc commit sideband (clean -> move) per-core
        for i in range(self.u.ncores):
            m.d.comb += [
                self.mv_upd_valid[i].eq(self.u.mv_upd_valid[i]),
                self.mv_upd_old[i].eq(self.u.mv_upd_old[i]),
                self.mv_upd_new[i].eq(self.u.mv_upd_new[i]),
            ]


        # Step56: reloc update stream (Clean -> Move) with backpressure.
        # We capture per-core mv_upd pulses into 1-slot pending regs, and stream them out with RR fairness.
        pending_v = Array(Signal(name=f"clean_reloc_pend{i}") for i in range(self.u.ncores))
        pending_old = Array(Signal(32, name=f"clean_reloc_pend{i}_old") for i in range(self.u.ncores))
        pending_new = Array(Signal(32, name=f"clean_reloc_pend{i}_new") for i in range(self.u.ncores))
        pending_core = Array(Signal(max(1, (self.u.ncores - 1).bit_length()), name=f"clean_reloc_pend{i}_core") for i in range(self.u.ncores))
        pending_epoch = Array(Signal(1, name=f"clean_reloc_pend{i}_epoch") for i in range(self.u.ncores))

        rr = Signal(range(self.u.ncores), name="clean_reloc_rr")

        # Registered stream output (holds stable under backpressure)
        core_id_w = max(1, (self.u.ncores - 1).bit_length())
        out_valid_r = Signal(name="clean_reloc_out_valid_r")
        out_old_r   = Signal(32, name="clean_reloc_out_old_r")
        out_new_r   = Signal(32, name="clean_reloc_out_new_r")
        out_core_r  = Signal(core_id_w, name="clean_reloc_out_core_r")
        out_epoch_r = Signal(1, name="clean_reloc_out_epoch_r")

        m.d.comb += [
            self.reloc_out_valid.eq(out_valid_r),
            self.reloc_out_old.eq(out_old_r),
            self.reloc_out_new.eq(out_new_r),
            self.reloc_out_core.eq(out_core_r),
            self.reloc_out_epoch.eq(out_epoch_r),
        ]

        fire = Signal(name="clean_reloc_fire")
        m.d.comb += fire.eq(out_valid_r & self.reloc_out_ready)

        choose_found = Signal(name="clean_reloc_choose_found")
        choose_sel   = Signal(range(self.u.ncores), name="clean_reloc_choose_sel")

        # Choose next pending slot (RR fairness)
        m.d.comb += [
            choose_found.eq(0),
            choose_sel.eq(rr),
        ]
        with m.Switch(rr):
            for rr_val in range(self.u.ncores):
                with m.Case(rr_val):
                    order = list(range(rr_val, self.u.ncores)) + list(range(0, rr_val))
                    first = True
                    for idx in order:
                        if first:
                            with m.If(pending_v[idx]):
                                m.d.comb += [
                                    choose_found.eq(1),
                                    choose_sel.eq(idx),
                                ]
                            first = False
                        else:
                            with m.Elif(pending_v[idx]):
                                m.d.comb += [
                                    choose_found.eq(1),
                                    choose_sel.eq(idx),
                                ]

        # When output is idle, or when previous item was accepted, load next if available.
        with m.If((~out_valid_r) | fire):
            with m.If(choose_found):
                m.d.sync += [
                    out_valid_r.eq(1),
                    out_old_r.eq(pending_old[choose_sel]),
                    out_new_r.eq(pending_new[choose_sel]),
                    out_core_r.eq(pending_core[choose_sel]),
                    out_epoch_r.eq(pending_epoch[choose_sel]),
                    pending_v[choose_sel].eq(0),
                    rr.eq(Mux(choose_sel == (self.u.ncores - 1), 0, choose_sel + 1)),
                ]
            with m.Else():
                m.d.sync += out_valid_r.eq(0)

        # Capture mv_upd pulses from the internal sweep engine into pending slots.
        # Depth=1 per core; supports pop+push in the same cycle (slot treated as free if being drained).
        drain_sel = Signal(name="clean_reloc_drain_sel")
        drain_idx = Signal(range(self.u.ncores), name="clean_reloc_drain_idx")
        m.d.comb += [
            drain_sel.eq(((~out_valid_r) | fire) & choose_found),
            drain_idx.eq(choose_sel),
        ]

        slot_free = Array(Signal(name=f"clean_reloc_slotfree{i}") for i in range(self.u.ncores))
        for i in range(self.u.ncores):
            m.d.comb += slot_free[i].eq((~pending_v[i]) | (drain_sel & (drain_idx == i)))
            m.d.comb += self.u.mv_upd_ready[i].eq(slot_free[i])
            with m.If(self.u.mv_upd_valid[i] & self.u.mv_upd_ready[i]):
                m.d.sync += [
                    pending_v[i].eq(1),
                    pending_old[i].eq(self.u.mv_upd_old[i]),
                    pending_new[i].eq(self.u.mv_upd_new[i]),
                    pending_core[i].eq(Const(i, core_id_w)),
                    pending_epoch[i].eq(epoch),
                ]

        # Backpressure accounting: cycles where mv_upd_valid was asserted but wrapper was not ready.
        # (Previously: counted dropped pulses. Step59 turns mv_upd into valid/ready so no drops.)
        overflow_inc = Signal(range(self.u.ncores + 1), name="clean_reloc_overflow_inc")
        overflow_expr = Const(0)
        for i in range(self.u.ncores):
            overflow_expr = overflow_expr + (self.u.mv_upd_valid[i] & (~self.u.mv_upd_ready[i]))
        m.d.comb += overflow_inc.eq(overflow_expr)
        with m.If(overflow_inc != 0):
            m.d.sync += self.dbg_reloc_overflow.eq(self.dbg_reloc_overflow + overflow_inc)

        # Stats
        m.d.comb += [
            self.mark_count_total.eq(self.u.mark_count_total),
            self.mark_dup_drop_total.eq(self.u.mark_dup_drop_total),
            self.mark_hit_total.eq(self.u.mark_hit_total),
            self.mark_miss_total.eq(self.u.mark_miss_total),
            self.mark_replace_total.eq(self.u.mark_replace_total),
        ]
        return m