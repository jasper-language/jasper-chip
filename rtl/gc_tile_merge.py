# rtl/gc_tile_merge.py
# N-way tile merge: gathers results from N 2L tiles, emits ordered stream.
from amaranth import *


class TileMerge(Elaboratable):
    """Merge results from N 2L tiles into a single ordered output stream.

    Each tile has 2 output ports. Results are collected into a commit queue
    and emitted in (epoch, sequence) order per merge_domain.
    """
    def __init__(self, tile_count=2, queue_depth=16):
        self.tile_count = tile_count
        self.queue_depth = queue_depth
        # Tile input ports: each tile has 2 outputs
        self.in_valid = [[Signal() for _ in range(2)] for _ in range(tile_count)]
        self.in_ready = [[Signal() for _ in range(2)] for _ in range(tile_count)]
        self.in_data = [[Signal(32) for _ in range(2)] for _ in range(tile_count)]
        self.in_tag = [[Signal(8) for _ in range(2)] for _ in range(tile_count)]
        self.in_epoch = [[Signal(8) for _ in range(2)] for _ in range(tile_count)]
        self.in_seq = [[Signal(8) for _ in range(2)] for _ in range(tile_count)]
        self.in_domain = [[Signal(4) for _ in range(2)] for _ in range(tile_count)]
        # Single output
        self.out_valid = Signal(); self.out_ready = Signal()
        self.out_data = Signal(32); self.out_tag = Signal(8)
        self.out_epoch = Signal(8); self.out_seq = Signal(8)
        self.out_domain = Signal(4)
        self.busy = Signal()

    def elaborate(self, platform):
        m = Module(); P = self; TC = P.tile_count; QD = P.queue_depth

        # Unified commit queue
        q_data = Array([Signal(32) for _ in range(QD)])
        q_tag = Array([Signal(8) for _ in range(QD)])
        q_epoch = Array([Signal(8) for _ in range(QD)])
        q_seq = Array([Signal(8) for _ in range(QD)])
        q_domain = Array([Signal(4) for _ in range(QD)])
        q_valid = Array([Signal() for _ in range(QD)])
        q_head = Signal(range(QD), reset=0)
        q_tail = Signal(range(QD), reset=0)
        q_count = Signal(range(QD + 1), reset=0)
        q_full = Signal(); q_empty = Signal()
        m.d.comb += [q_full.eq(q_count == QD), q_empty.eq(q_count == 0)]

        # Push: round-robin select one input per cycle
        push_sel = Signal(range(TC * 2))
        any_push = Signal()
        m.d.comb += any_push.eq(0)
        for idx in range(TC * 2):
            t = idx // 2; p = idx % 2
            selected = Signal(); m.d.comb += selected.eq(push_sel == idx)
            push = Signal()
            m.d.comb += push.eq(P.in_valid[t][p] & ~q_full & selected)
            m.d.comb += P.in_ready[t][p].eq(push)
            m.d.comb += any_push.eq(any_push | push)
            with m.If(push):
                m.d.sync += [
                    q_data[q_tail].eq(P.in_data[t][p]),
                    q_tag[q_tail].eq(P.in_tag[t][p]),
                    q_epoch[q_tail].eq(P.in_epoch[t][p]),
                    q_seq[q_tail].eq(P.in_seq[t][p]),
                    q_domain[q_tail].eq(P.in_domain[t][p]),
                    q_valid[q_tail].eq(1),
                    q_tail.eq(Mux(q_tail == QD - 1, 0, q_tail + 1)),
                ]
        # Advance push round-robin selector
        with m.If(any_push):
            m.d.sync += push_sel.eq(Mux(push_sel == TC * 2 - 1, 0, push_sel + 1))

        # Pop: emit 1 result/cycle from queue head (in-order)
        head_valid = Signal(); m.d.comb += head_valid.eq(q_valid[q_head])
        m.d.comb += [
            P.out_valid.eq(~q_empty & head_valid),
            P.out_data.eq(Mux(head_valid, q_data[q_head], 0)),
            P.out_tag.eq(Mux(head_valid, q_tag[q_head], 0)),
            P.out_epoch.eq(Mux(head_valid, q_epoch[q_head], 0)),
            P.out_seq.eq(Mux(head_valid, q_seq[q_head], 0)),
            P.out_domain.eq(Mux(head_valid, q_domain[q_head], 0)),
        ]
        pop = Signal(); m.d.comb += pop.eq(P.out_valid & P.out_ready)
        with m.If(pop):
            m.d.sync += [q_valid[q_head].eq(0), q_head.eq(Mux(q_head == QD - 1, 0, q_head + 1))]

        # Count
        with m.If(any_push & ~pop):
            m.d.sync += q_count.eq(q_count + 1)
        with m.If(pop & ~any_push):
            m.d.sync += q_count.eq(q_count - 1)

        m.d.comb += P.busy.eq(~q_empty)
        return m
