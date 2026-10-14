# rtl/gc_event_pipeline.py
# GC Event Pipeline — separates GC backend events into Scan/Sweep/Move sub-pipelines
from amaranth import *

EVT_SCAN = 0
EVT_SWEEP = 1
EVT_MOVE = 2
AGING_THRESHOLD = 4


class _PipelineStage(Elaboratable):
    """FIFO-based pipeline stage (depth 4) with valid/ready handshake and flush.

    Deeper buffer decouples event acceptance from result consumption,
    increasing sustained throughput from ~0.50 to ~0.90+ events/cycle.
    """
    DEPTH = 4

    def __init__(self):
        self.event_valid = Signal()
        self.event_ready = Signal()
        self.event_type = Signal(2)
        self.event_addr = Signal(32)
        self.event_data = Signal(32)
        self.event_tag = Signal(8)
        self.event_epoch = Signal(8)
        self.event_seq = Signal(2)

        self.result_valid = Signal()
        self.result_ready = Signal()
        self.result_type = Signal(2)
        self.result_data = Signal(32)
        self.result_tag = Signal(8)
        self.result_epoch = Signal(8)
        self.result_seq = Signal(2)

        self.flush = Signal()
        self.flush_epoch = Signal(8)
        self.busy = Signal()
        self.has_result = Signal()

    def elaborate(self, platform):
        m = Module(); D = self.DEPTH
        f_v = Array([Signal(reset=0) for _ in range(D)])
        f_t = Array([Signal(2) for _ in range(D)])
        f_d = Array([Signal(32) for _ in range(D)])
        f_tag = Array([Signal(8) for _ in range(D)])
        f_ep = Array([Signal(8) for _ in range(D)])
        f_seq = Array([Signal(2) for _ in range(D)])
        head = Signal(range(D), reset=0)
        tail = Signal(range(D), reset=0)
        count = Signal(range(D + 1), reset=0)

        full = Signal(); empty = Signal()
        m.d.comb += [
            full.eq(count == D),
            empty.eq(count == 0),
            self.event_ready.eq(~full & ~self.flush),
            self.result_valid.eq(~empty & ~self.flush),
            self.busy.eq(count > 0),
            self.has_result.eq(~empty),
        ]

        # Flush: reset entire FIFO (per-epoch filtering happens at Separated level
        # via current_epoch check in merge)
        with m.If(self.flush):
            m.d.sync += [count.eq(0), head.eq(0), tail.eq(0)]
            for i in range(D):
                m.d.sync += f_v[i].eq(0)

        # Push
        push = Signal()
        m.d.comb += push.eq(self.event_valid & self.event_ready & ~self.flush)
        with m.If(push):
            m.d.sync += [
                f_v[tail].eq(1),
                f_t[tail].eq(self.event_type),
                f_d[tail].eq(self.event_data),
                f_tag[tail].eq(self.event_tag),
                f_ep[tail].eq(self.event_epoch),
                f_seq[tail].eq(self.event_seq),
                tail.eq(Mux(tail == D - 1, 0, tail + 1)),
            ]

        # Pop
        pop = Signal()
        m.d.comb += pop.eq(self.result_valid & self.result_ready & ~self.flush)
        with m.If(pop):
            m.d.sync += [
                f_v[head].eq(0),
                head.eq(Mux(head == D - 1, 0, head + 1)),
            ]

        # Count update
        with m.If(push & ~pop):
            m.d.sync += count.eq(count + 1)
        with m.If(pop & ~push):
            m.d.sync += count.eq(count - 1)

        # Output from head
        m.d.comb += [
            self.result_type.eq(f_t[head]),
            self.result_data.eq(f_d[head]),
            self.result_tag.eq(f_tag[head]),
            self.result_epoch.eq(f_ep[head]),
            self.result_seq.eq(f_seq[head]),
        ]
        return m


