# rtl/gc_wide_2lane.py
# 2-Lane Wide Backend — RTL prototype for Server/Gateway tile.
# 2 inputs, 2 pipeline lanes, 2 metadata banks, 2 forwarding banks, 2 outputs.
from amaranth import *
from rtl.gc_event_pipeline import GCEventPipelineSeparated, EVT_SCAN, EVT_SWEEP, EVT_MOVE
from rtl.gc_metadata_pipeline import MetadataCachePipelined
from rtl.gc_forwarding_table import ForwardingTableBankedPipeline


class LanePipeline(Elaboratable):
    """One lane of the 2-lane backend: event pipe + meta cache + forwarding table."""
    def __init__(self, lane_id=0):
        self.lane_id = lane_id
        self.in_valid = Signal()
        self.in_ready = Signal()
        self.in_event_type = Signal(2)
        self.in_addr = Signal(32)
        self.in_data = Signal(32)
        self.in_tag = Signal(8)
        self.in_epoch = Signal(8)
        self.in_seq = Signal(2)
        self.flush = Signal()
        self.flush_epoch = Signal(8)
        self.current_epoch = Signal(8)

        self.out_valid = Signal()
        self.out_ready = Signal()
        self.out_data = Signal(32)
        self.out_tag = Signal(8)
        self.out_epoch = Signal(8)
        self.out_seq = Signal(2)
        self.out_merge_domain = Signal(4)
        self.busy = Signal()
        self.fill_ready = Signal()
        self.fill_valid = Signal()
        self.fill_addr = Signal(32)
        self.fill_data = Signal(32)

    def elaborate(self, platform):
        m = Module()
        pipe = GCEventPipelineSeparated()
        meta = MetadataCachePipelined(cache_size=1024, ways=2, access_granularity=32)
        ft = ForwardingTableBankedPipeline(bank_count=1, entries_per_bank=8, chase_depth=2)
        m.submodules.pipe = pipe; m.submodules.meta = meta; m.submodules.ft = ft

        # Event pipeline: route to SCAN sub-pipeline (simplified: all events go through pipe)
        m.d.comb += [
            pipe.event_valid.eq(self.in_valid),
            self.in_ready.eq(pipe.event_ready),
            pipe.event_type.eq(self.in_event_type),
            pipe.event_addr.eq(self.in_addr),
            pipe.event_data.eq(self.in_data),
            pipe.event_tag.eq(self.in_tag),
            pipe.event_epoch.eq(self.in_epoch),
            pipe.event_seq.eq(self.in_seq),
            pipe.flush.eq(self.flush), pipe.flush_epoch.eq(self.flush_epoch),
            pipe.current_epoch.eq(self.current_epoch),
        ]

        # Pipe → Meta (pass event_tag through meta's input_event for preservation)
        m.d.comb += [
            meta.request_valid.eq(pipe.result_valid),
            pipe.result_ready.eq(meta.request_ready),
            meta.request_addr.eq(pipe.result_data),
            meta.input_event.fields["event_id"].eq(self.in_tag),
            meta.input_event.fields["epoch"].eq(self.in_epoch),
        ]

        # Meta → FT (pass event_id as query_tag)
        m.d.comb += [
            ft.query_valid.eq(meta.rsp_valid),
            meta.rsp_ready.eq(ft.query_ready),
            ft.query_old_ptr.eq(meta.rsp_data),
            ft.query_tag.eq(meta.output_event.fields["event_id"][:8]),
        ]

        # FT → output
        m.d.comb += [
            self.out_valid.eq(ft.rsp_valid),
            ft.rsp_ready.eq(self.out_ready),
            self.out_data.eq(ft.rsp_new_ptr),
            self.out_tag.eq(ft.rsp_tag),
            self.busy.eq(pipe.busy | meta.busy | ft.busy),
            self.fill_valid.eq(meta.fill_valid),
            meta.fill_ready.eq(self.fill_ready),
            meta.fill_data.eq(self.fill_data),
            self.fill_addr.eq(meta.fill_addr),
        ]
        # Output epoch/seq passthrough from pipe (not preserved through meta/ft)
        m.d.comb += [
            self.out_epoch.eq(pipe.result_epoch),
            self.out_seq.eq(pipe.result_seq),
            self.out_merge_domain.eq(self.lane_id),
        ]
        return m


