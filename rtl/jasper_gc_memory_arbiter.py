# rtl/jasper_gc_memory_arbiter.py
# 4-input arbiter: compact > mre > sweep > scan, configurable N-outstanding.
from amaranth import *
from math import ceil, log2


class MemoryRequestArbiter(Elaboratable):
    """4-input arbiter: compact > mre > sweep > scan. Configurable N-outstanding."""
    def __init__(self, max_outstanding=1):
        self.max_outstanding = max_outstanding
        for name in ['compact', 'mre', 'sweep', 'scan']:
            setattr(self, f'{name}_req_valid', Signal())
            setattr(self, f'{name}_req_ready', Signal())
            setattr(self, f'{name}_req_is_write', Signal())
            setattr(self, f'{name}_req_addr', Signal(32))
            setattr(self, f'{name}_req_tag', Signal(16))
            setattr(self, f'{name}_rsp_valid', Signal())
            setattr(self, f'{name}_rsp_ready', Signal())
            setattr(self, f'{name}_rsp_tag', Signal(16))

        self.mem_req_valid = Signal(); self.mem_req_ready = Signal()
        self.mem_req_is_write = Signal(); self.mem_req_addr = Signal(32)
        self.mem_req_tag = Signal(16)
        self.mem_rsp_valid = Signal(); self.mem_rsp_ready = Signal()
        self.mem_rsp_tag = Signal(16)

        self.dbg_outstanding = Signal(range(max_outstanding + 1))
        self.dbg_out_engine = Signal(2)
        self.dbg_any_engine_req_valid = Signal()

    def elaborate(self, platform):
        m = Module()
        max_os = self.max_outstanding
        inc = Signal(); dec = Signal()
        m.d.comb += inc.eq(self.mem_req_valid & self.mem_req_ready)
        m.d.comb += dec.eq(self.mem_rsp_valid & self.mem_rsp_ready)

        outstanding_cnt = self.dbg_outstanding
        with m.If(inc & ~dec):
            m.d.sync += outstanding_cnt.eq(outstanding_cnt + 1)
        with m.Elif(~inc & dec):
            m.d.sync += outstanding_cnt.eq(outstanding_cnt - 1)

        can_accept = outstanding_cnt < max_os

        sel_cp = Signal(); sel_mre = Signal(); sel_sw = Signal(); sel_sc = Signal()
        m.d.comb += [
            sel_cp.eq(self.compact_req_valid & can_accept),
            sel_mre.eq(self.mre_req_valid & can_accept & ~sel_cp),
            sel_sw.eq(self.sweep_req_valid & can_accept & ~sel_cp & ~sel_mre),
            sel_sc.eq(self.scan_req_valid & can_accept & ~sel_cp & ~sel_mre & ~sel_sw),
        ]

        any_sel = Signal(); m.d.comb += any_sel.eq(sel_cp | sel_mre | sel_sw | sel_sc)
        m.d.comb += self.dbg_any_engine_req_valid.eq(
            self.compact_req_valid | self.mre_req_valid | self.sweep_req_valid | self.scan_req_valid)

        sel_engine = Signal(2)
        m.d.comb += sel_engine.eq(
            Mux(sel_cp, 3,
            Mux(sel_mre, 2,
            Mux(sel_sw, 1, 0))))

        m.d.comb += [
            self.mem_req_valid.eq(any_sel),
            self.mem_req_is_write.eq(Mux(sel_cp, self.compact_req_is_write,
                                     Mux(sel_mre, self.mre_req_is_write,
                                     Mux(sel_sw, self.sweep_req_is_write, self.scan_req_is_write)))),
            self.mem_req_addr.eq(Mux(sel_cp, self.compact_req_addr,
                                Mux(sel_mre, self.mre_req_addr,
                                Mux(sel_sw, self.sweep_req_addr, self.scan_req_addr)))),
            self.compact_req_ready.eq(sel_cp & self.mem_req_ready),
            self.mre_req_ready.eq(sel_mre & self.mem_req_ready),
            self.sweep_req_ready.eq(sel_sw & self.mem_req_ready),
            self.scan_req_ready.eq(sel_sc & self.mem_req_ready),
        ]

        if max_os == 1:
            out_engine = self.dbg_out_engine
            with m.If(inc):
                m.d.sync += out_engine.eq(sel_engine)

            m.d.comb += self.mem_req_tag.eq(Mux(sel_cp, self.compact_req_tag,
                                           Mux(sel_mre, self.mre_req_tag,
                                           Mux(sel_sw, self.sweep_req_tag, self.scan_req_tag))))

            rsp_cp = out_engine == 3; rsp_mre = out_engine == 2
            rsp_sw = out_engine == 1; rsp_sc = out_engine == 0
            m.d.comb += [
                self.compact_rsp_valid.eq(self.mem_rsp_valid & rsp_cp),
                self.mre_rsp_valid.eq(self.mem_rsp_valid & rsp_mre),
                self.sweep_rsp_valid.eq(self.mem_rsp_valid & rsp_sw),
                self.scan_rsp_valid.eq(self.mem_rsp_valid & rsp_sc),
                self.mem_rsp_ready.eq(Mux(rsp_cp, self.compact_rsp_ready,
                                      Mux(rsp_mre, self.mre_rsp_ready,
                                      Mux(rsp_sw, self.sweep_rsp_ready, self.scan_rsp_ready)))),
            ]
            for name in ['compact', 'mre', 'sweep', 'scan']:
                m.d.comb += getattr(self, f'{name}_rsp_tag').eq(self.mem_rsp_tag)
        else:
            rrb_tag_lsb_width = ceil(log2(max_os))
            rrb_valid = [Signal() for _ in range(max_os)]
            rrb_engine = [Signal(2) for _ in range(max_os)]
            rrb_valid_arr = Array(rrb_valid)
            rrb_engine_arr = Array(rrb_engine)

            found_expr = 0
            for i in range(max_os):
                found_expr = found_expr | ~rrb_valid[i]
            slot_found = Signal(); m.d.comb += slot_found.eq(found_expr)

            pos_expr = 0
            for i in range(max_os - 1, -1, -1):
                pos_expr = Mux(~rrb_valid[i], i, pos_expr)
            slot_pos = Signal(range(max_os)); m.d.comb += slot_pos.eq(pos_expr)

            user_tag = Signal(16)
            m.d.comb += user_tag.eq(Mux(sel_cp, self.compact_req_tag,
                                   Mux(sel_mre, self.mre_req_tag,
                                   Mux(sel_sw, self.sweep_req_tag, self.scan_req_tag))))
            m.d.comb += self.mem_req_tag.eq((user_tag << rrb_tag_lsb_width) | slot_pos)

            with m.If(inc & slot_found):
                m.d.sync += rrb_valid_arr[slot_pos].eq(1)
                m.d.sync += rrb_engine_arr[slot_pos].eq(sel_engine)
                m.d.sync += self.dbg_out_engine.eq(sel_engine)

            rsp_pos = Signal(range(max_os))
            m.d.comb += rsp_pos.eq(self.mem_rsp_tag[:rrb_tag_lsb_width])
            rsp_engine = Signal(2)
            m.d.comb += rsp_engine.eq(rrb_engine_arr[rsp_pos])

            m.d.comb += [
                self.compact_rsp_valid.eq(self.mem_rsp_valid & (rsp_engine == 3)),
                self.mre_rsp_valid.eq(self.mem_rsp_valid & (rsp_engine == 2)),
                self.sweep_rsp_valid.eq(self.mem_rsp_valid & (rsp_engine == 1)),
                self.scan_rsp_valid.eq(self.mem_rsp_valid & (rsp_engine == 0)),
                self.mem_rsp_ready.eq(Mux(rsp_engine == 3, self.compact_rsp_ready,
                                      Mux(rsp_engine == 2, self.mre_rsp_ready,
                                      Mux(rsp_engine == 1, self.sweep_rsp_ready, self.scan_rsp_ready)))),
            ]

            unpacked_tag = Signal(16)
            m.d.comb += unpacked_tag.eq(self.mem_rsp_tag >> rrb_tag_lsb_width)
            for name in ['compact', 'mre', 'sweep', 'scan']:
                m.d.comb += getattr(self, f'{name}_rsp_tag').eq(unpacked_tag)

            with m.If(dec):
                m.d.sync += rrb_valid_arr[rsp_pos].eq(0)

        return m