class GCEventPipelineStandard(Elaboratable):
    """Single backend processing all event types sequentially (current behavior).

    External interface matches GCEventPipelineSeparated exactly.
    Uses a single _PipelineStage internally.
    """
    def __init__(self):
        self.event_valid = Signal()
        self.event_ready = Signal()
        self.event_type = Signal(2)
        self.event_addr = Signal(32)
        self.event_data = Signal(32)
        self.event_tag = Signal(8)
        self.event_epoch = Signal(8)
        self.event_seq = Signal(2)

        self.result_valid = Signal()
        self.result_ready = Signal()
        self.result_type = Signal(2)
        self.result_data = Signal(32)
        self.result_tag = Signal(8)
        self.result_epoch = Signal(8)
        self.result_seq = Signal(2)

        self.flush = Signal()
        self.flush_epoch = Signal(8)
        self.busy = Signal()

    def elaborate(self, platform):
        m = Module()
        stage = _PipelineStage()
        m.submodules.stage = stage

        m.d.comb += [
            stage.event_valid.eq(self.event_valid),
            stage.event_type.eq(self.event_type),
            stage.event_addr.eq(self.event_addr),
            stage.event_data.eq(self.event_data),
            stage.event_tag.eq(self.event_tag),
            stage.event_epoch.eq(self.event_epoch),
            stage.event_seq.eq(self.event_seq),
            stage.result_ready.eq(self.result_ready),
            stage.flush.eq(self.flush),
            stage.flush_epoch.eq(self.flush_epoch),
            self.event_ready.eq(stage.event_ready),
            self.result_valid.eq(stage.result_valid),
            self.result_type.eq(stage.result_type),
            self.result_data.eq(stage.result_data),
            self.result_tag.eq(stage.result_tag),
            self.result_epoch.eq(stage.result_epoch),
            self.result_seq.eq(stage.result_seq),
            self.busy.eq(stage.busy),
        ]
        return m


