# rtl/jasper_gc_accelerator_scheduler.py
# P1: RegionScheduler — epoch validation, region ownership, command routing.
from amaranth import *
from rtl.jasper_gc_accelerator_config import CmdType, CompletionStatus


class RegionScheduler(Elaboratable):
    """Scheduler: validates epoch, manages region ownership, routes commands."""
    def __init__(self, region_count=4, support_scan=True, support_sweep=True,
                 support_compact=False, support_rebuild=False,
                 support_relocate=False, support_large_move=False,
                 support_bg_phase=False):
        self.region_count = region_count
        self.support_scan = support_scan
        self.support_sweep = support_sweep
        self.support_compact = support_compact
        self.support_rebuild = support_rebuild
        self.support_relocate = support_relocate
        self.support_large_move = support_large_move
        self.support_bg_phase = support_bg_phase

        self.in_valid = Signal(); self.in_ready = Signal()
        self.in_type = Signal(4); self.in_correlation_id = Signal(16)
        self.in_epoch = Signal(8); self.in_merge_domain = Signal(4)
        self.in_region_base = Signal(32); self.in_region_size = Signal(32)
        self.in_priority = Signal(2); self.in_flags = Signal(8)
        self.current_epoch = Signal(8)

        self.out_valid = Signal(); self.out_ready = Signal()
        self.out_type = Signal(4); self.out_correlation_id = Signal(16)
        self.out_epoch = Signal(8); self.out_merge_domain = Signal(4)
        self.out_region_base = Signal(32); self.out_region_size = Signal(32)
        self.out_priority = Signal(2); self.out_flags = Signal(8)

        self.comp_valid = Signal(); self.comp_ready = Signal()
        self.comp_status = Signal(3); self.comp_correlation_id = Signal(16)
        self.comp_epoch = Signal(8); self.comp_merge_domain = Signal(4)
        self.busy = Signal()
        self.unlock = Signal()
        self.unlock_region = Signal(max(region_count, 1))

        # Debug signals (initialized here, driven in elaborate)
        self._reject_stale = Signal()
        self._reject_unsupp = Signal()
        self._reject_busy = Signal()

    def elaborate(self, platform):
        m = Module(); R = self.region_count

        # Region lock state: 0=IDLE, 1=SCAN(shared), 2=EXCLUSIVE
        region_lock = [Signal(2, init=0) for _ in range(R)]
        region_owner_cid = [Signal(16, init=0) for _ in range(R)]

        # Expose debug signals
        self._region_lock = region_lock
        self._region_id = Signal(max(R, 1))
        self._region_busy = Signal()
        self._region_scanning = Signal()
        self._cmd_supported = Signal()
        self._is_excl = Signal()
        self._epoch_ok = Signal()
        self._issue = Signal()

        # Region index from address (top bits)
        region_id = self._region_id
        if R > 1:
            shift = 28; bw = (R - 1).bit_length()
            m.d.comb += region_id.eq(self.in_region_base[shift:shift + bw])
        else:
            m.d.comb += region_id.eq(0)

        # Support check via Mux tree
        def support_mux():
            v = Const(0)
            for t in range(9):
                supported = {
                    0: self.support_scan, 1: self.support_sweep,
                    2: self.support_compact, 3: self.support_rebuild,
                    4: self.support_relocate, 5: True,  # PREFETCH always
                    6: self.support_relocate, 7: self.support_large_move,
                    8: self.support_bg_phase,
                }.get(t, False)
                v = Mux(self.in_type == t, Const(1 if supported else 0), v)
            return v

        cmd_supported = self._cmd_supported
        m.d.comb += cmd_supported.eq(support_mux())

        # Exclusive check
        is_excl = self._is_excl
        excl_mux = Const(0)
        for t in range(9):
            excl = 0 if t in (0, 5) else 1  # SCAN(0) and PREFETCH(5) are shared
            excl_mux = Mux(self.in_type == t, Const(excl), excl_mux)
        m.d.comb += is_excl.eq(excl_mux)

        # Region lock check: Mux tree over region_count
        region_busy = self._region_busy
        region_scanning = self._region_scanning
        busy_mux = Const(0)
        scan_mux = Const(0)
        for r in range(R):
            busy_mux = Mux(region_id == r, region_lock[r] != 0, busy_mux)
            scan_mux = Mux(region_id == r, region_lock[r] == 1, scan_mux)
        m.d.comb += [
            region_busy.eq(busy_mux),
            region_scanning.eq(scan_mux),
        ]

        # Epoch check
        epoch_ok = self._epoch_ok
        m.d.comb += epoch_ok.eq(self.in_epoch >= self.current_epoch)

        # Decision
        m.d.comb += self.in_ready.eq(~self.busy)
        accepted = Signal()
        m.d.comb += accepted.eq(self.in_valid & self.in_ready)

        reject_stale = self._reject_stale
        reject_unsupp = self._reject_unsupp
        reject_busy = self._reject_busy
        issue = self._issue

        m.d.comb += [
            reject_stale.eq(accepted & ~epoch_ok),
            reject_unsupp.eq(accepted & epoch_ok & ~cmd_supported),
            reject_busy.eq(accepted & epoch_ok & cmd_supported & region_busy & (is_excl | ~region_scanning)),
            issue.eq(accepted & epoch_ok & cmd_supported & ~(region_busy & (is_excl | ~region_scanning))),
        ]

        # Issue to engine (purely combinational — valid only on issue cycle)
        m.d.comb += [
            self.out_valid.eq(issue),
            self.out_type.eq(self.in_type),
            self.out_correlation_id.eq(self.in_correlation_id),
            self.out_epoch.eq(self.in_epoch),
            self.out_merge_domain.eq(self.in_merge_domain),
            self.out_region_base.eq(self.in_region_base),
            self.out_region_size.eq(self.in_region_size),
            self.out_priority.eq(self.in_priority),
            self.out_flags.eq(self.in_flags),
        ]

        # Lock region on issue
        for r in range(R):
            with m.If(issue & self.out_ready & (region_id == r)):
                m.d.sync += region_lock[r].eq(Mux(is_excl, 2, 1))

        # Immediate reject completions
        m.d.comb += [
            self.comp_valid.eq(reject_stale | reject_unsupp | reject_busy),
            self.comp_status.eq(Mux(reject_stale, 3,
                               Mux(reject_unsupp, 5, 2))),
            self.comp_correlation_id.eq(self.in_correlation_id),
            self.comp_epoch.eq(self.in_epoch),
            self.comp_merge_domain.eq(self.in_merge_domain),
        ]

        # Busy: when command is being processed (accepted but not yet issued/rejected)
        m.d.comb += self.busy.eq(0)

        # Region unlock on engine completion
        with m.If(self.unlock):
            for r in range(R):
                with m.If(self.unlock_region == r):
                    m.d.sync += region_lock[r].eq(0)

        return m
