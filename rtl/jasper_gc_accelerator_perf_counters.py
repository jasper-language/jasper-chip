# rtl/jasper_gc_accelerator_perf_counters.py
# Performance counters for JasperGCAcceleratorIP — observability v0.1.
# All counters are 32-bit, saturating (stop at 0xFFFFFFFF).
# No ready/valid timing is modified; counters are read-only debug signals.
from amaranth import *


class _SatCounter(Elaboratable):
    """32-bit saturating counter: increments when `inc` is high, saturates at max."""
    def __init__(self):
        self.inc = Signal()
        self.val = Signal(32, init=0)

    def elaborate(self, platform):
        m = Module()
        nxt = Signal(32)
        m.d.comb += nxt.eq(self.val + 1)
        with m.If(self.inc & (self.val != 0xFFFFFFFF)):
            m.d.sync += self.val.eq(nxt)
        return m


class _MaxTracker(Elaboratable):
    """Tracks maximum run length of `cond`."""
    def __init__(self):
        self.cond = Signal()
        self.run = Signal(32, init=0)
        self.max = Signal(32, init=0)

    def elaborate(self, platform):
        m = Module()
        with m.If(self.cond):
            m.d.sync += self.run.eq(self.run + 1)
            with m.If(self.run + 1 > self.max):
                m.d.sync += self.max.eq(self.run + 1)
        with m.Else():
            m.d.sync += self.run.eq(0)
        return m


