# rtl/jasper_gc_coherent_access.py
# CoherentAccess v0.1 — coherent load/store latency model.
# NOT a full coherence protocol. Models hit/miss latency, backpressure,
# and basic read/write semantics. No MOESI, no snoop, no invalidation.
from amaranth import *
import math


class CoherentAccess(Elaboratable):
    """CoherentAccess v0.1 — coherent load/store latency model.

    Read path: coherent read -> hit/miss -> hit_latency / miss_latency -> read_data.
    Write path: coherent store -> store_latency -> OK (or UNSUPPORTED if disabled).
    No-loss: every accepted request produces exactly one response.
    Backpressure: queue full -> req_ready=0; response holds when rsp_ready=0.
    """
    def __init__(self, *,
                 line_size=64,
                 hit_latency=2,
                 miss_latency=5,
                 store_latency=1,
                 queue_depth=4,
                 hit_mask=0b1010,
                 hit_mask_width=4,
                 enable_write=True,
                 enable_error_injection=False,
                 fault_tag=None,
                 addr_width=32,
                 data_width=32,
                 tag_width=16,
                 epoch_width=8,
                 size_width=4,
                 region_id_width=8,
                 flags_width=8):
        self.line_size = line_size
        self.hit_latency = max(1, hit_latency)
        self.miss_latency = max(1, miss_latency)
        self.store_latency = max(1, store_latency)
        self.queue_depth = max(1, queue_depth)
        self.hit_mask = hit_mask
        self.hit_mask_width = hit_mask_width
        self.enable_write = enable_write
        self.enable_error_injection = enable_error_injection
        self.fault_tag = fault_tag
        self.addr_width = addr_width
        self.data_width = data_width
        self.tag_width = tag_width
        self.epoch_width = epoch_width
        self._lsb = int(math.log2(line_size))
        self._idx_w = max(1, int(math.ceil(math.log2(hit_mask_width))))
        self._max_lat = max(self.hit_latency, self.miss_latency, self.store_latency)

        self.req_valid = Signal()
        self.req_ready = Signal()
        self.req_is_write = Signal()
        self.req_addr = Signal(addr_width)
        self.req_write_data = Signal(data_width)
        self.req_size = Signal(size_width)
        self.req_tag = Signal(tag_width)
        self.req_epoch = Signal(epoch_width)
        self.req_region_id = Signal(region_id_width)
        self.req_flags = Signal(flags_width)

        self.rsp_valid = Signal()
        self.rsp_ready = Signal()
        self.rsp_read_data = Signal(data_width)
        self.rsp_tag = Signal(tag_width)
        self.rsp_epoch = Signal(epoch_width)
        self.rsp_status = Signal(3)  # 0=OK .. 5=UNSUPPORTED
        self.rsp_error = Signal()
        self.rsp_hit = Signal()

    def elaborate(self, platform):
        m = Module()
        QD = self.queue_depth
        AW = self.addr_width
        DW = self.data_width
        TW = self.tag_width
        EW = self.epoch_width
        ML = self._max_lat

        # ── Request Queue (FIFO) ──────────────────────────────────────
        q_valid = Array([Signal() for _ in range(QD)])
        q_is_write = Array([Signal() for _ in range(QD)])
        q_addr = Array([Signal(AW) for _ in range(QD)])
        q_write_data = Array([Signal(DW) for _ in range(QD)])
        q_tag = Array([Signal(TW) for _ in range(QD)])
        q_epoch = Array([Signal(EW) for _ in range(QD)])
        q_head = Signal(range(QD), init=0)
        q_tail = Signal(range(QD), init=0)
        q_cnt = Signal(range(QD + 1), init=0)

        push = Signal()
        m.d.comb += push.eq(self.req_valid & (q_cnt != QD))
        m.d.comb += self.req_ready.eq(q_cnt != QD)

        # ── Active / Latency Counter (declared early, used by bypass logic) ─
        state_acting = Signal(init=0)
        lat_cnt = Signal(range(ML + 1), init=0)
        active_is_write = Signal()
        active_hit = Signal()
        active_tag = Signal(TW)
        active_epoch = Signal(EW)

        # ── Bypass / Dequeue ──────────────────────────────────────────
        # done: response consumed this cycle
        done = Signal()
        m.d.comb += done.eq(
            state_acting & (lat_cnt == 0) & self.rsp_ready)

        # Pipeline can accept new request when idle or response consumed this cycle
        can_accept = Signal()
        m.d.comb += can_accept.eq(~state_acting | done)

        # Bypass: request goes directly to pipeline when:
        #   queue empty, pipeline can accept, not in blocking response
        bypass = Signal()
        m.d.comb += bypass.eq(
            push & (q_cnt == 0) & can_accept & (~self.rsp_valid | done))

        # Dequeue: bypass OR queue has data AND pipeline can accept AND (not responding or consumed)
        dequeue = Signal()
        m.d.comb += dequeue.eq(
            bypass | ((q_cnt != 0) & can_accept & (~self.rsp_valid | done)))

        next_req = Signal()
        m.d.comb += next_req.eq(dequeue)

        # ── Hit/Miss + Target Latency from source address ─────────────
        deq_addr = Signal(AW)
        m.d.comb += deq_addr.eq(Mux(bypass, self.req_addr, q_addr[q_head]))

        deq_is_write = Signal()
        m.d.comb += deq_is_write.eq(
            Mux(bypass, self.req_is_write, q_is_write[q_head]))

        line_idx = Signal(range(self.hit_mask_width))
        m.d.comb += line_idx.eq(
            deq_addr[self._lsb:self._lsb + self._idx_w])

        deq_hit = Signal()
        hit_expr = 0
        for i in range(self.hit_mask_width):
            hit_expr = Mux(line_idx == i,
                           (self.hit_mask >> i) & 1, hit_expr)
        m.d.comb += deq_hit.eq(hit_expr)

        deq_target = Signal(range(ML + 1))
        m.d.comb += deq_target.eq(
            Mux(deq_is_write, self.store_latency,
            Mux(deq_hit, self.hit_latency, self.miss_latency)))

        deq_tag = Signal(TW)
        m.d.comb += deq_tag.eq(Mux(bypass, self.req_tag, q_tag[q_head]))
        deq_epoch = Signal(EW)
        m.d.comb += deq_epoch.eq(
            Mux(bypass, self.req_epoch, q_epoch[q_head]))

        # ── State Machine: state_acting + lat_cnt updates ─────────────
        # state_acting: next_req dominates, else cleared on done, else hold
        m.d.sync += state_acting.eq(
            Mux(next_req, 1,
            Mux(done, 0,
            state_acting)))

        # lat_cnt: set from deq_target on next_req; decrement when active+counting; hold
        m.d.sync += lat_cnt.eq(
            Mux(next_req, Mux(deq_target == 0, 0, deq_target - 1),
            Mux(state_acting & (lat_cnt != 0), lat_cnt - 1,
            lat_cnt)))

        # Active registers: latch on next_req
        with m.If(next_req):
            m.d.sync += [
                active_is_write.eq(deq_is_write),
                active_hit.eq(deq_hit),
                active_tag.eq(deq_tag),
                active_epoch.eq(deq_epoch),
            ]

        # ── Queue push (only when not bypassing) ──────────────────────
        with m.If(push & ~bypass):
            m.d.sync += [
                q_is_write[q_tail].eq(self.req_is_write),
                q_addr[q_tail].eq(self.req_addr),
                q_write_data[q_tail].eq(self.req_write_data),
                q_tag[q_tail].eq(self.req_tag),
                q_epoch[q_tail].eq(self.req_epoch),
                q_valid[q_tail].eq(1),
                q_tail.eq(Mux(q_tail == QD - 1, 0, q_tail + 1)),
            ]

        # ── Queue dequeue (q_head advance, only when not bypassing) ───
        with m.If(next_req & ~bypass):
            m.d.sync += [
                q_valid[q_head].eq(0),
                q_head.eq(Mux(q_head == QD - 1, 0, q_head + 1)),
            ]

        # ── q_cnt: push+1, dequeue-1, bypass=0 net ────────────────────
        with m.If(push & ~bypass & ~(next_req & ~bypass)):
            m.d.sync += q_cnt.eq(q_cnt + 1)
        with m.Elif(~push & (next_req & ~bypass)):
            m.d.sync += q_cnt.eq(q_cnt - 1)

        # ── Response output ───────────────────────────────────────────
        m.d.comb += self.rsp_valid.eq(state_acting & (lat_cnt == 0))

        m.d.comb += [
            self.rsp_read_data.eq(Mux(active_is_write, 0, 0xCAFE)),
            self.rsp_tag.eq(active_tag),
            self.rsp_epoch.eq(active_epoch),
            self.rsp_hit.eq(active_hit),
        ]

        if self.enable_error_injection and self.fault_tag is not None:
            needs_fault = Signal()
            m.d.comb += needs_fault.eq(active_tag == self.fault_tag)
            rsp_stat_expr = Mux(needs_fault, 4, 0)
            if not self.enable_write:
                rsp_stat_expr = Mux(
                    needs_fault, 4,
                    Mux(active_is_write, 5, 0))
        else:
            rsp_stat_expr = 0
            if not self.enable_write:
                rsp_stat_expr = Mux(active_is_write, 5, 0)

        m.d.comb += self.rsp_status.eq(rsp_stat_expr)
        m.d.comb += self.rsp_error.eq(self.rsp_status >= 2)

        return m
