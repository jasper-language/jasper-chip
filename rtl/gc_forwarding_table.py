# rtl/gc_forwarding_table.py
# Forwarding Table — 统一接口 + Standard / BankedPipeline 实现
from amaranth import *
from rtl.gc_backend_event import GCBackendEventRecord

FD = 4  # response FIFO depth


def _tree_first(conds, vals, default=0):
    """Binary tree first-match selector.
    Returns (any_hit_expr, selected_value_expr).
    O(N log N) AST nodes vs O(N^2) for linear priority chain.
    """
    n = len(conds)
    if n == 0:
        return 0, default
    if n == 1:
        return conds[0], Mux(conds[0], vals[0], default)
    if n == 2:
        hit = conds[0] | conds[1]
        sel = Mux(conds[0], vals[0], Mux(conds[1], vals[1], default))
        return hit, sel
    mid = n // 2
    hl, sl = _tree_first(conds[:mid], vals[:mid], default)
    hr, sr = _tree_first(conds[mid:], vals[mid:], default)
    return hl | hr, Mux(hl, sl, sr)


# ── ForwardingTableStandard: 多条目 + chase + epoch + rsp_ready ──
class ForwardingTableStandard(Elaboratable):
    """Standard forwarding table with multi-entry, chase, epoch, backpressure.

    与现有 GCMvCoProc 语义等价: map_depth 条 old→new 映射,
    chase_depth 级链式追踪, update_epoch 参与查询有效性判断.
    """
    def __init__(self, map_depth=16, chase_depth=2):
        self.map_depth = map_depth
        self.chase_depth = chase_depth

        self.query_valid = Signal(); self.query_ready = Signal()
        self.query_old_ptr = Signal(32); self.query_tag = Signal(8)

        self.rsp_valid = Signal(); self.rsp_ready = Signal()
        self.rsp_new_ptr = Signal(32); self.rsp_tag = Signal(8); self.rsp_hit = Signal()

        self.update_valid = Signal(); self.update_ready = Signal()
        self.update_old_ptr = Signal(32); self.update_new_ptr = Signal(32)
        self.update_epoch = Signal(8)

        self.epoch = Signal(8); self.flush_epoch = Signal()
        self.busy = Signal(); self.error = Signal()
        self.full = Signal()

        self.input_event = GCBackendEventRecord()
        self.output_event = GCBackendEventRecord()

    def elaborate(self, platform):
        m = Module(); md = self.map_depth; cd = self.chase_depth
        idx_bits = (md - 1).bit_length() if md > 1 else 1

        tbl_v = Array([Signal(reset=0) for _ in range(md)])
        tbl_o = Array([Signal(32) for _ in range(md)])
        tbl_n = Array([Signal(32) for _ in range(md)])
        tbl_e = Array([Signal(8) for _ in range(md)])
        tbl_rr = Signal(range(md), reset=0)

        # Response FIFO (depth FD = 4)
        fifo_head = Signal(range(FD), reset=0)
        fifo_tail = Signal(range(FD), reset=0)
        fifo_cnt = Signal(range(FD + 1), reset=0)
        f_hit = Array([Signal() for _ in range(FD)])
        f_new = Array([Signal(32) for _ in range(FD)])
        f_tag = Array([Signal(8) for _ in range(FD)])
        f_old = Array([Signal(32) for _ in range(FD)])
        f_id = Array([Signal(16) for _ in range(FD)])
        f_core = Array([Signal(8) for _ in range(FD)])

        fifo_full = Signal(); fifo_empty = Signal()
        m.d.comb += [
            fifo_full.eq(fifo_cnt == FD),
            fifo_empty.eq(fifo_cnt == 0),
        ]

        # Full detection: all entries valid
        full_expr = Const(1)
        for i in range(md):
            full_expr = full_expr & tbl_v[i]
        m.d.comb += self.full.eq(full_expr)

        # Update path (backpressure when full)
        m.d.comb += self.update_ready.eq(~self.full)
        with m.If(self.update_valid & self.update_ready):
            for i in range(md):
                with m.If(tbl_rr == i):
                    m.d.sync += [tbl_v[i].eq(1), tbl_o[i].eq(self.update_old_ptr),
                                 tbl_n[i].eq(self.update_new_ptr), tbl_e[i].eq(self.update_epoch)]
            m.d.sync += tbl_rr.eq(Mux(tbl_rr == md - 1, 0, tbl_rr + 1))

        # Query path: priority match over all entries, filter by epoch
        cond_list = []
        for i in range(md):
            ek = Signal(); m.d.comb += ek.eq(tbl_e[i] == self.epoch)
            cond_list.append(tbl_v[i] & ek & (self.query_old_ptr == tbl_o[i]))
        vals = [tbl_n[i] for i in range(md)]
        hit_v, np_v = _tree_first(cond_list, vals)
        chase_v = np_v
        for _ in range(cd - 1):
            ch_conds = []
            for i in range(md):
                ek = Signal(); m.d.comb += ek.eq(tbl_e[i] == self.epoch)
                ch_conds.append(tbl_v[i] & ek & (chase_v == tbl_o[i]))
            _, nxt = _tree_first(ch_conds, vals, default=chase_v)
            chase_v = nxt

        # Response output from FIFO head
        m.d.comb += [
            self.query_ready.eq(~fifo_full),
            self.rsp_valid.eq(~fifo_empty),
            self.rsp_hit.eq(Mux(~fifo_empty, f_hit[fifo_head], 0)),
            self.rsp_new_ptr.eq(Mux(~fifo_empty, f_new[fifo_head], 0)),
            self.rsp_tag.eq(Mux(~fifo_empty, f_tag[fifo_head], 0)),
        ]

        push = self.query_valid & self.query_ready
        pop = self.rsp_valid & self.rsp_ready

        with m.If(push & pop):
            m.d.sync += [
                f_hit[fifo_tail].eq(hit_v),
                f_new[fifo_tail].eq(Mux(hit_v, chase_v, self.query_old_ptr)),
                f_tag[fifo_tail].eq(self.query_tag),
                f_old[fifo_tail].eq(self.query_old_ptr),
                f_id[fifo_tail].eq(Mux(self.input_event.valid, self.input_event.fields["event_id"], self.query_tag)),
                f_core[fifo_tail].eq(self.input_event.fields["core_id"]),
                fifo_tail.eq(fifo_tail + 1),
                fifo_head.eq(fifo_head + 1),
            ]
        with m.Elif(push):
            m.d.sync += [
                f_hit[fifo_tail].eq(hit_v),
                f_new[fifo_tail].eq(Mux(hit_v, chase_v, self.query_old_ptr)),
                f_tag[fifo_tail].eq(self.query_tag),
                f_old[fifo_tail].eq(self.query_old_ptr),
                f_id[fifo_tail].eq(Mux(self.input_event.valid, self.input_event.fields["event_id"], self.query_tag)),
                f_core[fifo_tail].eq(self.input_event.fields["core_id"]),
                fifo_tail.eq(fifo_tail + 1),
                fifo_cnt.eq(fifo_cnt + 1),
            ]
        with m.Elif(pop):
            m.d.sync += [
                fifo_head.eq(fifo_head + 1),
                fifo_cnt.eq(fifo_cnt - 1),
            ]

        # Flush: clear entries whose epoch matches flush_epoch
        with m.If(self.flush_epoch):
            for i in range(md):
                m.d.sync += tbl_v[i].eq(tbl_v[i] & (tbl_e[i] != self.flush_epoch))

        m.d.comb += [self.busy.eq(~fifo_empty),
                     self.error.eq(self.update_valid & self.full)]

        # ── GCBackendEvent I/O bridge ──
        m.d.comb += [
            self.input_event.ready.eq(self.query_ready),
            self.output_event.valid.eq(self.rsp_valid),
            self.output_event.ready.eq(self.rsp_ready),
            self.output_event.fields["old_ptr"].eq(Mux(~fifo_empty, f_old[fifo_head], 0)),
            self.output_event.fields["new_ptr"].eq(self.rsp_new_ptr),
            self.output_event.fields["event_id"].eq(Mux(~fifo_empty, f_id[fifo_head], 0)),
            self.output_event.fields["core_id"].eq(Mux(~fifo_empty, f_core[fifo_head], 0)),
            self.output_event.fields["epoch"].eq(self.epoch),
        ]
        return m