class JasperGCAcceleratorPerfCounters(Elaboratable):
    """Performance counters for accelerator observability v0.1.

    Connect to JasperGCAcceleratorIP internal signals.
    All counters are 32-bit saturating; max trackers record longest backpressure run.
    """
    def __init__(self):
        # -- Command path --
        self.cmd_accepted = _SatCounter()
        self.cmd_backpressure = _SatCounter()
        self.cmd_stall_max = _MaxTracker()
        self.cmd_rejected = _SatCounter()

        # -- Completion path --
        self.comp_accepted = _SatCounter()
        self.comp_backpressure = _SatCounter()
        self.comp_stall_max = _MaxTracker()
        self.comp_route_mismatch = _SatCounter()  # not wired in v0.1

        # -- Memory path --
        self.mem_req_accepted = _SatCounter()
        self.mem_rsp_accepted = _SatCounter()
        self.mem_req_backpressure = _SatCounter()
        self.mem_rsp_backpressure = _SatCounter()
        self.mem_stall_max = _MaxTracker()
        self.outstanding_block = _SatCounter()

        # -- Per-engine command accepted --
        self.scan_cmd_accepted = _SatCounter()
        self.sweep_cmd_accepted = _SatCounter()
        self.rebuild_cmd_accepted = _SatCounter()
        self.compact_cmd_accepted = _SatCounter()

        # -- Per-engine memory request accepted --
        self.scan_mem_req_accepted = _SatCounter()
        self.sweep_mem_req_accepted = _SatCounter()
        self.rebuild_mem_req_accepted = _SatCounter()
        self.compact_mem_req_accepted = _SatCounter()

        # -- Per-engine completion accepted --
        self.scan_comp_accepted = _SatCounter()
        self.sweep_comp_accepted = _SatCounter()
        self.rebuild_comp_accepted = _SatCounter()
        self.compact_comp_accepted = _SatCounter()

        # -- Per-engine busy cycles --
        self.scan_busy = _SatCounter()
        self.sweep_busy = _SatCounter()
        self.rebuild_busy = _SatCounter()
        self.compact_busy = _SatCounter()

        # -- Per-engine memory stall cycles (engine in WAIT) --
        self.scan_mem_stall = _SatCounter()
        self.sweep_mem_stall = _SatCounter()
        self.rebuild_mem_stall = _SatCounter()
        self.compact_mem_stall = _SatCounter()

        # -- Reject counters --
        self.stale_epoch_reject = _SatCounter()
        self.unsupported_reject = _SatCounter()
        self.region_busy_reject = _SatCounter()

        # -- Input signals (connect in the accelerator) --
        self.cmd_valid = Signal()
        self.cmd_ready = Signal()
        self.comp_valid = Signal()
        self.comp_ready = Signal()
        self.mem_req_valid = Signal()
        self.mem_req_ready = Signal()
        self.mem_rsp_valid = Signal()
        self.mem_rsp_ready = Signal()
        self.arb_outstanding = Signal()
        self.arb_any_engine_req = Signal()
        # Per-engine
        self.to_scan = Signal()
        self.to_sweep = Signal()
        self.to_ce = Signal()
        self.to_mre = Signal()
        self.scan_mem_req_v = Signal()
        self.scan_mem_req_r = Signal()
        self.sweep_mem_req_v = Signal()
        self.sweep_mem_req_r = Signal()
        self.mre_mem_req_v = Signal()
        self.mre_mem_req_r = Signal()
        self.ce_mem_req_v = Signal()
        self.ce_mem_req_r = Signal()
        self.scan_busy_sig = Signal()
        self.sweep_busy_sig = Signal()
        self.mre_busy_sig = Signal()
        self.ce_busy_sig = Signal()
        self.scan_out_v = Signal()
        self.scan_out_r = Signal()
        self.sweep_out_v = Signal()
        self.sweep_out_r = Signal()
        self.mre_out_v = Signal()
        self.mre_out_r = Signal()
        self.ce_out_v = Signal()
        self.ce_out_r = Signal()
        # Scheduler reject signals
        self.reject_stale = Signal()
        self.reject_unsupp = Signal()
        self.reject_busy = Signal()

    def elaborate(self, platform):
        m = Module()
        subs = [
            'cmd_accepted', 'cmd_backpressure', 'cmd_rejected',
            'comp_accepted', 'comp_backpressure', 'comp_route_mismatch',
            'mem_req_accepted', 'mem_rsp_accepted',
            'mem_req_backpressure', 'mem_rsp_backpressure',
            'outstanding_block',
            'scan_cmd_accepted', 'sweep_cmd_accepted',
            'rebuild_cmd_accepted', 'compact_cmd_accepted',
            'scan_mem_req_accepted', 'sweep_mem_req_accepted',
            'rebuild_mem_req_accepted', 'compact_mem_req_accepted',
            'scan_comp_accepted', 'sweep_comp_accepted',
            'rebuild_comp_accepted', 'compact_comp_accepted',
            'scan_busy', 'sweep_busy', 'rebuild_busy', 'compact_busy',
            'scan_mem_stall', 'sweep_mem_stall',
            'rebuild_mem_stall', 'compact_mem_stall',
            'stale_epoch_reject', 'unsupported_reject', 'region_busy_reject',
        ]
        for name in subs:
            m.submodules[name] = getattr(self, name)

        max_trackers = ['cmd_stall_max', 'comp_stall_max', 'mem_stall_max']
        for name in max_trackers:
            m.submodules[name] = getattr(self, name)

        # Command path
        m.d.comb += self.cmd_accepted.inc.eq(self.cmd_valid & self.cmd_ready)
        m.d.comb += self.cmd_backpressure.inc.eq(self.cmd_valid & ~self.cmd_ready)
        m.d.comb += self.cmd_stall_max.cond.eq(self.cmd_valid & ~self.cmd_ready)

        # Completion path
        m.d.comb += self.comp_accepted.inc.eq(self.comp_valid & self.comp_ready)
        m.d.comb += self.comp_backpressure.inc.eq(self.comp_valid & ~self.comp_ready)
        m.d.comb += self.comp_stall_max.cond.eq(self.comp_valid & ~self.comp_ready)
        # comp_route_mismatch: not wired in v0.1 — always 0

        # Memory path
        m.d.comb += self.mem_req_accepted.inc.eq(self.mem_req_valid & self.mem_req_ready)
        m.d.comb += self.mem_rsp_accepted.inc.eq(self.mem_rsp_valid & self.mem_rsp_ready)
        m.d.comb += self.mem_req_backpressure.inc.eq(self.mem_req_valid & ~self.mem_req_ready)
        m.d.comb += self.mem_rsp_backpressure.inc.eq(self.mem_rsp_valid & ~self.mem_rsp_ready)
        m.d.comb += self.mem_stall_max.cond.eq(self.mem_req_valid & ~self.mem_req_ready)
        m.d.comb += self.outstanding_block.inc.eq(
            self.arb_outstanding & self.arb_any_engine_req)

        # Per-engine command accepted
        m.d.comb += self.scan_cmd_accepted.inc.eq(self.to_scan)
        m.d.comb += self.sweep_cmd_accepted.inc.eq(self.to_sweep)
        m.d.comb += self.rebuild_cmd_accepted.inc.eq(self.to_mre)
        m.d.comb += self.compact_cmd_accepted.inc.eq(self.to_ce)

        # Per-engine memory request accepted
        m.d.comb += self.scan_mem_req_accepted.inc.eq(
            self.scan_mem_req_v & self.scan_mem_req_r)
        m.d.comb += self.sweep_mem_req_accepted.inc.eq(
            self.sweep_mem_req_v & self.sweep_mem_req_r)
        m.d.comb += self.rebuild_mem_req_accepted.inc.eq(
            self.mre_mem_req_v & self.mre_mem_req_r)
        m.d.comb += self.compact_mem_req_accepted.inc.eq(
            self.ce_mem_req_v & self.ce_mem_req_r)

        # Per-engine completion accepted
        m.d.comb += self.scan_comp_accepted.inc.eq(
            self.scan_out_v & self.scan_out_r)
        m.d.comb += self.sweep_comp_accepted.inc.eq(
            self.sweep_out_v & self.sweep_out_r)
        m.d.comb += self.rebuild_comp_accepted.inc.eq(
            self.mre_out_v & self.mre_out_r)
        m.d.comb += self.compact_comp_accepted.inc.eq(
            self.ce_out_v & self.ce_out_r)

        # Per-engine busy cycles
        m.d.comb += self.scan_busy.inc.eq(self.scan_busy_sig)
        m.d.comb += self.sweep_busy.inc.eq(self.sweep_busy_sig)
        m.d.comb += self.rebuild_busy.inc.eq(self.mre_busy_sig)
        m.d.comb += self.compact_busy.inc.eq(self.ce_busy_sig)

        # Per-engine memory stall: engine busy AND mem_req_valid AND NOT mem_req_ready
        m.d.comb += self.scan_mem_stall.inc.eq(
            self.scan_busy_sig & self.scan_mem_req_v & ~self.scan_mem_req_r)
        m.d.comb += self.sweep_mem_stall.inc.eq(
            self.sweep_busy_sig & self.sweep_mem_req_v & ~self.sweep_mem_req_r)
        m.d.comb += self.rebuild_mem_stall.inc.eq(
            self.mre_busy_sig & self.mre_mem_req_v & ~self.mre_mem_req_r)
        m.d.comb += self.compact_mem_stall.inc.eq(
            self.ce_busy_sig & self.ce_mem_req_v & ~self.ce_mem_req_r)

        # Reject counters (from scheduler)
        m.d.comb += self.stale_epoch_reject.inc.eq(self.reject_stale)
        m.d.comb += self.unsupported_reject.inc.eq(self.reject_unsupp)
        m.d.comb += self.region_busy_reject.inc.eq(self.reject_busy)

        return m
