# rtl/gc_chip_move.py
# Step53: Move chip top-level wrapper (forwarding map / load barrier service).

from __future__ import annotations

from amaranth import Array, Module, Mux, Signal
from amaranth.hdl import Elaboratable

from .gc_mv_coproc import GCMvCoProc


class GCMoveChipTop(Elaboratable):
    """Move chip wrapper (re-exporting GCMvCoProc ports)."""

    def __init__(self, **kwargs):
        self.u = GCMvCoProc(**kwargs)

        # NOTE (Step54): explicit chip boundary ports (no aliasing).

        # CPU/µop command/response interface (MV_QUERY etc.) per-core arrays
        self.cmd_enq_valid = Array(Signal.like(self.u.cmd_enq_valid[i], name=f"move_cmd{i}_valid") for i in range(self.u.ncores))
        self.cmd_enq_ready = Array(Signal.like(self.u.cmd_enq_ready[i], name=f"move_cmd{i}_ready") for i in range(self.u.ncores))
        self.cmd_tag = Array(Signal.like(self.u.cmd_tag[i], name=f"move_cmd{i}_tag") for i in range(self.u.ncores))
        self.cmd_op = Array(Signal.like(self.u.cmd_op[i], name=f"move_cmd{i}_op") for i in range(self.u.ncores))
        self.cmd_rd = Array(Signal.like(self.u.cmd_rd[i], name=f"move_cmd{i}_rd") for i in range(self.u.ncores))
        self.cmd_rs1 = Array(Signal.like(self.u.cmd_rs1[i], name=f"move_cmd{i}_rs1") for i in range(self.u.ncores))
        self.cmd_rs2 = Array(Signal.like(self.u.cmd_rs2[i], name=f"move_cmd{i}_rs2") for i in range(self.u.ncores))

        self.rsp_valid = Array(Signal.like(self.u.rsp_valid[i], name=f"move_rsp{i}_valid") for i in range(self.u.ncores))
        self.rsp_tag = Array(Signal.like(self.u.rsp_tag[i], name=f"move_rsp{i}_tag") for i in range(self.u.ncores))
        self.rsp_rd = Array(Signal.like(self.u.rsp_rd[i], name=f"move_rsp{i}_rd") for i in range(self.u.ncores))
        self.rsp_data = Array(Signal.like(self.u.rsp_data[i], name=f"move_rsp{i}_data") for i in range(self.u.ncores))
        self.rsp_take = Array(Signal.like(self.u.rsp_take[i], name=f"move_rsp{i}_take") for i in range(self.u.ncores))
        self.trap = Array(Signal.like(self.u.trap[i], name=f"move_trap{i}") for i in range(self.u.ncores))

        # Epoch broadcast
        self.epoch_advance = Signal.like(self.u.epoch_advance, name="move_epoch_advance")

        # Sideband updates from Clean reloc commit (per-core arrays)
        self.upd_valid = Array(Signal.like(self.u.upd_valid[i], name=f"move_upd{i}_valid") for i in range(self.u.ncores))
        self.upd_old = Array(Signal.like(self.u.upd_old[i], name=f"move_upd{i}_old") for i in range(self.u.ncores))
        self.upd_new = Array(Signal.like(self.u.upd_new[i], name=f"move_upd{i}_new") for i in range(self.u.ncores))
        self.upd_epoch = Array(Signal.like(self.u.upd_epoch[i], name=f"move_upd{i}_epoch") for i in range(self.u.ncores))



        # Step56: Optional reloc update stream input (preferred inter-chip link form).
        core_id_w = max(1, (self.u.ncores - 1).bit_length())
        self.reloc_in_valid = Signal(name="move_reloc_in_valid")
        self.reloc_in_ready = Signal(name="move_reloc_in_ready")
        self.reloc_in_old   = Signal(32, name="move_reloc_in_old")
        self.reloc_in_new   = Signal(32, name="move_reloc_in_new")
        self.reloc_in_core  = Signal(core_id_w, name="move_reloc_in_core")
        self.reloc_in_epoch = Signal(1, name="move_reloc_in_epoch")

    def elaborate(self, platform):
        m = Module()
        m.submodules.move = self.u

        # CPU cmd/rsp wiring (per-core)
        for i in range(self.u.ncores):
            m.d.comb += [
                # cmd -> move
                self.u.cmd_enq_valid[i].eq(self.cmd_enq_valid[i]),
                self.cmd_enq_ready[i].eq(self.u.cmd_enq_ready[i]),
                self.u.cmd_tag[i].eq(self.cmd_tag[i]),
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
            ]

        # Epoch broadcast
        m.d.comb += self.u.epoch_advance.eq(self.epoch_advance)

        # Step56: reloc update stream input is accepted unconditionally.
        m.d.comb += self.reloc_in_ready.eq(1)
        fire = Signal(name="move_reloc_fire")
        m.d.comb += fire.eq(self.reloc_in_valid & self.reloc_in_ready)

        # Sideband (clean -> move) per-core, with optional stream injection (stream has priority for the targeted core).
        for i in range(self.u.ncores):
            fire_i = fire & (self.reloc_in_core == i)
            m.d.comb += [
                self.u.upd_valid[i].eq(self.upd_valid[i] | fire_i),
                self.u.upd_old[i].eq(Mux(fire_i, self.reloc_in_old, self.upd_old[i])),
                self.u.upd_new[i].eq(Mux(fire_i, self.reloc_in_new, self.upd_new[i])),
                self.u.upd_epoch[i].eq(Mux(fire_i, self.reloc_in_epoch, self.upd_epoch[i])),
            ]

        return m
