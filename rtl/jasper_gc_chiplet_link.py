# rtl/jasper_gc_chiplet_link.py
# ChipletLink model — configurable die-to-die link latency/backpressure model.
from amaranth import *


class ChipletLink(Elaboratable):
    """ChipletLink — configurable die-to-die link latency model.

    Models a chiplet interconnect with:
    - Forward link latency pipe (elastic pipeline, depth = link_latency)
    - Remote endpoint queue (FIFO, depth = queue_depth)
    - Return link latency pipe (elastic pipeline, depth = link_latency)
    - Simple (ready/valid) or credit-based flow control
    - Optional LFSR-based error injection
    - MemoryAccess-compatible primary interface.
    """
    def __init__(self, *,
                 link_latency=5,
                 link_width=1,
                 queue_depth=4,
                 mode="simple",
                 credit_return_latency=3,
                 max_credits=4,
                 error_rate=0,
                 num_lanes=1,
                 ber_rate=0,
                 training_cycles=0,
                 serdes_delay=0):
        self.link_latency = link_latency
        self.link_width = link_width
        self.queue_depth = queue_depth
        self.mode = mode
        self.credit_return_latency = credit_return_latency
        self.max_credits = max_credits
        self.error_rate = error_rate
        self.num_lanes = num_lanes
        self.ber_rate = ber_rate
        self.training_cycles = training_cycles
        self.serdes_delay = serdes_delay

        # Primary interface (MemoryAccess-compatible)
        self.req_valid = Signal()
        self.req_ready = Signal()
        self.req_addr = Signal(32)
        self.req_tag = Signal(16)
        self.req_is_write = Signal()

        self.rsp_valid = Signal()
        self.rsp_ready = Signal()
        self.rsp_tag = Signal(16)
        self.rsp_data = Signal(32)
        self.rsp_error = Signal()

        # Debug signals
        self.dbg_link_busy = Signal()
        maxc = max(max_credits, 1) if mode == "credit" else 1
        self.dbg_credits = Signal(range(maxc + 1))
        self.dbg_queue_level = Signal(range(queue_depth + 1))
        self.dbg_link_training = Signal()
        self.dbg_link_ready = Signal()
        self.dbg_lane_skew = Signal(range(num_lanes))
        self.dbg_bit_errors = Signal(16)

    def elaborate(self, platform):
        m = Module()
        L = self.link_latency
        Q = self.queue_depth

        # ── Forward Pipe (elastic pipeline, depth L) ───────────────
        fv = [Signal() for _ in range(L)]
        fa = [Signal(32) for _ in range(L)]
        ft = [Signal(16) for _ in range(L)]
        fw = [Signal() for _ in range(L)]

        # ── Remote Queue (FIFO, depth Q) ──────────────────────────
        qv = Array([Signal() for _ in range(Q)])
        qa = Array([Signal(32) for _ in range(Q)])
        qt = Array([Signal(16) for _ in range(Q)])
        qw = Array([Signal() for _ in range(Q)])
        qh = Signal(range(Q), init=0)
        qtl = Signal(range(Q), init=0)
        qc = Signal(range(Q + 1), init=0)

        # ── Response Pipe (elastic pipeline, depth L) ─────────────
        rv = [Signal() for _ in range(L)]
        rt = [Signal(16) for _ in range(L)]
        re = [Signal() for _ in range(L)]

        # ── Remote queue pop signal (declared early for credit) ───
        rq_pop = Signal()

        # ── Debug ─────────────────────────────────────────────────
        m.d.comb += self.dbg_link_busy.eq(fv[0] if L > 0 else 0)
        m.d.comb += self.dbg_queue_level.eq(qc)

        # ── Credit mode ───────────────────────────────────────────
        if self.mode == "credit":
            cr = Signal(range(self.max_credits + 1), init=self.max_credits)
            m.d.comb += self.dbg_credits.eq(cr)
            cr_pipe = [Signal() for _ in range(self.credit_return_latency)]
            for i in range(self.credit_return_latency):
                if i == 0:
                    m.d.sync += cr_pipe[0].eq(rq_pop)
                else:
                    m.d.sync += cr_pipe[i].eq(cr_pipe[i-1])
            credit_return = Signal()
            if self.credit_return_latency > 0:
                m.d.comb += credit_return.eq(
                    cr_pipe[self.credit_return_latency - 1])
            else:
                m.d.comb += credit_return.eq(rq_pop)
        else:
            cr = Signal(range(1), init=0)
            m.d.comb += self.dbg_credits.eq(0)
            credit_return = Signal(0)

        # ── Elastic pipeline: forward pipe ready signals ──────────
        fwd_ready = [Signal() for _ in range(L)]
        for i in range(L - 1, -1, -1):
            if i == L - 1:
                m.d.comb += fwd_ready[i].eq(~fv[i] | (qc != Q))
            else:
                m.d.comb += fwd_ready[i].eq(~fv[i] | fwd_ready[i + 1])

        # ── PHY: link training ─────────────────────────────────────
        training = Signal(init=1 if self.training_cycles > 0 else 0)
        train_cnt = Signal(range(max(self.training_cycles, 1)), init=0)
        link_up = Signal(init=1 if self.training_cycles == 0 else 0)
        if self.training_cycles > 0:
            m.d.comb += self.dbg_link_training.eq(training)
            m.d.comb += self.dbg_link_ready.eq(link_up)
            with m.If(training):
                m.d.sync += train_cnt.eq(train_cnt + 1)
                with m.If(train_cnt == self.training_cycles - 1):
                    m.d.sync += training.eq(0)
                    m.d.sync += link_up.eq(1)
        else:
            m.d.comb += self.dbg_link_training.eq(0)
            m.d.comb += self.dbg_link_ready.eq(1)

        # ── PHY: lane skew ─────────────────────────────────────────
        lane_phase = Signal(range(self.num_lanes), init=0)
        lane_skew_valid = Signal()
        m.d.comb += self.dbg_lane_skew.eq(lane_phase)
        if self.num_lanes > 1:
            m.d.sync += lane_phase.eq(
                Mux(lane_phase == self.num_lanes - 1, 0, lane_phase + 1))

        # ── PHY: lane-based accept gating ──────────────────────────
        phy_ready = fwd_ready[0]
        if self.num_lanes > 1:
            m.d.comb += lane_skew_valid.eq(
                Mux(lane_phase == 0, fwd_ready[0],
                Mux(lane_phase == 1, fwd_ready[0] & fwd_ready[0],
                    fwd_ready[0])))

        # ── PHY: serdes delay (extra latency on top of link_latency)
        serdes_cnt = Signal(range(max(self.serdes_delay + 1, 1)), init=0)
        serdes_active = Signal(init=0)

        # ── Request acceptance ─────────────────────────────────────
        lane_ready = phy_ready if self.num_lanes <= 1 else lane_skew_valid
        link_ready = lane_ready & link_up
        if self.mode == "simple":
            m.d.comb += self.req_ready.eq(link_ready)
        else:
            m.d.comb += self.req_ready.eq((cr > 0) & link_ready)

        accept = Signal()
        m.d.comb += accept.eq(self.req_valid & self.req_ready)

        # ── Credit counter update ─────────────────────────────────
        if self.mode == "credit":
            m.d.sync += cr.eq(
                Mux(accept & credit_return, cr,
                Mux(accept, cr - 1,
                Mux(credit_return, cr + 1,
                    cr))))

        # ── Forward pipe stage updates ────────────────────────────
        for i in range(L):
            upstream_valid = accept if i == 0 else fv[i - 1]
            downstream_ready = fwd_ready[i + 1] if i < L - 1 else (qc != Q)
            gets = upstream_valid & fwd_ready[i]
            advances = fv[i] & downstream_ready
            m.d.sync += fv[i].eq(gets | (fv[i] & ~advances))
            with m.If(gets):
                if i == 0:
                    m.d.sync += [
                        fa[0].eq(self.req_addr),
                        ft[0].eq(self.req_tag),
                        fw[0].eq(self.req_is_write),
                    ]
                else:
                    m.d.sync += [
                        fa[i].eq(fa[i - 1]),
                        ft[i].eq(ft[i - 1]),
                        fw[i].eq(fw[i - 1]),
                    ]

        # ── Remote queue push / pop ───────────────────────────────
        push_rq = Signal()
        m.d.comb += push_rq.eq(fv[L - 1] & (qc != Q))

        m.d.comb += rq_pop.eq((qc != 0) & ~rv[0])

        with m.If(push_rq):
            m.d.sync += [
                qa[qtl].eq(fa[L - 1]),
                qt[qtl].eq(ft[L - 1]),
                qw[qtl].eq(fw[L - 1]),
                qv[qtl].eq(1),
                qtl.eq(Mux(qtl == Q - 1, 0, qtl + 1)),
            ]

        with m.If(rq_pop):
            m.d.sync += [
                qv[qh].eq(0),
                qh.eq(Mux(qh == Q - 1, 0, qh + 1)),
            ]

        m.d.sync += qc.eq(
            Mux(push_rq & rq_pop, qc,
            Mux(push_rq, qc + 1,
            Mux(rq_pop, qc - 1,
                qc))))

        # ── LFSR for error injection ──────────────────────────────
        if self.error_rate > 0:
            lfsr = Signal(8, init=1)
            m.d.sync += lfsr.eq(Cat(
                lfsr[0] ^ lfsr[2] ^ lfsr[3] ^ lfsr[4],
                lfsr[0], lfsr[1], lfsr[2],
                lfsr[3], lfsr[4], lfsr[5], lfsr[6],
            ))
            error_hit = Signal()
            m.d.comb += error_hit.eq(lfsr < self.error_rate)
        else:
            error_hit = Signal(0)

        # ── PHY: BER-based bit error counter ───────────────────────
        ber_cnt = Signal(16, init=0)
        m.d.comb += self.dbg_bit_errors.eq(ber_cnt)
        if self.ber_rate > 0:
            ber_lfsr = Signal(8, init=0xAA)
            m.d.sync += ber_lfsr.eq(Cat(
                ber_lfsr[0] ^ ber_lfsr[2] ^ ber_lfsr[3],
                ber_lfsr[0], ber_lfsr[1], ber_lfsr[2],
                ber_lfsr[3], ber_lfsr[4], ber_lfsr[5], ber_lfsr[6],
            ))
            with m.If(rq_pop & (ber_lfsr < self.ber_rate)):
                m.d.sync += ber_cnt.eq(ber_cnt + 1)

        # ── Elastic pipeline: response pipe ready signals ─────────
        rsp_ready_p = [Signal() for _ in range(L)]
        for i in range(L - 1, -1, -1):
            if i == L - 1:
                m.d.comb += rsp_ready_p[i].eq(~rv[i] | self.rsp_ready)
            else:
                m.d.comb += rsp_ready_p[i].eq(~rv[i] | rsp_ready_p[i + 1])

        # ── Response pipe stage updates ───────────────────────────
        for i in range(L):
            upstream_valid = rq_pop if i == 0 else rv[i - 1]
            downstream_ready = rsp_ready_p[i + 1] if i < L - 1 else self.rsp_ready
            gets = upstream_valid & rsp_ready_p[i]
            advances = rv[i] & downstream_ready
            m.d.sync += rv[i].eq(gets | (rv[i] & ~advances))
            with m.If(gets):
                if i == 0:
                    m.d.sync += rt[0].eq(qt[qh])
                    if self.error_rate > 0:
                        m.d.sync += re[0].eq(error_hit)
                    else:
                        m.d.sync += re[0].eq(0)
                else:
                    m.d.sync += [
                        rt[i].eq(rt[i - 1]),
                        re[i].eq(re[i - 1]),
                    ]

        # ── Response output ───────────────────────────────────────
        m.d.comb += [
            self.rsp_valid.eq(rv[L - 1] if L > 0 else 0),
            self.rsp_tag.eq(rt[L - 1]),
            self.rsp_data.eq(0xDEADBEEF),
            self.rsp_error.eq(re[L - 1] if L > 0 else 0),
        ]

        return m