class Wide2LaneBackend(Elaboratable):
    """2-lane wide backend: 2 inputs, 2 lanes, 2 outputs with commit queue."""
    def __init__(self):
        # Input ports
        self.in0_valid = Signal(); self.in0_ready = Signal()
        self.in0_type = Signal(2); self.in0_addr = Signal(32)
        self.in0_data = Signal(32); self.in0_tag = Signal(8)
        self.in0_epoch = Signal(8); self.in0_seq = Signal(2)
        self.in1_valid = Signal(); self.in1_ready = Signal()
        self.in1_type = Signal(2); self.in1_addr = Signal(32)
        self.in1_data = Signal(32); self.in1_tag = Signal(8)
        self.in1_epoch = Signal(8); self.in1_seq = Signal(2)
        self.flush = Signal(); self.flush_epoch = Signal(8)
        self.current_epoch = Signal(8)

        # Output ports (commit queue → 2 outputs)
        self.out0_valid = Signal(); self.out0_ready = Signal()
        self.out0_data = Signal(32); self.out0_tag = Signal(8)
        self.out0_epoch = Signal(8); self.out0_seq = Signal(2)
        self.out0_domain = Signal(4)
        self.out1_valid = Signal(); self.out1_ready = Signal()
        self.out1_data = Signal(32); self.out1_tag = Signal(8)
        self.out1_epoch = Signal(8); self.out1_seq = Signal(2)
        self.out1_domain = Signal(4)
        self.busy = Signal()
        self.fill_ready = Signal()
        self.fill_valid = Signal()
        self.fill_addr = Signal(32)
        self.fill_data = Signal(32)

    def elaborate(self, platform):
        m = Module(); P = self

        lane0 = LanePipeline(lane_id=0); lane1 = LanePipeline(lane_id=1)
        m.submodules.lane0 = lane0; m.submodules.lane1 = lane1

        # Dispatch: addr LSB selects lane
        lane0_sel = Signal(); lane1_sel = Signal()
        m.d.comb += [
            lane0_sel.eq(P.in0_addr[0] == 0),
            lane1_sel.eq(P.in0_addr[0] == 1),
        ]

        # Lane 0 input
        m.d.comb += [
            lane0.in_valid.eq(P.in0_valid & lane0_sel),
            P.in0_ready.eq(Mux(lane0_sel, lane0.in_ready, lane1.in_ready)),
            lane0.in_event_type.eq(P.in0_type),
            lane0.in_addr.eq(P.in0_addr),
            lane0.in_data.eq(P.in0_data),
            lane0.in_tag.eq(P.in0_tag),
            lane0.in_epoch.eq(P.in0_epoch),
            lane0.in_seq.eq(P.in0_seq),
        ]

        # Lane 1 input (second port)
        m.d.comb += [
            lane1.in_valid.eq(P.in1_valid),
            P.in1_ready.eq(lane1.in_ready),
            lane1.in_event_type.eq(P.in1_type),
            lane1.in_addr.eq(P.in1_addr),
            lane1.in_data.eq(P.in1_data),
            lane1.in_tag.eq(P.in1_tag),
            lane1.in_epoch.eq(P.in1_epoch),
            lane1.in_seq.eq(P.in1_seq),
        ]

        # Common control
        m.d.comb += lane0.flush.eq(P.flush)
        m.d.comb += lane1.flush.eq(P.flush)
        m.d.comb += lane0.flush_epoch.eq(P.flush_epoch)
        m.d.comb += lane1.flush_epoch.eq(P.flush_epoch)
        m.d.comb += lane0.current_epoch.eq(P.current_epoch)
        m.d.comb += lane1.current_epoch.eq(P.current_epoch)

        # ── Commit queue: collect lane results, output in order ──
        # Queue entries: {data, tag, epoch, seq, domain, valid, lane_id}
        QD = 8
        q_data = Array([Signal(32) for _ in range(QD)])
        q_tag = Array([Signal(8) for _ in range(QD)])
        q_epoch = Array([Signal(8) for _ in range(QD)])
        q_seq = Array([Signal(8) for _ in range(QD)])
        q_domain = Array([Signal(4) for _ in range(QD)])
        q_valid = Array([Signal() for _ in range(QD)])
        q_lane = Array([Signal() for _ in range(QD)])
        q_head = Signal(range(QD), reset=0)
        q_tail = Signal(range(QD), reset=0)
        q_count = Signal(range(QD + 1), reset=0)
        q_full = Signal(); q_empty = Signal()
        m.d.comb += [q_full.eq(q_count == QD), q_empty.eq(q_count == 0)]

        # Push from either lane
        push0 = Signal(); push1 = Signal()
        m.d.comb += [
            push0.eq(lane0.out_valid & ~q_full),
            push1.eq(lane1.out_valid & ~q_full),
            lane0.out_ready.eq(~q_full),
            lane1.out_ready.eq(~q_full),
        ]
        with m.If(push0):
            m.d.sync += [
                q_data[q_tail].eq(lane0.out_data),
                q_tag[q_tail].eq(lane0.out_tag),
                q_epoch[q_tail].eq(lane0.out_epoch),
                q_seq[q_tail].eq(lane0.out_seq),
                q_domain[q_tail].eq(lane0.out_merge_domain),
                q_valid[q_tail].eq(1),
                q_lane[q_tail].eq(0),
                q_tail.eq(Mux(q_tail == QD - 1, 0, q_tail + 1)),
            ]
        with m.If(push1):
            m.d.sync += [
                q_data[q_tail].eq(lane1.out_data),
                q_tag[q_tail].eq(lane1.out_tag),
                q_epoch[q_tail].eq(lane1.out_epoch),
                q_seq[q_tail].eq(lane1.out_seq),
                q_domain[q_tail].eq(lane1.out_merge_domain),
                q_valid[q_tail].eq(1),
                q_lane[q_tail].eq(1),
                q_tail.eq(Mux(q_tail == QD - 1, 0, q_tail + 1)),
            ]

        # Pop: commit queue emits two results per cycle at most
        pop_en = Signal(2)
        for p in range(2):
            out_valid_sig = [P.out0_valid, P.out1_valid][p]
            out_ready_sig = [P.out0_ready, P.out1_ready][p]
            out_data_sig = [P.out0_data, P.out1_data][p]
            out_tag_sig = [P.out0_tag, P.out1_tag][p]
            out_epoch_sig = [P.out0_epoch, P.out1_epoch][p]
            out_seq_sig = [P.out0_seq, P.out1_seq][p]
            out_domain_sig = [P.out0_domain, P.out1_domain][p]

            head_valid = Signal(); m.d.comb += head_valid.eq(q_valid[q_head])
            m.d.comb += [
                out_valid_sig.eq(~q_empty & head_valid),
                out_data_sig.eq(Mux(~q_empty & head_valid, q_data[q_head], 0)),
                out_tag_sig.eq(Mux(~q_empty & head_valid, q_tag[q_head], 0)),
                out_epoch_sig.eq(Mux(~q_empty & head_valid, q_epoch[q_head], 0)),
                out_seq_sig.eq(Mux(~q_empty & head_valid, q_seq[q_head], 0)),
                out_domain_sig.eq(Mux(~q_empty & head_valid, q_domain[q_head], 0)),
            ]
            pop_this = Signal()
            m.d.comb += pop_this.eq(out_valid_sig & out_ready_sig)
            m.d.comb += pop_en[p].eq(pop_this)

            with m.If(pop_this):
                m.d.sync += [
                    q_valid[q_head].eq(0),
                    q_head.eq(Mux(q_head == QD - 1, 0, q_head + 1)),
                ]

        # Count update
        push_any = Signal(); m.d.comb += push_any.eq(push0 | push1)
        pop_any = Signal(); m.d.comb += pop_any.eq(pop_en[0] | pop_en[1])
        with m.If(push_any & ~pop_any):
            m.d.sync += q_count.eq(q_count + 1)
        with m.If(pop_any & ~push_any):
            m.d.sync += q_count.eq(q_count - 1)

        # Fill handling: OR from both lanes
        m.d.comb += [
            P.fill_valid.eq(lane0.fill_valid | lane1.fill_valid),
            lane0.fill_ready.eq(P.fill_ready),
            lane1.fill_ready.eq(P.fill_ready),
            lane0.fill_data.eq(P.fill_data),
            lane1.fill_data.eq(P.fill_data),
            P.fill_addr.eq(Mux(lane0.fill_valid, lane0.fill_addr, lane1.fill_addr)),
            P.busy.eq(lane0.busy | lane1.busy | (~q_empty)),
        ]
        return m