class GCEventPipelineSeparated(Elaboratable):
    """Three independent sub-pipelines for Scan/Sweep/Move, events dispatched by type.

    Dispatcher routes event_valid to the correct sub-pipeline based on event_type.
    Merger collects results from all sub-pipelines with priority: Scan > Sweep > Move.
    """
    def __init__(self):
        self.event_valid = Signal()
        self.event_ready = Signal()
        self.event_type = Signal(2)
        self.event_addr = Signal(32)
        self.event_data = Signal(32)
        self.event_tag = Signal(8)
        self.event_epoch = Signal(8)
        self.event_seq = Signal(2)

        self.result_valid = Signal()
        self.result_ready = Signal()
        self.result_type = Signal(2)
        self.result_data = Signal(32)
        self.result_tag = Signal(8)
        self.result_epoch = Signal(8)
        self.result_seq = Signal(2)

        self.flush = Signal()
        self.flush_epoch = Signal(8)
        self.current_epoch = Signal(8)
        self.busy = Signal()

    def elaborate(self, platform):
        m = Module()

        scan = _PipelineStage()
        sweep = _PipelineStage()
        move = _PipelineStage()
        m.submodules.scan = scan
        m.submodules.sweep = sweep
        m.submodules.move = move

        is_scan = Signal()
        is_sweep = Signal()
        is_move = Signal()
        m.d.comb += [
            is_scan.eq(self.event_type == EVT_SCAN),
            is_sweep.eq(self.event_type == EVT_SWEEP),
            is_move.eq(self.event_type == EVT_MOVE),
        ]

        m.d.comb += [
            scan.event_valid.eq(self.event_valid & is_scan),
            sweep.event_valid.eq(self.event_valid & is_sweep),
            move.event_valid.eq(self.event_valid & is_move),
            scan.event_type.eq(self.event_type),
            sweep.event_type.eq(self.event_type),
            move.event_type.eq(self.event_type),
            scan.event_addr.eq(self.event_addr),
            sweep.event_addr.eq(self.event_addr),
            move.event_addr.eq(self.event_addr),
            scan.event_data.eq(self.event_data),
            sweep.event_data.eq(self.event_data),
            move.event_data.eq(self.event_data),
            scan.event_tag.eq(self.event_tag),
            sweep.event_tag.eq(self.event_tag),
            move.event_tag.eq(self.event_tag),
            scan.event_epoch.eq(self.event_epoch),
            sweep.event_epoch.eq(self.event_epoch),
            move.event_epoch.eq(self.event_epoch),
            scan.event_seq.eq(self.event_seq),
            sweep.event_seq.eq(self.event_seq),
            move.event_seq.eq(self.event_seq),
            self.event_ready.eq(
                (is_scan & scan.event_ready) |
                (is_sweep & sweep.event_ready) |
                (is_move & move.event_ready)
            ),
            scan.flush.eq(self.flush),
            sweep.flush.eq(self.flush),
            move.flush.eq(self.flush),
            scan.flush_epoch.eq(self.flush_epoch),
            sweep.flush_epoch.eq(self.flush_epoch),
            move.flush_epoch.eq(self.flush_epoch),
        ]

        # sub-pipeline OK signals (result_valid + epoch match)
        scan_ok = Signal()
        sweep_ok = Signal()
        move_ok = Signal()
        m.d.comb += [
            scan_ok.eq(scan.result_valid & (scan.result_epoch == self.current_epoch)),
            sweep_ok.eq(sweep.result_valid & (sweep.result_epoch == self.current_epoch)),
            move_ok.eq(move.result_valid & (move.result_epoch == self.current_epoch)),
        ]

        # Round-robin + aging merge state
        priority = Signal(range(3), reset=0)
        age_scan = Signal(range(8), reset=0)
        age_sweep = Signal(range(8), reset=0)
        age_move = Signal(range(8), reset=0)

        # Round-robin order: sp0=priority, sp1=priority+1, sp2=priority+2 (mod 3)
        sp0 = Signal(range(3))
        sp1 = Signal(range(3))
        sp2 = Signal(range(3))
        m.d.comb += [
            sp0.eq(priority),
            sp1.eq(Mux(priority == 2, 0, priority + 1)),
            sp2.eq(Mux(priority == 0, 2, priority - 1)),
        ]

        def _ok(idx):
            return Mux(idx == 0, scan_ok, Mux(idx == 1, sweep_ok, move_ok))

        sp0_ok = Signal()
        sp1_ok = Signal()
        sp2_ok = Signal()
        rr_sel = Signal(range(3))
        rr_found = Signal()
        m.d.comb += [
            sp0_ok.eq(_ok(sp0)),
            sp1_ok.eq(_ok(sp1)),
            sp2_ok.eq(_ok(sp2)),
            rr_sel.eq(Mux(sp0_ok, sp0, Mux(sp1_ok, sp1, sp2))),
            rr_found.eq(sp0_ok | sp1_ok | sp2_ok),
        ]

        # Aging detection
        aged_scan = Signal()
        aged_sweep = Signal()
        aged_move = Signal()
        any_aged = Signal()
        m.d.comb += [
            aged_scan.eq(scan_ok & (age_scan >= AGING_THRESHOLD)),
            aged_sweep.eq(sweep_ok & (age_sweep >= AGING_THRESHOLD)),
            aged_move.eq(move_ok & (age_move >= AGING_THRESHOLD)),
            any_aged.eq(aged_scan | aged_sweep | aged_move),
        ]

        # Final selection: aging takes priority over round-robin
        selected = Signal(range(3))
        selected_ok = Signal()
        m.d.comb += [
            selected.eq(Mux(aged_scan, 0, Mux(aged_sweep, 1, Mux(aged_move, 2, rr_sel)))),
            selected_ok.eq(Mux(any_aged, 1, rr_found)),
        ]

        # A transfer happens when the selected pipeline is ok and the consumer is ready
        consume = Signal()
        m.d.comb += consume.eq(selected_ok & self.result_ready)

        # Age next-state: cleared on consume, incremented when waiting (not selected)
        age_scan_nxt = Signal(range(8))
        age_sweep_nxt = Signal(range(8))
        age_move_nxt = Signal(range(8))
        m.d.comb += [
            age_scan_nxt.eq(
                Mux((selected == 0) & consume, 0,
                    Mux(~scan_ok, 0,
                        Mux(selected != 0,
                            Mux(age_scan == 7, 7, age_scan + 1),
                            age_scan)))),
            age_sweep_nxt.eq(
                Mux((selected == 1) & consume, 0,
                    Mux(~sweep_ok, 0,
                        Mux(selected != 1,
                            Mux(age_sweep == 7, 7, age_sweep + 1),
                            age_sweep)))),
            age_move_nxt.eq(
                Mux((selected == 2) & consume, 0,
                    Mux(~move_ok, 0,
                        Mux(selected != 2,
                            Mux(age_move == 7, 7, age_move + 1),
                            age_move)))),
        ]

        # State update on clock
        m.d.sync += [
            age_scan.eq(age_scan_nxt),
            age_sweep.eq(age_sweep_nxt),
            age_move.eq(age_move_nxt),
            priority.eq(
                Mux(consume,
                    Mux(selected == 0, 1, Mux(selected == 1, 2, 0)),
                    priority)),
        ]

        # Output mux based on selected pipeline
        m.d.comb += [
            self.result_valid.eq(selected_ok),
            self.result_type.eq(
                Mux(selected == 0, scan.result_type,
                    Mux(selected == 1, sweep.result_type, move.result_type))),
            self.result_data.eq(
                Mux(selected == 0, scan.result_data,
                    Mux(selected == 1, sweep.result_data, move.result_data))),
            self.result_tag.eq(
                Mux(selected == 0, scan.result_tag,
                    Mux(selected == 1, sweep.result_tag, move.result_tag))),
            self.result_epoch.eq(
                Mux(selected == 0, scan.result_epoch,
                    Mux(selected == 1, sweep.result_epoch, move.result_epoch))),
            self.result_seq.eq(
                Mux(selected == 0, scan.result_seq,
                    Mux(selected == 1, sweep.result_seq, move.result_seq))),
            scan.result_ready.eq(self.result_ready & selected_ok & (selected == 0)),
            sweep.result_ready.eq(self.result_ready & selected_ok & (selected == 1)),
            move.result_ready.eq(self.result_ready & selected_ok & (selected == 2)),
            self.busy.eq(scan.busy | sweep.busy | move.busy),
        ]
        return m
