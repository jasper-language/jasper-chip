# rtl/gc_backend_merge.py
# Multi-backend dispatch + merge: 将事件分发到多个 backend 并合并结果
from amaranth import *
from rtl.gc_backend_event import GCBackendEventRecord


class BackendMergeSingle(Elaboratable):
    """Single 实现: 单 backend 直通 (backend_count=1).

    与当前单 backend 行为完全一致.
    """
    def __init__(self, data_width=32, tag_width=8, backend_count=1):
        self.data_width = data_width
        self.tag_width = tag_width
        self.backend_count = backend_count

        self.event_valid = Signal()
        self.event_ready = Signal()
        self.event_addr = Signal(32)
        self.event_tag = Signal(tag_width)
        self.event_source = Signal(8)

        self.result_valid = Signal()
        self.result_ready = Signal()
        self.result_data = Signal(data_width)
        self.result_tag = Signal(tag_width)

        self.backend_busy = Signal(backend_count)
        self.dispatch_policy = Signal(2)
        self.merge_policy = Signal(2)

        self.input_event = GCBackendEventRecord()
        self.output_event = GCBackendEventRecord()

    def elaborate(self, platform):
        m = Module()
        occ = Signal(reset=0)
        r_data = Signal(32)
        r_tag = Signal(self.tag_width)

        m.d.comb += [
            self.event_ready.eq(~occ | (occ & self.result_ready)),
            self.result_valid.eq(occ),
            self.result_data.eq(r_data),
            self.result_tag.eq(r_tag),
            self.backend_busy[0].eq(occ),
        ]

        with m.If(self.event_valid & self.event_ready):
            m.d.sync += [
                occ.eq(1),
                r_data.eq(self.event_addr),
                r_tag.eq(self.event_tag),
            ]
        with m.Elif(self.result_valid & self.result_ready):
            m.d.sync += occ.eq(0)
        m.d.comb += [
            self.input_event.fields["address"].eq(self.event_addr),
            self.input_event.fields["data"].eq(self.event_addr),
            self.input_event.fields["event_id"].eq(self.event_tag),
            self.input_event.fields["core_id"].eq(self.event_source),
            self.input_event.valid.eq(self.event_valid),
        ]
        for name in list(self.input_event.fields.keys()):
            if name != "backend_id":
                m.d.comb += self.output_event.fields[name].eq(self.input_event.fields[name])
        m.d.comb += [
            self.output_event.valid.eq(self.input_event.valid),
            self.input_event.ready.eq(self.output_event.ready),
        ]
        return m


