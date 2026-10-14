# rtl/gc_backend_tile.py
# Parameterized backend tile: 1-lane or 2-lane.
# Multi-backend: instantiate N tiles + dispatch + merge.
from amaranth import *
from rtl.gc_event_pipeline import GCEventPipelineSeparated
from rtl.gc_metadata_pipeline import MetadataCachePipelined
from rtl.gc_forwarding_table import ForwardingTableBankedPipeline, FD


class BackendLane(Elaboratable):
    """Single processing lane: event pipe → meta cache → forwarding table."""
    def __init__(self, lane_id=0,
                 metadata_cache_size=1024, metadata_ways=2, metadata_access_granularity=32,
                 metadata_pipeline_depth=8,
                 forwarding_entries=64, forwarding_chase_depth=4,
                 entries_per_bank=32):
        self.lane_id = lane_id
        self.metadata_cache_size = metadata_cache_size
        self.metadata_ways = metadata_ways
        self.metadata_access_granularity = metadata_access_granularity
        self.metadata_pipeline_depth = metadata_pipeline_depth
        self.forwarding_entries = forwarding_entries
        self.forwarding_chase_depth = forwarding_chase_depth
        self.entries_per_bank = entries_per_bank
        self.in_valid = Signal(); self.in_ready = Signal()
        self.in_type = Signal(2); self.in_addr = Signal(32)
        self.in_data = Signal(32); self.in_tag = Signal(8)
        self.in_epoch = Signal(8); self.in_seq = Signal(2)
        self.flush = Signal(); self.flush_epoch = Signal(8)
        self.current_epoch = Signal(8)
        self.out_valid = Signal(); self.out_ready = Signal()
        self.out_data = Signal(32); self.out_tag = Signal(8)
        self.out_epoch = Signal(8); self.out_seq = Signal(2)
        self.out_domain = Signal(4)
        self.busy = Signal()
        self.fill_ready = Signal(); self.fill_valid = Signal()
        self.fill_addr = Signal(32); self.fill_data = Signal(32)

    def elaborate(self, platform):
        m = Module()
        epb = self.entries_per_bank
        bc = max(1, (self.forwarding_entries + epb - 1) // epb)
        pipe = GCEventPipelineSeparated()
        meta = MetadataCachePipelined(
            cache_size=self.metadata_cache_size,
            ways=self.metadata_ways,
            access_granularity=self.metadata_access_granularity,
        )
        ft = ForwardingTableBankedPipeline(
            bank_count=bc,
            entries_per_bank=epb,
            chase_depth=self.forwarding_chase_depth,
        )
        m.submodules.pipe = pipe; m.submodules.meta = meta; m.submodules.ft = ft

        m.d.comb += meta.input_event.fields["event_id"].eq(pipe.result_tag)
        m.d.comb += meta.input_event.fields["epoch"].eq(pipe.result_epoch)
        m.d.comb += meta.input_event.fields["sequence"].eq(pipe.result_seq)

        m.d.comb += ft.query_tag.eq(meta.output_event.fields["event_id"][:8])
        m.d.comb += ft.epoch.eq(self.current_epoch)
        m.d.comb += ft.flush_epoch.eq(self.flush_epoch)

        # Shadow FIFO for epoch/seq (mirrors FT response FIFO depth)
        sf_ep = Array([Signal(8) for _ in range(FD)])
        sf_sq = Array([Signal(2) for _ in range(FD)])
        sf_head = Signal(range(FD), reset=0)
        sf_tail = Signal(range(FD), reset=0)
        sf_cnt = Signal(range(FD + 1), reset=0)
        sf_push = Signal()
        sf_pop = Signal()
        sf_full = Signal()
        m.d.comb += [
            sf_full.eq((sf_cnt == FD) & ~sf_pop),
            sf_push.eq(meta.rsp_valid & ft.query_ready & ~sf_full),
            sf_pop.eq(ft.rsp_valid & self.out_ready),
        ]
        with m.If(sf_push & sf_pop):
            m.d.sync += [
                sf_ep[sf_tail].eq(meta.output_event.fields["epoch"]),
                sf_sq[sf_tail].eq(meta.output_event.fields["sequence"]),
                sf_tail.eq(sf_tail + 1), sf_head.eq(sf_head + 1),
            ]
        with m.Elif(sf_push):
            m.d.sync += [
                sf_ep[sf_tail].eq(meta.output_event.fields["epoch"]),
                sf_sq[sf_tail].eq(meta.output_event.fields["sequence"]),
                sf_tail.eq(sf_tail + 1), sf_cnt.eq(sf_cnt + 1),
            ]
        with m.Elif(sf_pop):
            m.d.sync += [
                sf_head.eq(sf_head + 1), sf_cnt.eq(sf_cnt - 1),
            ]

        m.d.comb += [
            pipe.event_valid.eq(self.in_valid), self.in_ready.eq(pipe.event_ready),
            pipe.event_type.eq(self.in_type), pipe.event_addr.eq(self.in_addr),
            pipe.event_data.eq(self.in_data), pipe.event_tag.eq(self.in_tag),
            pipe.event_epoch.eq(self.in_epoch), pipe.event_seq.eq(self.in_seq),
            pipe.flush.eq(self.flush), pipe.flush_epoch.eq(self.flush_epoch),
            pipe.current_epoch.eq(self.current_epoch),
            meta.request_valid.eq(pipe.result_valid),
            pipe.result_ready.eq(meta.request_ready),
            meta.request_addr.eq(pipe.result_data),
            ft.query_valid.eq(meta.rsp_valid & ~sf_full),
            meta.rsp_ready.eq(ft.query_ready & ~sf_full),
            ft.query_old_ptr.eq(meta.rsp_data),
            self.out_valid.eq(ft.rsp_valid), ft.rsp_ready.eq(self.out_ready),
            self.out_data.eq(ft.rsp_new_ptr), self.out_tag.eq(ft.rsp_tag),
            self.out_epoch.eq(sf_ep[sf_head]), self.out_seq.eq(sf_sq[sf_head]),
            self.out_domain.eq(self.lane_id),
            self.busy.eq(pipe.busy | meta.busy | ft.busy),
            self.fill_valid.eq(meta.fill_valid),
            meta.fill_ready.eq(self.fill_ready),
            meta.fill_data.eq(self.fill_data),
            self.fill_addr.eq(meta.fill_addr),
        ]
        return m


class BackendTile(Elaboratable):
    """Parameterized backend tile: 1-lane or 2-lane.

    lane_count=1: 1.0 evt/cyc (Standard equivalent)
    lane_count=2: 2.0 evt/cyc (Server/Gateway tile)

    Results from both lanes go through a commit queue → 2 output ports.
    """
    def __init__(self, lane_count=1,
                 metadata_cache_size=1024, metadata_ways=2, metadata_access_granularity=32,
                 metadata_pipeline_depth=8,
                 forwarding_entries=64, forwarding_chase_depth=4,
                 entries_per_bank=8):
        self.lane_count = lane_count
        self.metadata_cache_size = metadata_cache_size
        self.metadata_ways = metadata_ways
        self.metadata_access_granularity = metadata_access_granularity
        self.metadata_pipeline_depth = metadata_pipeline_depth
        self.forwarding_entries = forwarding_entries
        self.forwarding_chase_depth = forwarding_chase_depth
        self.entries_per_bank = entries_per_bank
        # Input ports (2 for both modes; unused when lane_count=1)
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
        # Output ports (always 2, lane_count=1 uses only port 0)
        self.out0_valid = Signal(); self.out0_ready = Signal()
        self.out0_data = Signal(32); self.out0_tag = Signal(8)
        self.out0_epoch = Signal(8); self.out0_seq = Signal(2)
        self.out0_domain = Signal(4)
        self.out1_valid = Signal(); self.out1_ready = Signal()
        self.out1_data = Signal(32); self.out1_tag = Signal(8)
        self.out1_epoch = Signal(8); self.out1_seq = Signal(2)
        self.out1_domain = Signal(4)
        self.busy = Signal()
        self.fill_ready = Signal(); self.fill_valid = Signal()
        self.fill_addr = Signal(32); self.fill_data = Signal(32)

    def elaborate(self, platform):
        m = Module(); P = self; LC = P.lane_count
        lanes = [BackendLane(
            lane_id=i,
            metadata_cache_size=self.metadata_cache_size,
            metadata_ways=self.metadata_ways,
            metadata_access_granularity=self.metadata_access_granularity,
            metadata_pipeline_depth=self.metadata_pipeline_depth,
            forwarding_entries=self.forwarding_entries,
            forwarding_chase_depth=self.forwarding_chase_depth,
            entries_per_bank=self.entries_per_bank,
        ) for i in range(self.lane_count)]
        for i, l in enumerate(lanes):
            m.submodules[f"lane_{i}"] = l

        # Lane inputs
        m.d.comb += [
            lanes[0].in_valid.eq(P.in0_valid if LC >= 1 else 0),
            P.in0_ready.eq(lanes[0].in_ready if LC >= 1 else 0),
            lanes[0].in_type.eq(P.in0_type), lanes[0].in_addr.eq(P.in0_addr),
            lanes[0].in_data.eq(P.in0_data), lanes[0].in_tag.eq(P.in0_tag),
            lanes[0].in_epoch.eq(P.in0_epoch), lanes[0].in_seq.eq(P.in0_seq),
        ]
        if LC >= 2:
            m.d.comb += [
                lanes[1].in_valid.eq(P.in1_valid), P.in1_ready.eq(lanes[1].in_ready),
                lanes[1].in_type.eq(P.in1_type), lanes[1].in_addr.eq(P.in1_addr),
                lanes[1].in_data.eq(P.in1_data), lanes[1].in_tag.eq(P.in1_tag),
                lanes[1].in_epoch.eq(P.in1_epoch), lanes[1].in_seq.eq(P.in1_seq),
            ]

        # Common control
        for l in lanes:
            m.d.comb += [
                l.flush.eq(P.flush), l.flush_epoch.eq(P.flush_epoch),
                l.current_epoch.eq(P.current_epoch),
                l.fill_ready.eq(P.fill_ready), l.fill_data.eq(P.fill_data),
            ]

        # Output routing: lane_count=1 uses out0 only; lane_count=2 uses both
        m.d.comb += [
            P.out0_valid.eq(lanes[0].out_valid), lanes[0].out_ready.eq(P.out0_ready),
            P.out0_data.eq(lanes[0].out_data), P.out0_tag.eq(lanes[0].out_tag),
            P.out0_epoch.eq(lanes[0].out_epoch), P.out0_seq.eq(lanes[0].out_seq),
            P.out0_domain.eq(lanes[0].out_domain),
        ]
        if LC >= 2:
            m.d.comb += [
                P.out1_valid.eq(lanes[1].out_valid), lanes[1].out_ready.eq(P.out1_ready),
                P.out1_data.eq(lanes[1].out_data), P.out1_tag.eq(lanes[1].out_tag),
                P.out1_epoch.eq(lanes[1].out_epoch), P.out1_seq.eq(lanes[1].out_seq),
                P.out1_domain.eq(lanes[1].out_domain),
            ]

        fill_v = Const(0); fill_a = Const(0)
        for l in lanes:
            fill_v = fill_v | l.fill_valid
            fill_a = Mux(l.fill_valid, l.fill_addr, fill_a)
        m.d.comb += [
            P.fill_valid.eq(fill_v), P.fill_addr.eq(fill_a),
            P.busy.eq(sum(l.busy for l in lanes) > 0),
        ]
        return m