# ── ForwardingTableBankedPipeline: 真实 multi-bank + pipeline ──
class ForwardingTableBankedPipeline(Elaboratable):
    """Banked + pipelined forwarding table.

    bank_count=1: 等价 Standard (统一接口, 统一行为)
    bank_count>1: 按 old_ptr hash 分发到 N 个 bank,
                  每 bank 独立 lookup, 结果合并后返回.
    """
    def __init__(self, bank_count=1, entries_per_bank=8, chase_depth=2):
        self.bank_count = bank_count
        self.entries_per_bank = entries_per_bank
        self.chase_depth = chase_depth

        self.query_valid = Signal(); self.query_ready = Signal()
        self.query_old_ptr = Signal(32); self.query_tag = Signal(8)
        self.rsp_valid = Signal(); self.rsp_ready = Signal()
        self.rsp_new_ptr = Signal(32); self.rsp_tag = Signal(8); self.rsp_hit = Signal()
        self.update_valid = Signal(); self.update_ready = Signal()
        self.update_old_ptr = Signal(32); self.update_new_ptr = Signal(32)
        self.update_epoch = Signal(8)
        self.epoch = Signal(8); self.flush_epoch = Signal()
        self.busy = Signal(); self.error = Signal()
        self.full = Signal()

        self.input_event = GCBackendEventRecord()
        self.output_event = GCBackendEventRecord()

    def elaborate(self, platform):
        m = Module(); bk = self.bank_count; epb = self.entries_per_bank
        ib = (epb - 1).bit_length() if epb > 1 else 1

        if bk == 1:
            # Single bank: multi-entry Array, identical to Standard
            tbl_v = Array([Signal(reset=0) for _ in range(epb)])
            tbl_o = Array([Signal(32) for _ in range(epb)])
            tbl_n = Array([Signal(32) for _ in range(epb)])
            tbl_e = Array([Signal(8) for _ in range(epb)])
            tbl_rr = Signal(range(epb), reset=0)

            # Response FIFO (depth FD = 4)
            fifo_head = Signal(range(FD), reset=0)
            fifo_tail = Signal(range(FD), reset=0)
            fifo_cnt = Signal(range(FD + 1), reset=0)
            f_hit = Array([Signal() for _ in range(FD)])
            f_new = Array([Signal(32) for _ in range(FD)])
            f_tag = Array([Signal(8) for _ in range(FD)])
            f_old = Array([Signal(32) for _ in range(FD)])
            f_id = Array([Signal(16) for _ in range(FD)])
            f_core = Array([Signal(8) for _ in range(FD)])

            fifo_full = Signal(); fifo_empty = Signal()
            m.d.comb += [
                fifo_full.eq(fifo_cnt == FD),
                fifo_empty.eq(fifo_cnt == 0),
            ]

            # Full detection
            full_expr = Const(1)
            for i in range(epb):
                full_expr = full_expr & tbl_v[i]
            m.d.comb += self.full.eq(full_expr)

            m.d.comb += self.update_ready.eq(~self.full)
            with m.If(self.update_valid & self.update_ready):
                for i in range(epb):
                    with m.If(tbl_rr == i):
                        m.d.sync += [tbl_v[i].eq(1), tbl_o[i].eq(self.update_old_ptr),
                                     tbl_n[i].eq(self.update_new_ptr), tbl_e[i].eq(self.update_epoch)]
                m.d.sync += tbl_rr.eq(Mux(tbl_rr == epb - 1, 0, tbl_rr + 1))

            # Priority match (tree-based first-match)
            cond_list = []
            for i in range(epb):
                ek = Signal(); m.d.comb += ek.eq(tbl_e[i] == self.epoch)
                cond_list.append(tbl_v[i] & ek & (self.query_old_ptr == tbl_o[i]))
            vals = [tbl_n[i] for i in range(epb)]
            hv, nv = _tree_first(cond_list, vals)
            chase_v = nv
            for _ in range(self.chase_depth - 1):
                ch_conds = []
                for i in range(epb):
                    ek = Signal(); m.d.comb += ek.eq(tbl_e[i] == self.epoch)
                    ch_conds.append(tbl_v[i] & ek & (chase_v == tbl_o[i]))
                _, nxt = _tree_first(ch_conds, vals, default=chase_v)
                chase_v = nxt

            m.d.comb += [
                self.query_ready.eq(~fifo_full),
                self.rsp_valid.eq(~fifo_empty),
                self.rsp_hit.eq(Mux(~fifo_empty, f_hit[fifo_head], 0)),
                self.rsp_new_ptr.eq(Mux(~fifo_empty, f_new[fifo_head], 0)),
                self.rsp_tag.eq(Mux(~fifo_empty, f_tag[fifo_head], 0)),
            ]

            push = self.query_valid & self.query_ready
            pop = self.rsp_valid & self.rsp_ready

            with m.If(push & pop):
                m.d.sync += [
                    f_hit[fifo_tail].eq(hv),
                    f_new[fifo_tail].eq(Mux(hv, chase_v, self.query_old_ptr)),
                    f_tag[fifo_tail].eq(self.query_tag),
                    f_old[fifo_tail].eq(self.query_old_ptr),
                    f_id[fifo_tail].eq(Mux(self.input_event.valid, self.input_event.fields["event_id"], self.query_tag)),
                    f_core[fifo_tail].eq(self.input_event.fields["core_id"]),
                    fifo_tail.eq(fifo_tail + 1),
                    fifo_head.eq(fifo_head + 1),
                ]
            with m.Elif(push):
                m.d.sync += [
                    f_hit[fifo_tail].eq(hv),
                    f_new[fifo_tail].eq(Mux(hv, chase_v, self.query_old_ptr)),
                    f_tag[fifo_tail].eq(self.query_tag),
                    f_old[fifo_tail].eq(self.query_old_ptr),
                    f_id[fifo_tail].eq(Mux(self.input_event.valid, self.input_event.fields["event_id"], self.query_tag)),
                    f_core[fifo_tail].eq(self.input_event.fields["core_id"]),
                    fifo_tail.eq(fifo_tail + 1),
                    fifo_cnt.eq(fifo_cnt + 1),
                ]
            with m.Elif(pop):
                m.d.sync += [
                    fifo_head.eq(fifo_head + 1),
                    fifo_cnt.eq(fifo_cnt - 1),
                ]

            with m.If(self.flush_epoch):
                for i in range(epb):
                    m.d.sync += tbl_v[i].eq(tbl_v[i] & (tbl_e[i] != self.flush_epoch))
            m.d.comb += [self.busy.eq(~fifo_empty),
                         self.error.eq(self.update_valid & self.full)]

            # ── GCBackendEvent I/O bridge (single bank) ──
            m.d.comb += [
                self.input_event.ready.eq(self.query_ready),
                self.output_event.valid.eq(self.rsp_valid),
                self.output_event.ready.eq(self.rsp_ready),
                self.output_event.fields["old_ptr"].eq(Mux(~fifo_empty, f_old[fifo_head], 0)),
                self.output_event.fields["new_ptr"].eq(self.rsp_new_ptr),
                self.output_event.fields["event_id"].eq(Mux(~fifo_empty, f_id[fifo_head], 0)),
                self.output_event.fields["core_id"].eq(Mux(~fifo_empty, f_core[fifo_head], 0)),
                self.output_event.fields["epoch"].eq(self.epoch),
            ]
            return m

        # Multi-bank: N independent banks, hash → dispatch → merge
        b_bits = (bk - 1).bit_length() if bk > 1 else 1
        q_bank = Signal(b_bits); u_bank = Signal(b_bits)
        m.d.comb += [q_bank.eq(self.query_old_ptr[:b_bits]),
                     u_bank.eq(self.update_old_ptr[:b_bits])]

        # Per-bank state. Use nested Arrays so query/update logic only selects the
        # hashed bank instead of building hit/chase logic for every bank.
        b_v = Array([Array([Signal(reset=0) for _ in range(epb)]) for _ in range(bk)])
        b_o = Array([Array([Signal(32) for _ in range(epb)]) for _ in range(bk)])
        b_n = Array([Array([Signal(32) for _ in range(epb)]) for _ in range(bk)])
        b_e = Array([Array([Signal(8) for _ in range(epb)]) for _ in range(bk)])
        b_rr = Array([Signal(range(epb), reset=0) for _ in range(bk)])

        # Query path: only the hashed bank can contain the queried pointer.
        cond_list = []
        vals = []
        for i in range(epb):
            ek = Signal()
            m.d.comb += ek.eq(b_e[q_bank][i] == self.epoch)
            cond_list.append(b_v[q_bank][i] & ek & (self.query_old_ptr == b_o[q_bank][i]))
            vals.append(b_n[q_bank][i])
        hit_final, new_base = _tree_first(cond_list, vals)
        new_final = new_base
        for _ in range(min(self.chase_depth, 2) - 1):
            ch_conds = []
            for i in range(epb):
                ek = Signal()
                m.d.comb += ek.eq(b_e[q_bank][i] == self.epoch)
                ch_conds.append(b_v[q_bank][i] & ek & (new_final == b_o[q_bank][i]))
            _, nxt = _tree_first(ch_conds, vals, default=new_final)
            new_final = nxt

        # Full only needs to inspect the update target bank.
        full_expr = Const(1)
        for i in range(epb):
            full_expr = full_expr & b_v[u_bank][i]
        m.d.comb += self.full.eq(full_expr)

        # Update (banked)
        with m.If(self.update_valid & self.update_ready):
            for i in range(epb):
                with m.If(b_rr[u_bank] == i):
                    m.d.sync += [
                        b_v[u_bank][i].eq(1),
                        b_o[u_bank][i].eq(self.update_old_ptr),
                        b_n[u_bank][i].eq(self.update_new_ptr),
                        b_e[u_bank][i].eq(self.update_epoch),
                    ]
            m.d.sync += b_rr[u_bank].eq(Mux(b_rr[u_bank] == epb - 1, 0, b_rr[u_bank] + 1))

        # Flush all banks for the target epoch.
        for b in range(bk):
            with m.If(self.flush_epoch):
                for i in range(epb):
                    m.d.sync += b_v[b][i].eq(b_v[b][i] & (b_e[b][i] != self.flush_epoch))

        # Shared response FIFO (depth FD = 4)
        fifo_head = Signal(range(FD), reset=0)
        fifo_tail = Signal(range(FD), reset=0)
        fifo_cnt = Signal(range(FD + 1), reset=0)
        f_hit = Array([Signal() for _ in range(FD)])
        f_new = Array([Signal(32) for _ in range(FD)])
        f_tag = Array([Signal(8) for _ in range(FD)])
        f_old = Array([Signal(32) for _ in range(FD)])
        f_id = Array([Signal(16) for _ in range(FD)])
        f_core = Array([Signal(8) for _ in range(FD)])

        fifo_full = Signal(); fifo_empty = Signal()
        m.d.comb += [
            fifo_full.eq(fifo_cnt == FD),
            fifo_empty.eq(fifo_cnt == 0),
        ]

        m.d.comb += [
            self.update_ready.eq(~self.full),
            self.query_ready.eq(~fifo_full),
            self.rsp_valid.eq(~fifo_empty),
            self.rsp_hit.eq(Mux(~fifo_empty, f_hit[fifo_head], 0)),
            self.rsp_new_ptr.eq(Mux(~fifo_empty, f_new[fifo_head], 0)),
            self.rsp_tag.eq(Mux(~fifo_empty, f_tag[fifo_head], 0)),
        ]

        push = self.query_valid & self.query_ready
        pop = self.rsp_valid & self.rsp_ready

        with m.If(push & pop):
            m.d.sync += [
                f_hit[fifo_tail].eq(hit_final),
                f_new[fifo_tail].eq(Mux(hit_final, new_final, self.query_old_ptr)),
                f_tag[fifo_tail].eq(self.query_tag),
                f_old[fifo_tail].eq(self.query_old_ptr),
                f_id[fifo_tail].eq(Mux(self.input_event.valid, self.input_event.fields["event_id"], self.query_tag)),
                f_core[fifo_tail].eq(self.input_event.fields["core_id"]),
                fifo_tail.eq(fifo_tail + 1),
                fifo_head.eq(fifo_head + 1),
            ]
        with m.Elif(push):
            m.d.sync += [
                f_hit[fifo_tail].eq(hit_final),
                f_new[fifo_tail].eq(Mux(hit_final, new_final, self.query_old_ptr)),
                f_tag[fifo_tail].eq(self.query_tag),
                f_old[fifo_tail].eq(self.query_old_ptr),
                f_id[fifo_tail].eq(Mux(self.input_event.valid, self.input_event.fields["event_id"], self.query_tag)),
                f_core[fifo_tail].eq(self.input_event.fields["core_id"]),
                fifo_tail.eq(fifo_tail + 1),
                fifo_cnt.eq(fifo_cnt + 1),
            ]
        with m.Elif(pop):
            m.d.sync += [
                fifo_head.eq(fifo_head + 1),
                fifo_cnt.eq(fifo_cnt - 1),
            ]

        m.d.comb += [self.busy.eq(~fifo_empty),
                     self.error.eq(self.update_valid & self.full)]

        # ── GCBackendEvent I/O bridge (multi-bank) ──
        m.d.comb += [
            self.input_event.ready.eq(self.query_ready),
            self.output_event.valid.eq(self.rsp_valid),
            self.output_event.ready.eq(self.rsp_ready),
            self.output_event.fields["old_ptr"].eq(Mux(~fifo_empty, f_old[fifo_head], 0)),
            self.output_event.fields["new_ptr"].eq(self.rsp_new_ptr),
            self.output_event.fields["event_id"].eq(Mux(~fifo_empty, f_id[fifo_head], 0)),
            self.output_event.fields["core_id"].eq(Mux(~fifo_empty, f_core[fifo_head], 0)),
            self.output_event.fields["epoch"].eq(self.epoch),
        ]
        return m


# ── 工厂函数 ──
def create_forwarding_table(impl: str, **kwargs):
    if impl == "standard":
        return ForwardingTableStandard(**kwargs)
    elif impl == "banked_pipeline":
        return ForwardingTableBankedPipeline(**kwargs)
    raise ValueError(f"Unknown impl: {impl}")
