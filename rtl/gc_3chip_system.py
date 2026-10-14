# rtl/gc_3chip_system.py
# Step53: Example wiring of Scan/Clean/Move chip tops.
# Step56: Add a reloc-update link FIFO between Clean and Move to model chip-to-chip transport/backpressure.

from __future__ import annotations

from amaranth import Cat, Module, Signal
from amaranth.hdl import Elaboratable
from amaranth.lib.fifo import SyncFIFO

from .gc_chip_scan import GCScanChipTop
from .gc_chip_clean import GCCleanChipTop
from .gc_chip_move import GCMoveChipTop


class GC3ChipSystem(Elaboratable):
    """A minimal harness that instantiates and wires the 3 GC chips.

    This harness is not used by TopSoC; it's a reference design for the 3-chip
    partition with explicit black-box boundaries. It is used by protocol/contract
    tests (Step55+).

    External pins:
      - epoch_advance: broadcast epoch flip (1-cycle pulse)
      - reloc_link_enable: when 0, stalls delivery of Clean->Move reloc updates (for tests)
      - card_link_enable: when 0, stalls delivery of Scan->Clean card records (for tests)
    """

    def __init__(
        self,
        ncores=2,
        scan_kwargs=None,
        clean_kwargs=None,
        move_kwargs=None,
        reloc_link_depth=2,
        card_link_depth=2,
        enable_scan=True,
        use_autotuned_defaults=False,
    ):
        self.ncores = int(ncores)
        scan_kwargs = dict(scan_kwargs or {})
        clean_kwargs = dict(clean_kwargs or {})
        move_kwargs = dict(move_kwargs or {})

        # Resolve effective inter-chip link depths.
        card_link_depth_eff = int(card_link_depth)
        reloc_link_depth_eff = int(reloc_link_depth)

        # Step71: optionally use autotuned defaults written by tools.step71_apply_autotune.
        # This is a simulation/convenience knob; hardware parameters remain explicit.
        if use_autotuned_defaults:
            try:
                from . import autotuned_link_depths as _ald
                if int(getattr(_ald, "VALID", 0)) == 1:
                    card_link_depth_eff = int(getattr(_ald, "CARD_LINK_DEPTH", card_link_depth_eff))
                    reloc_link_depth_eff = int(getattr(_ald, "RELOC_LINK_DEPTH", reloc_link_depth_eff))
            except Exception:
                # Missing module or invalid content: fall back to explicit args.
                pass

        # Expose effective depths for tests/tools.
        self.effective_card_link_depth = int(card_link_depth_eff)
        self.effective_reloc_link_depth = int(reloc_link_depth_eff)

        # Instantiate
        self.enable_scan = bool(enable_scan)
        self.scan = GCScanChipTop(ncores=self.ncores, **scan_kwargs) if self.enable_scan else None
        self.clean = GCCleanChipTop(ncores=self.ncores, **clean_kwargs)
        self.move = GCMoveChipTop(ncores=self.ncores, **move_kwargs)

        # Exported pins (so convert() has something to port)
        self.epoch_advance = Signal(name="gc_epoch_advance")
        self.reloc_link_enable = Signal(reset=1, name="gc_reloc_link_enable")
        self.reloc_link_depth = int(self.effective_reloc_link_depth)
        self.card_link_enable = Signal(reset=1, name="gc_card_link_enable")
        self.card_link_depth = int(self.effective_card_link_depth)

        # Step62: observability for inter-chip transport occupancy (useful for backpressure tests/profiling).
        self.dbg_reloc_link_level = Signal(32, name="gc_dbg_reloc_link_level")
        self.dbg_card_link_level  = Signal(32, name="gc_dbg_card_link_level")

        # Step72: also export the configured depths (constants) for observability.
        self.dbg_reloc_link_depth = Signal(32, reset=self.reloc_link_depth, name="gc_dbg_reloc_link_depth")
        self.dbg_card_link_depth  = Signal(32, reset=self.card_link_depth,  name="gc_dbg_card_link_depth")

    def elaborate(self, platform):
        m = Module()
        if self.enable_scan:
            m.submodules.scan = self.scan
        m.submodules.clean = self.clean
        m.submodules.move = self.move

        # Constant debug exports.
        m.d.comb += [
            self.dbg_card_link_depth.eq(self.card_link_depth),
            self.dbg_reloc_link_depth.eq(self.reloc_link_depth),
        ]

        # --- Internal wiring ---
        # Scan -> Clean card stream
        if self.enable_scan:
            # Step60: add an explicit Scan->Clean transport FIFO to model inter-chip delay/backpressure.
            core_id_w = max(1, (self.ncores - 1).bit_length())
            card_link = SyncFIFO(width=32 + core_id_w + 1, depth=self.card_link_depth)
            m.submodules.card_link = card_link

            m.d.comb += self.dbg_card_link_level.eq(card_link.level)

            # Scan pushes card records into the transport FIFO.
            m.d.comb += [
                card_link.w_en.eq(self.scan.out_valid & card_link.w_rdy),
                card_link.w_data.eq(Cat(self.scan.out_card_id, self.scan.out_core_id, self.scan.out_epoch)),
                self.scan.out_ready.eq(card_link.w_rdy),
            ]

            # Deliver to clean; allow tests to stall delivery with card_link_enable.
            m.d.comb += [
                self.clean.card_in_valid.eq(card_link.r_rdy & self.card_link_enable),
                self.clean.card_in_card_id.eq(card_link.r_data[0:32]),
                self.clean.card_in_core_id.eq(card_link.r_data[32:32 + core_id_w]),
                self.clean.card_in_epoch.eq(card_link.r_data[32 + core_id_w:32 + core_id_w + 1]),
                card_link.r_en.eq(self.clean.card_in_ready & card_link.r_rdy & self.card_link_enable),
            ]
        else:
            m.d.comb += self.dbg_card_link_level.eq(0)
            # No scan chip in this harness configuration; keep card input idle.
            m.d.comb += [
                self.clean.card_in_valid.eq(0),
                self.clean.card_in_card_id.eq(0),
                self.clean.card_in_core_id.eq(0),
                self.clean.card_in_epoch.eq(0),
            ]

        # Clean -> Move reloc update stream + a small link FIFO to model chip-to-chip transport. reloc update stream + a small link FIFO to model chip-to-chip transport.
        core_id_w = max(1, (self.ncores - 1).bit_length())
        link_w = 32 + 32 + core_id_w + 1
        fifo = SyncFIFO(width=link_w, depth=self.reloc_link_depth)
        m.submodules.reloc_link_fifo = fifo

        m.d.comb += self.dbg_reloc_link_level.eq(fifo.level)

        # Push from Clean stream
        m.d.comb += [
            self.clean.reloc_out_ready.eq(fifo.w_rdy),
            fifo.w_en.eq(self.clean.reloc_out_valid & fifo.w_rdy),
            fifo.w_data.eq(Cat(self.clean.reloc_out_old, self.clean.reloc_out_new, self.clean.reloc_out_core, self.clean.reloc_out_epoch)),
        ]

        # Pop to Move stream (can be stalled by reloc_link_enable for backpressure tests)
        m.d.comb += [
            self.move.reloc_in_valid.eq(fifo.r_rdy & self.reloc_link_enable),
            self.move.reloc_in_old.eq(fifo.r_data[0:32]),
            self.move.reloc_in_new.eq(fifo.r_data[32:64]),
            self.move.reloc_in_core.eq(fifo.r_data[64:64 + core_id_w]),
            self.move.reloc_in_epoch.eq(fifo.r_data[64 + core_id_w:64 + core_id_w + 1]),
            fifo.r_en.eq(fifo.r_rdy & self.reloc_link_enable & self.move.reloc_in_ready),
        ]

        # Epoch broadcast (external in this harness)
        m.d.comb += self.clean.epoch_advance.eq(self.epoch_advance)
        if self.enable_scan:
            m.d.comb += self.scan.epoch_advance.eq(self.epoch_advance)
        m.d.comb += self.move.epoch_advance.eq(self.epoch_advance)

        return m
