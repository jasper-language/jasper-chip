# rtl/gc_l0_forwarding.py
# Per-core L0 Forwarding Cache — small per-core cache for recent old->new forwarding entries
from amaranth import *


class L0ForwardingDisabled(Elaboratable):
    """Always miss — forwards all queries to shared forwarding table (current behavior).

    query_ready=1 always, rsp_valid=query_valid, rsp_hit=0,
    rsp_new_ptr=query_old_ptr (identity), update_ready=1 always.
    """
    def __init__(self):
        self.query_valid = Signal()
        self.query_ready = Signal()
        self.query_old_ptr = Signal(32)

        self.rsp_valid = Signal()
        self.rsp_ready = Signal()
        self.rsp_new_ptr = Signal(32)
        self.rsp_hit = Signal()

        self.update_valid = Signal()
        self.update_ready = Signal()
        self.update_old_ptr = Signal(32)
        self.update_new_ptr = Signal(32)

        self.flush = Signal()

    def elaborate(self, platform):
        m = Module()
        m.d.comb += [
            self.query_ready.eq(1),
            self.rsp_valid.eq(self.query_valid & ~self.flush),
            self.rsp_hit.eq(0),
            self.rsp_new_ptr.eq(self.query_old_ptr),
            self.update_ready.eq(1),
        ]
        return m


class L0ForwardingEnabled(Elaboratable):
    """Small (4-16 entry) direct-mapped forwarding cache.

    On RB query: check L0 first.
    Hit (rsp_hit=1) → rsp_new_ptr carries forwarded pointer, return immediately.
    Miss (rsp_hit=0) → caller queries shared ForwardingTable (GCMvCoProc).

    Update stores old->new mapping at slot index = old_ptr[0:idx_bits].
    Flush clears all valid bits.
    """
    def __init__(self, entries=8):
        assert 4 <= entries <= 16, "entries must be between 4 and 16"
        self.entries = entries
        self.idx_bits = (entries - 1).bit_length()

        self.query_valid = Signal()
        self.query_ready = Signal()
        self.query_old_ptr = Signal(32)

        self.rsp_valid = Signal()
        self.rsp_ready = Signal()
        self.rsp_new_ptr = Signal(32)
        self.rsp_hit = Signal()

        self.update_valid = Signal()
        self.update_ready = Signal()
        self.update_old_ptr = Signal(32)
        self.update_new_ptr = Signal(32)

        self.flush = Signal()

    def elaborate(self, platform):
        m = Module()
        e = self.entries
        ib = self.idx_bits

        v = [Signal(reset=0) for _ in range(e)]
        op = [Signal(32) for _ in range(e)]
        np = [Signal(32) for _ in range(e)]

        q_idx = Signal(ib)
        u_idx = Signal(ib)
        m.d.comb += [
            q_idx.eq(self.query_old_ptr[:ib]),
            u_idx.eq(self.update_old_ptr[:ib]),
        ]

        hit = Signal()
        hit_np = Signal(32)
        m.d.comb += hit.eq(0)
        m.d.comb += hit_np.eq(self.query_old_ptr)

        for i in range(e):
            with m.If(q_idx == i):
                m.d.comb += hit.eq(v[i] & (op[i] == self.query_old_ptr))
                m.d.comb += hit_np.eq(np[i])

        m.d.comb += [
            self.query_ready.eq(1),
            self.rsp_valid.eq(self.query_valid & ~self.flush),
            self.rsp_hit.eq(hit),
            self.rsp_new_ptr.eq(Mux(hit, hit_np, self.query_old_ptr)),
            self.update_ready.eq(1),
        ]

        for i in range(e):
            with m.If(self.flush):
                m.d.sync += v[i].eq(0)
            with m.Elif(self.update_valid & (u_idx == i)):
                m.d.sync += [
                    v[i].eq(1),
                    op[i].eq(self.update_old_ptr),
                    np[i].eq(self.update_new_ptr),
                ]

        return m
