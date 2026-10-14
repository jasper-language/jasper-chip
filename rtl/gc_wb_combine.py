# rtl/gc_wb_combine.py — 写屏障合并缓冲 (write-combining buffer)
# 位于 store 流水线与 WB FIFO 之间：
#   相邻对同一 card 的写入仅产生一条 WB 事件，减少 FIFO 压力。
from amaranth import *


class GCWBCombine(Elaboratable):
    def __init__(self, depth=4, max_age=4):
        self._depth = depth
        self._max_age = max_age
        self._age_bits = max(1, (max_age - 1).bit_length())

        # Inputs
        self.wb_combine_enable = Signal(reset=1)
        self.mem1_addr = Signal(32)
        self.mem1_is_store = Signal()
        self.mem1_wdata = Signal(32)
        self.store_grant = Signal()
        self.wb_card_shift = Signal(6)
        self.wb_obj_shift = Signal(6)
        self.wb_ptr_filter = Signal()
        self.flush = Signal()
        self.wbq_w_rdy = Signal()

        # Outputs
        self.wbq_w_data = Signal(64)
        self.wbq_w_en = Signal()
        self.stall_store = Signal()
        self.wb_valid = Signal()

    @staticmethod
    def _prio_first(signals):
        found = Const(0)
        idx = Const(0)
        for i, s in enumerate(signals):
            idx = Mux(found if i > 0 else s, idx,
                      Const(i, max(1, (len(signals) - 1).bit_length())))
            found = found | s
        return found, idx

    def elaborate(self, platform):
        m = Module()
        D = self._depth
        MAX_AGE = self._max_age
        AB = self._age_bits

        card_id = Signal(32)
        obj_id = Signal(32)
        m.d.comb += [
            card_id.eq(self.mem1_addr >> self.wb_card_shift),
            obj_id.eq(self.mem1_addr >> self.wb_obj_shift),
        ]

        ptr_hit = Signal()
        m.d.comb += ptr_hit.eq(Mux(self.wb_ptr_filter == 1,
                                   self.mem1_wdata[31], 1))

        enable = Signal()
        m.d.comb += enable.eq(self.wb_combine_enable)
        new_store = Signal()
        m.d.comb += new_store.eq(self.store_grant & ptr_hit)

        # ── Merge buffer entries ──
        v = Array([Signal() for _ in range(D)])
        c = Array([Signal(32) for _ in range(D)])
        o = Array([Signal(32) for _ in range(D)])
        a = Array([Signal(AB) for _ in range(D)])

        # Match incoming card_id against valid entries
        mh = [v[i] & (c[i] == card_id) for i in range(D)]
        match_found, match_idx = self._prio_first(mh)

        # First free slot
        free_found, free_idx = self._prio_first([~v[i] for i in range(D)])
        buffer_full = Signal()
        m.d.comb += buffer_full.eq(~free_found)

        # On new store: merge or allocate
        with m.If(new_store & enable):
            with m.If(match_found):
                m.d.sync += o[match_idx].eq(obj_id)
            with m.Elif(free_found):
                m.d.sync += [
                    v[free_idx].eq(1),
                    c[free_idx].eq(card_id),
                    o[free_idx].eq(obj_id),
                    a[free_idx].eq(0),
                ]

        # Age increment for valid entries
        for i in range(D):
            with m.If(v[i] & (a[i] < MAX_AGE - 1)):
                m.d.sync += a[i].eq(a[i] + 1)

        # ── Flush arbitration ──
        any_aged = Signal()
        m.d.comb += any_aged.eq(Cat(*[v[i] & (a[i] >= MAX_AGE - 1)
                                      for i in range(D)]).bool())

        # Priority: aged entries first, then round-robin
        aged_found, aged_idx = self._prio_first(
            [v[i] & (a[i] >= MAX_AGE - 1) for i in range(D)])
        flush_ptr = Signal(range(D), reset=0)
        flush_sel = Mux(aged_found, aged_idx, flush_ptr)

        need_flush = Signal()
        m.d.comb += need_flush.eq(
            self.wbq_w_rdy & (
                any_aged | self.flush |
                (buffer_full & ~new_store & v[flush_sel])
            ))

        can_flush = Signal()
        m.d.comb += can_flush.eq(need_flush & v[flush_sel])

        with m.If(can_flush):
            m.d.sync += [
                v[flush_sel].eq(0),
                a[flush_sel].eq(0),
                flush_ptr.eq(Mux(flush_sel == D - 1, 0, flush_sel + 1)),
            ]

        # wb_valid: any pending entry
        m.d.comb += self.wb_valid.eq(Cat(*v).bool())

        # ── Bypass path (combine disabled) ──
        bypass_en = Signal()
        bypass_data = Signal(64)
        m.d.comb += [
            bypass_en.eq(new_store & ~enable & self.wbq_w_rdy),
            bypass_data.eq(Cat(card_id, obj_id)),
        ]

        # ── Output mux ──
        m.d.comb += [
            self.wbq_w_en.eq(Mux(enable, can_flush, bypass_en)),
            self.wbq_w_data.eq(Mux(enable, Cat(c[flush_sel], o[flush_sel]),
                                   bypass_data)),
            self.stall_store.eq(Mux(
                enable,
                ptr_hit & ~match_found & buffer_full,
                ptr_hit & ~self.wbq_w_rdy,
            )),
        ]

        return m
