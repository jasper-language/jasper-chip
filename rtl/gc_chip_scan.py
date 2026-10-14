# rtl/gc_chip_scan.py
# Step53: Scan chip top-level wrapper for the 3-chip GC partition.

from __future__ import annotations

from amaranth import Array, Module, Signal
from amaranth.hdl import Elaboratable

from .gc_scan_coproc import GCScanCoProc


class GCScanChipTop(Elaboratable):
    """Scan chip wrapper (re-exporting GCScanCoProc ports)."""

    def __init__(self, **kwargs):
        self.u = GCScanCoProc(**kwargs)

        # NOTE (Step54): explicit chip boundary ports (no aliasing).

        # Write-barrier event input (from CPU/mutator fabric). Per-core arrays.
        self.wb_valid = Array(Signal.like(self.u.wb_valid[i], name=f"scan_wb{i}_valid") for i in range(self.u.ncores))
        self.wb_ready = Array(Signal.like(self.u.wb_ready[i], name=f"scan_wb{i}_ready") for i in range(self.u.ncores))
        self.wb_addr  = Array(Signal.like(self.u.wb_addr[i],  name=f"scan_wb{i}_addr")  for i in range(self.u.ncores))
        self.wb_data  = Array(Signal.like(self.u.wb_data[i],  name=f"scan_wb{i}_data")  for i in range(self.u.ncores))

        # Epoch broadcast
        self.epoch_advance = Signal.like(self.u.epoch_advance, name="scan_epoch_advance")

        # Card stream output (to Clean chip)
        self.out_valid = Signal.like(self.u.out_valid, name="scan_out_valid")
        self.out_ready = Signal.like(self.u.out_ready, name="scan_out_ready")
        self.out_card_id = Signal.like(self.u.out_card_id, name="scan_out_card_id")
        self.out_core_id = Signal.like(self.u.out_core_id, name="scan_out_core_id")
        self.out_epoch = Signal.like(self.u.out_epoch, name="scan_out_epoch")

        # Optional observability (kept as part of chip ports for bring-up). Per-core arrays.
        self.ev_count = Array(Signal.like(self.u.ev_count[i], name=f"scan{i}_evcnt") for i in range(self.u.ncores))
        self.in_count = Array(Signal.like(self.u.in_count[i], name=f"scan{i}_incnt") for i in range(self.u.ncores))
        self.uniq_enq = Array(Signal.like(self.u.uniq_enq[i], name=f"scan{i}_uniq") for i in range(self.u.ncores))
        self.dup_drop = Array(Signal.like(self.u.dup_drop[i], name=f"scan{i}_dup") for i in range(self.u.ncores))
        self.trap = Array(Signal.like(self.u.trap[i], name=f"scantrap{i}") for i in range(self.u.ncores))

    def elaborate(self, platform):
        m = Module()
        m.submodules.scan = self.u

        # WB input -> scan (per-core)
        for i in range(self.u.ncores):
            m.d.comb += [
                self.u.wb_valid[i].eq(self.wb_valid[i]),
                self.wb_ready[i].eq(self.u.wb_ready[i]),
                self.u.wb_addr[i].eq(self.wb_addr[i]),
                self.u.wb_data[i].eq(self.wb_data[i]),
            ]

        # Epoch broadcast
        m.d.comb += self.u.epoch_advance.eq(self.epoch_advance)

        # Card stream scan -> clean
        m.d.comb += [
            self.out_valid.eq(self.u.out_valid),
            self.u.out_ready.eq(self.out_ready),
            self.out_card_id.eq(self.u.out_card_id),
            self.out_core_id.eq(self.u.out_core_id),
            self.out_epoch.eq(self.u.out_epoch),
        ]

        # Observability (per-core)
        for i in range(self.u.ncores):
            m.d.comb += [
                self.ev_count[i].eq(self.u.ev_count[i]),
                self.in_count[i].eq(self.u.in_count[i]),
                self.uniq_enq[i].eq(self.u.uniq_enq[i]),
                self.dup_drop[i].eq(self.u.dup_drop[i]),
            ]
        for i in range(self.u.ncores):
            m.d.comb += self.trap[i].eq(self.u.trap[i])
        return m