class BackendMergeMulti(Elaboratable):
    """Multi 实现 with pipelined merge stage.

    分发策略 (dispatch_policy):
      0: round_robin — 轮询分发
      1: hash_lsb   — 地址 LSB hash 分发
      2: broadcast  — 广播到所有 backend
      3: affinity   — 按 event_source 亲和性分发

    合并策略 (merge_policy):
      0: none     — 直通不合并 (适用于单结果)
      1: ordered  — 按 tag 顺序合并
      2: priority — 按 source 优先级合并

    新增流水线合并 (merge_policy=1,2):
      - 每 lane 深度 4 的结果 FIFO, 含 head/tail/count 指针
      - 2 级合并流水线: Stage 0 预选 2 候选, Stage 1 输出
      - 向后兼容: merge_policy=0 保持原直通行为
    """
    DISPATCH_ROUND_ROBIN = 0
    DISPATCH_HASH_LSB    = 1
    DISPATCH_BROADCAST   = 2
    DISPATCH_AFFINITY    = 3

    MERGE_NONE     = 0
    MERGE_ORDERED  = 1
    MERGE_PRIORITY = 2

    FIFO_DEPTH = 4

    def __init__(self, data_width=32, tag_width=8, backend_count=4,
                 source_width=8):
        self.data_width = data_width
        self.tag_width = tag_width
        self.backend_count = backend_count
        self.source_width = source_width

        self.event_valid = Signal()
        self.event_ready = Signal()
        self.event_addr = Signal(32)
        self.event_tag = Signal(tag_width)
        self.event_source = Signal(source_width)

        self.result_valid = Signal()
        self.result_ready = Signal()
        self.result_data = Signal(data_width)
        self.result_tag = Signal(tag_width)

        self.backend_busy = Signal(backend_count)
        self.dispatch_policy = Signal(2)
        self.merge_policy = Signal(2)

        self.input_events = [GCBackendEventRecord() for _ in range(backend_count)]
        self.output_event = GCBackendEventRecord()

        self.backend_result_valid = [Signal() for _ in range(backend_count)]
        self.backend_result_data = [Signal(data_width) for _ in range(backend_count)]
        self.backend_result_tag = [Signal(tag_width) for _ in range(backend_count)]
        self.backend_result_source = [Signal(source_width) for _ in range(backend_count)]
        self.backend_result_epoch = [Signal(8) for _ in range(backend_count)]
        self.backend_result_sequence = [Signal(8) for _ in range(backend_count)]
        self.backend_result_merge_domain = [Signal(4) for _ in range(backend_count)]
        self.backend_result_ready = [Signal() for _ in range(backend_count)]

    def elaborate(self, platform):
        m = Module()
        bc = self.backend_count
        FD = self.FIFO_DEPTH

        # ── Dispatch Logic (unchanged from original) ──────────────
        target_width = max(bc - 1, 0).bit_length() or 1
        rr_ptr = Signal(range(bc))
        target = Signal(target_width)

        busy_bits = Signal(bc)
        for i in range(bc):
            m.d.comb += busy_bits[i].eq(self.backend_busy[i])

        any_busy = Signal()
        m.d.comb += any_busy.eq(busy_bits.any())

        with m.Switch(self.dispatch_policy):
            with m.Case(self.DISPATCH_ROUND_ROBIN):
                m.d.comb += target.eq(rr_ptr)
                with m.If(self.event_valid):
                    m.d.sync += rr_ptr.eq(Mux(rr_ptr == bc - 1, 0, rr_ptr + 1))
            with m.Case(self.DISPATCH_HASH_LSB):
                m.d.comb += target.eq(self.event_addr[:target_width])
            with m.Case(self.DISPATCH_BROADCAST):
                m.d.comb += target.eq(0)
            with m.Case(self.DISPATCH_AFFINITY):
                m.d.comb += target.eq(self.event_source[:target_width])

        target_busy = Signal()
        m.d.comb += target_busy.eq(busy_bits.bit_select(target, 1))
        m.d.comb += self.event_ready.eq(~target_busy | ~self.event_valid)

        # ── Per-Lane Result FIFOs (depth = FD) ────────────────────
        # Each FIFO entry stores: data, tag, source, epoch, sequence,
        #                         merge_domain, event_type

        lane_fifo_data = Array(Array(Signal(self.data_width) for _ in range(FD)) for _ in range(bc))
        lane_fifo_tag = Array(Array(Signal(self.tag_width) for _ in range(FD)) for _ in range(bc))
        lane_fifo_source = Array(Array(Signal(self.source_width) for _ in range(FD)) for _ in range(bc))
        lane_fifo_epoch = Array(Array(Signal(8) for _ in range(FD)) for _ in range(bc))
        lane_fifo_sequence = Array(Array(Signal(8) for _ in range(FD)) for _ in range(bc))
        lane_fifo_merge_domain = Array(Array(Signal(4) for _ in range(FD)) for _ in range(bc))
        lane_fifo_event_type = Array(Array(Signal(3) for _ in range(FD)) for _ in range(bc))

        lane_head = Array([Signal(range(FD)) for _ in range(bc)])
        lane_tail = Array([Signal(range(FD)) for _ in range(bc)])
        lane_count = Array([Signal(range(FD + 1)) for _ in range(bc)])

        lane_empty = Array([Signal() for _ in range(bc)])
        lane_full = Array([Signal() for _ in range(bc)])

        for i in range(bc):
            m.d.comb += lane_empty[i].eq(lane_count[i] == 0)
            m.d.comb += lane_full[i].eq(lane_count[i] == FD)
            m.d.comb += self.backend_result_ready[i].eq(~lane_full[i])

            can_write = self.backend_result_valid[i] & ~lane_full[i]
            with m.If(can_write):
                m.d.sync += [
                    lane_fifo_data[i][lane_tail[i]].eq(self.backend_result_data[i]),
                    lane_fifo_tag[i][lane_tail[i]].eq(self.backend_result_tag[i]),
                    lane_fifo_source[i][lane_tail[i]].eq(self.backend_result_source[i]),
                    lane_fifo_epoch[i][lane_tail[i]].eq(self.backend_result_epoch[i]),
                    lane_fifo_sequence[i][lane_tail[i]].eq(self.backend_result_sequence[i]),
                    lane_fifo_merge_domain[i][lane_tail[i]].eq(self.backend_result_merge_domain[i]),
                    lane_fifo_event_type[i][lane_tail[i]].eq(self.backend_result_tag[i][:3]),
                ]
                m.d.sync += lane_tail[i].eq(Mux(lane_tail[i] == FD - 1, 0, lane_tail[i] + 1))
                m.d.sync += lane_count[i].eq(lane_count[i] + 1)

        # ── Pipelined Merge (2-stage) ────────────────────────────
        # Stage 0: pre-select candidates into 2-deep prefetch buffer
        # Stage 1: output from prefetch buffer to consumer

        p_valid = Array([Signal() for _ in range(2)])
        p_lane = Array([Signal(range(bc)) for _ in range(2)])
        p_data = Array([Signal(self.data_width) for _ in range(2)])
        p_tag = Array([Signal(self.tag_width) for _ in range(2)])
        p_source = Array([Signal(self.source_width) for _ in range(2)])
        p_epoch = Array([Signal(8) for _ in range(2)])
        p_sequence = Array([Signal(8) for _ in range(2)])
        p_merge_domain = Array([Signal(4) for _ in range(2)])
        p_event_type = Array([Signal(3) for _ in range(2)])

        merge_rr = Signal(range(bc))

        # Pre-compute priority scan for each possible start position
        # fill_found_for_start[r] / fill_lane_for_start[r] =
        #   first non-empty lane beginning at lane r (wrapping)
        fill_found_for_start = [Signal() for _ in range(bc)]
        fill_lane_for_start = [Signal(range(bc)) for _ in range(bc)]

        for r in range(bc):
            ff = [Signal() for _ in range(bc)]
            fl = [Signal(range(bc)) for _ in range(bc)]
            for step in range(bc):
                idx = (r + step) % bc
                if step == 0:
                    m.d.comb += ff[0].eq(~lane_empty[idx])
                    m.d.comb += fl[0].eq(idx)
                else:
                    taken = ff[step - 1]
                    m.d.comb += ff[step].eq(taken | (~lane_empty[idx] & ~taken))
                    m.d.comb += fl[step].eq(Mux(taken, fl[step - 1], idx))
            m.d.comb += fill_found_for_start[r].eq(ff[bc - 1])
            m.d.comb += fill_lane_for_start[r].eq(fl[bc - 1])

        # Select based on merge_rr (single comb driver via mux tree)
        fill_found = Signal()
        fill_lane = Signal(range(bc))
        mux_found = fill_found_for_start[bc - 1]
        mux_lane = fill_lane_for_start[bc - 1]
        for r in range(bc - 2, -1, -1):
            mux_found = Mux(merge_rr == r, fill_found_for_start[r], mux_found)
            mux_lane = Mux(merge_rr == r, fill_lane_for_start[r], mux_lane)
        m.d.comb += fill_found.eq(mux_found)
        m.d.comb += fill_lane.eq(mux_lane)

        # Pipeline control signals
        pipe_valid = Signal()
        pipe_consume = Signal()
        pipe_consume_lane = Signal(range(bc))

        m.d.comb += pipe_valid.eq(p_valid[0] | p_valid[1])

        # Stage 1: sync updates (shift + pop on consume)
        with m.If(pipe_consume):
            with m.If(p_valid[0]):
                m.d.sync += [
                    p_valid[0].eq(p_valid[1]),
                    p_lane[0].eq(p_lane[1]),
                    p_data[0].eq(p_data[1]),
                    p_tag[0].eq(p_tag[1]),
                    p_source[0].eq(p_source[1]),
                    p_epoch[0].eq(p_epoch[1]),
                    p_sequence[0].eq(p_sequence[1]),
                    p_merge_domain[0].eq(p_merge_domain[1]),
                    p_event_type[0].eq(p_event_type[1]),
                    p_valid[1].eq(0),
                ]
            with m.Elif(p_valid[1]):
                m.d.sync += p_valid[1].eq(0)

        # FIFO pop for consumed lane
        for i in range(bc):
            with m.If(pipe_consume & (pipe_consume_lane == i)):
                m.d.sync += lane_head[i].eq(Mux(lane_head[i] == FD - 1, 0, lane_head[i] + 1))
                m.d.sync += lane_count[i].eq(lane_count[i] - 1)

        # Advance merge_rr past consumed lane
        with m.If(pipe_consume):
            m.d.sync += merge_rr.eq(Mux(pipe_consume_lane == bc - 1, 0, pipe_consume_lane + 1))

        # Stage 0: fill one empty slot per cycle
        fill_needed = Signal()
        fill_slot = Signal()
        m.d.comb += fill_needed.eq(~p_valid[0] | ~p_valid[1])
        m.d.comb += fill_slot.eq(Mux(p_valid[0], 1, 0))

        with m.If(fill_needed & fill_found & ~(pipe_consume & (fill_lane == pipe_consume_lane))):
            m.d.sync += [
                p_valid[fill_slot].eq(1),
                p_lane[fill_slot].eq(fill_lane),
                p_data[fill_slot].eq(lane_fifo_data[fill_lane][lane_head[fill_lane]]),
                p_tag[fill_slot].eq(lane_fifo_tag[fill_lane][lane_head[fill_lane]]),
                p_source[fill_slot].eq(lane_fifo_source[fill_lane][lane_head[fill_lane]]),
                p_epoch[fill_slot].eq(lane_fifo_epoch[fill_lane][lane_head[fill_lane]]),
                p_sequence[fill_slot].eq(lane_fifo_sequence[fill_lane][lane_head[fill_lane]]),
                p_merge_domain[fill_slot].eq(lane_fifo_merge_domain[fill_lane][lane_head[fill_lane]]),
                p_event_type[fill_slot].eq(lane_fifo_event_type[fill_lane][lane_head[fill_lane]]),
                merge_rr.eq(Mux(fill_lane == bc - 1, 0, fill_lane + 1)),
            ]

        # ── Output mux: passthrough vs pipelined merge ───────────
        with m.Switch(self.merge_policy):
            with m.Case(self.MERGE_NONE):
                m.d.comb += [
                    self.result_valid.eq(self.event_valid & self.event_ready),
                    self.result_data.eq(self.event_addr),
                    self.result_tag.eq(self.event_tag),
                    pipe_consume.eq(0),
                    pipe_consume_lane.eq(0),
                ]
            with m.Case(self.MERGE_ORDERED, self.MERGE_PRIORITY):
                m.d.comb += [
                    self.result_valid.eq(pipe_valid),
                    pipe_consume.eq(self.result_ready & pipe_valid),
                ]
                with m.If(p_valid[0]):
                    m.d.comb += [
                        self.result_data.eq(p_data[0]),
                        self.result_tag.eq(p_tag[0]),
                        pipe_consume_lane.eq(p_lane[0]),
                    ]
                with m.Elif(p_valid[1]):
                    m.d.comb += [
                        self.result_data.eq(p_data[1]),
                        self.result_tag.eq(p_tag[1]),
                        pipe_consume_lane.eq(p_lane[1]),
                    ]
                with m.Else():
                    m.d.comb += [
                        self.result_data.eq(0),
                        self.result_tag.eq(0),
                        pipe_consume_lane.eq(0),
                    ]

        # ── GCBackendEvent connections ────────────────────────────
        for i in range(bc):
            m.d.comb += [
                self.input_events[i].fields["address"].eq(self.event_addr),
                self.input_events[i].fields["data"].eq(self.event_addr),
                self.input_events[i].fields["event_id"].eq(self.event_tag),
                self.input_events[i].fields["core_id"].eq(self.event_source),
                self.input_events[i].fields["epoch"].eq(0),
                self.input_events[i].fields["sequence"].eq(0),
                self.input_events[i].fields["merge_domain"].eq(0),
                self.input_events[i].valid.eq(self.event_valid),
            ]

        m.d.comb += self.output_event.valid.eq(self.result_valid)
        m.d.comb += self.output_event.fields["event_type"].eq(self.event_tag[:3])

        with m.Switch(self.merge_policy):
            with m.Case(self.MERGE_NONE):
                m.d.comb += [
                    self.output_event.fields["data"].eq(self.event_addr),
                    self.output_event.fields["event_id"].eq(self.event_tag),
                    self.output_event.fields["core_id"].eq(self.event_source),
                    self.output_event.fields["epoch"].eq(0),
                    self.output_event.fields["sequence"].eq(0),
                    self.output_event.fields["merge_domain"].eq(0),
                ]
            with m.Case(self.MERGE_ORDERED, self.MERGE_PRIORITY):
                m.d.comb += [
                    self.output_event.fields["data"].eq(p_data[0] | p_data[1]),
                    self.output_event.fields["event_id"].eq(p_tag[0] | p_tag[1]),
                    self.output_event.fields["core_id"].eq(p_source[0] | p_source[1]),
                    self.output_event.fields["epoch"].eq(p_epoch[0] | p_epoch[1]),
                    self.output_event.fields["sequence"].eq(p_sequence[0] | p_sequence[1]),
                    self.output_event.fields["merge_domain"].eq(p_merge_domain[0] | p_merge_domain[1]),
                ]

        return m


def create_backend_merge(impl: str, **kwargs):
    if impl == "single":
        return BackendMergeSingle(**kwargs)
    elif impl == "multi":
        return BackendMergeMulti(**kwargs)
    else:
        raise ValueError(f"Unknown backend_merge_impl: {impl}")
