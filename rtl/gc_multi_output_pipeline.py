# rtl/gc_multi_output_pipeline.py
# Multi-Output Event Pipeline — Experimental.
# Distributes sub-pipeline results across N output ports.
from amaranth import *
from rtl.gc_event_pipeline import _PipelineStage, EVT_SCAN, EVT_SWEEP, EVT_MOVE


class MultiOutputEventPipeline(Elaboratable):
    """Event pipeline with N output result ports.

    Each sub-pipeline (scan/sweep/move) has a FIFO depth 4.
    Results are distributed across N output ports in round-robin order
    to increase sustained throughput beyond 1.0 evt/cyc.

    Parameters:
        output_ports (int): number of parallel result ports (1-4)
    """
    def __init__(self, output_ports=2):
        self.output_ports = output_ports
        self.event_valid = Signal()
        self.event_ready = Signal()
        self.event_type = Signal(2)
        self.event_addr = Signal(32)
        self.event_data = Signal(32)
        self.event_tag = Signal(8)
        self.event_epoch = Signal(8)
        self.event_seq = Signal(2)
        self.flush = Signal()
        self.flush_epoch = Signal(8)
        self.current_epoch = Signal(8)
        self.busy = Signal()

        # Result ports: each has valid/ready/type/data/tag/epoch/seq
        self.rsp_valid = [Signal() for _ in range(output_ports)]
        self.rsp_ready = [Signal() for _ in range(output_ports)]
        self.rsp_type = [Signal(2) for _ in range(output_ports)]
        self.rsp_data = [Signal(32) for _ in range(output_ports)]
        self.rsp_tag = [Signal(8) for _ in range(output_ports)]
        self.rsp_epoch = [Signal(8) for _ in range(output_ports)]
        self.rsp_seq = [Signal(2) for _ in range(output_ports)]

    def elaborate(self, platform):
        m = Module(); P = self; NP = P.output_ports

        scan = _PipelineStage(); sweep = _PipelineStage(); move = _PipelineStage()
        m.submodules.scan = scan; m.submodules.sweep = sweep; m.submodules.move = move

        is_scan = Signal(); is_sweep = Signal(); is_move = Signal()
        m.d.comb += [
            is_scan.eq(P.event_type == EVT_SCAN),
            is_sweep.eq(P.event_type == EVT_SWEEP),
            is_move.eq(P.event_type == EVT_MOVE),
            scan.event_valid.eq(P.event_valid & is_scan),
            sweep.event_valid.eq(P.event_valid & is_sweep),
            move.event_valid.eq(P.event_valid & is_move),
            scan.event_type.eq(P.event_type), sweep.event_type.eq(P.event_type),
            move.event_type.eq(P.event_type),
            scan.event_addr.eq(P.event_addr), sweep.event_addr.eq(P.event_addr),
            move.event_addr.eq(P.event_addr),
            scan.event_data.eq(P.event_data), sweep.event_data.eq(P.event_data),
            move.event_data.eq(P.event_data),
            scan.event_tag.eq(P.event_tag), sweep.event_tag.eq(P.event_tag),
            move.event_tag.eq(P.event_tag),
            scan.event_epoch.eq(P.event_epoch), sweep.event_epoch.eq(P.event_epoch),
            move.event_epoch.eq(P.event_epoch),
            scan.event_seq.eq(P.event_seq), sweep.event_seq.eq(P.event_seq),
            move.event_seq.eq(P.event_seq),
            P.event_ready.eq(
                (is_scan & scan.event_ready) |
                (is_sweep & sweep.event_ready) |
                (is_move & move.event_ready)
            ),
            scan.flush.eq(P.flush), sweep.flush.eq(P.flush), move.flush.eq(P.flush),
            scan.flush_epoch.eq(P.flush_epoch), sweep.flush_epoch.eq(P.flush_epoch),
            move.flush_epoch.eq(P.flush_epoch),
        ]

        # Epoch filtering
        scan_ok = Signal(); sweep_ok = Signal(); move_ok = Signal()
        m.d.comb += [
            scan_ok.eq(scan.result_valid & (scan.result_epoch == P.current_epoch)),
            sweep_ok.eq(sweep.result_valid & (sweep.result_epoch == P.current_epoch)),
            move_ok.eq(move.result_valid & (move.result_epoch == P.current_epoch)),
        ]

        # Multi-output dispatch: each sub-pipeline result goes to a specific port.
        # For NP >= 3, each type gets its own port (scan→port0, sweep→port1, move→port2).
        # For NP = 2, scan→port0, sweep+move round-robin on port1.
        # For NP = 1, all→port0 (legacy mode, equivalent to GCEventPipelineSeparated).

        # Port routing signals
        for p in range(NP):
            port_valid = Signal()
            port_type = Signal(2); port_data = Signal(32)
            port_tag = Signal(8); port_epoch = Signal(8); port_seq = Signal(2)

            if NP >= 4 and p >= 3:
                # Extra ports: round-robin across all types
                prr = Signal(); m.d.sync += prr.eq(prr + 1)
                src3 = Mux(prr == 0, scan_ok, Mux(prr == 1, sweep_ok, 0))
                m.d.comb += [
                    port_valid.eq(scan_ok | sweep_ok | move_ok),
                    port_type.eq(Mux(scan_ok, 0, Mux(sweep_ok, 1, 2))),
                    port_data.eq(Mux(scan_ok, scan.result_data, Mux(sweep_ok, sweep.result_data, move.result_data))),
                    port_tag.eq(Mux(scan_ok, scan.result_tag, Mux(sweep_ok, sweep.result_tag, move.result_tag))),
                    port_epoch.eq(Mux(scan_ok, scan.result_epoch, Mux(sweep_ok, sweep.result_epoch, move.result_epoch))),
                    port_seq.eq(Mux(scan_ok, scan.result_seq, Mux(sweep_ok, sweep.result_seq, move.result_seq))),
                    scan.result_ready.eq(scan.result_ready | (P.rsp_ready[p] & scan_ok & (prr == 0))),
                    sweep.result_ready.eq(sweep.result_ready | (P.rsp_ready[p] & sweep_ok & (prr == 1))),
                    move.result_ready.eq(move.result_ready | (P.rsp_ready[p] & move_ok)),
                ]

            if NP >= 3 and p < 3:
                # One port per sub-pipeline (up to 3)
                src_stage = [scan, sweep, move][p]
                src_ok = [scan_ok, sweep_ok, move_ok][p]
                m.d.comb += [
                    port_valid.eq(src_ok),
                    port_type.eq(p),
                    port_data.eq(src_stage.result_data),
                    port_tag.eq(src_stage.result_tag),
                    port_epoch.eq(src_stage.result_epoch),
                    port_seq.eq(src_stage.result_seq),
                    src_stage.result_ready.eq(P.rsp_ready[p] & src_ok),
                ]
            elif NP == 2:
                # Port 0: SCAN. Port 1: SWEEP + MOVE (round-robin)
                if p == 0:
                    m.d.comb += [
                        port_valid.eq(scan_ok),
                        port_type.eq(EVT_SCAN),
                        port_data.eq(scan.result_data),
                        port_tag.eq(scan.result_tag),
                        port_epoch.eq(scan.result_epoch),
                        port_seq.eq(scan.result_seq),
                        scan.result_ready.eq(P.rsp_ready[0] & scan_ok),
                    ]
                else:
                    rr_bit = Signal(); m.d.sync += rr_bit.eq(~rr_bit)
                    both_ready = Signal(); m.d.comb += both_ready.eq(sweep_ok & move_ok)
                    pick_sweep = Signal()
                    m.d.comb += pick_sweep.eq(Mux(both_ready, rr_bit, sweep_ok))
                    m.d.comb += [
                        port_valid.eq(sweep_ok | move_ok),
                        port_type.eq(Mux(sweep_ok & (pick_sweep | ~move_ok), EVT_SWEEP, EVT_MOVE)),
                        port_data.eq(Mux(sweep_ok & (pick_sweep | ~move_ok), sweep.result_data, move.result_data)),
                        port_tag.eq(Mux(sweep_ok & (pick_sweep | ~move_ok), sweep.result_tag, move.result_tag)),
                        port_epoch.eq(Mux(sweep_ok & (pick_sweep | ~move_ok), sweep.result_epoch, move.result_epoch)),
                        port_seq.eq(Mux(sweep_ok & (pick_sweep | ~move_ok), sweep.result_seq, move.result_seq)),
                        sweep.result_ready.eq(P.rsp_ready[1] & port_valid & sweep_ok & pick_sweep),
                        move.result_ready.eq(P.rsp_ready[1] & port_valid & move_ok & ~(sweep_ok & pick_sweep)),
                    ]
            else:  # NP == 1 — fallback to sequential
                rr_prio = Signal()
                m.d.comb += [
                    rr_prio.eq(Mux(scan_ok, 0, Mux(sweep_ok, 1, 2))),
                    port_valid.eq(scan_ok | sweep_ok | move_ok),
                    port_type.eq(Mux(scan_ok, EVT_SCAN, Mux(sweep_ok, EVT_SWEEP, EVT_MOVE))),
                    port_data.eq(Mux(scan_ok, scan.result_data, Mux(sweep_ok, sweep.result_data, move.result_data))),
                    port_tag.eq(Mux(scan_ok, scan.result_tag, Mux(sweep_ok, sweep.result_tag, move.result_tag))),
                    port_epoch.eq(Mux(scan_ok, scan.result_epoch, Mux(sweep_ok, sweep.result_epoch, move.result_epoch))),
                    port_seq.eq(Mux(scan_ok, scan.result_seq, Mux(sweep_ok, sweep.result_seq, move.result_seq))),
                    scan.result_ready.eq(P.rsp_ready[0] & scan_ok),
                    sweep.result_ready.eq(P.rsp_ready[0] & sweep_ok & ~scan_ok),
                    move.result_ready.eq(P.rsp_ready[0] & move_ok & ~scan_ok & ~sweep_ok),
                ]

            m.d.comb += [
                P.rsp_valid[p].eq(port_valid),
                P.rsp_type[p].eq(port_type),
                P.rsp_data[p].eq(port_data),
                P.rsp_tag[p].eq(port_tag),
                P.rsp_epoch[p].eq(port_epoch),
                P.rsp_seq[p].eq(port_seq),
            ]

        m.d.comb += P.busy.eq(scan.busy | sweep.busy | move.busy)
        return m
