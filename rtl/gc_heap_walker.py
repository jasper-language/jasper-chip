# rtl/gc_heap_walker.py
from amaranth import *
from amaranth.lib.fifo import SyncFIFO

class GcHeapWalker(Elaboratable):
    OBJ_HEADER_WORDS = 2
    def __init__(self, fifo_depth=16, out_depth=8):
        self.fifo_depth = fifo_depth; self.out_depth = out_depth
        self.root_valid = Signal(); self.root_ready = Signal()
        self.root_ptr = Signal(32)
        self.card_valid = Signal(); self.card_ready = Signal()
        self.card_addr = Signal(32)
        self.dmem_addr = Signal(32); self.dmem_rdata = Signal(32)
        self.start = Signal(); self.active = Signal(); self.done = Signal()
        self.objects_scanned = Signal(32)

    def elaborate(self, platform):
        m = Module()
        wf = SyncFIFO(width=32, depth=self.fifo_depth)
        of = SyncFIFO(width=32, depth=self.out_depth)
        m.submodules.wf = wf; m.submodules.of = of
        S_IDLE, S_READ, S_SCAN = 0, 1, 2
        st = Signal(2); op = Signal(32); osz = Signal(32)
        ri = Signal(5); sc = Signal(32)
        push_work = Signal()

        m.d.comb += [
            self.root_ready.eq(wf.w_rdy),
            self.card_valid.eq(of.r_rdy),
            of.r_en.eq(self.card_ready & of.r_rdy),
            self.card_addr.eq(of.r_data),
            push_work.eq((st == S_SCAN) & (ri < osz) &
                         self.dmem_rdata[31] & of.w_rdy & wf.w_rdy),
        ]

        # Work FIFO write: external root OR internal discover
        wf_we = Signal()
        wf_wd = Signal(32)
        m.d.comb += [
            wf_we.eq((self.root_valid & wf.w_rdy) | push_work),
            wf_wd.eq(Mux(self.root_valid & wf.w_rdy, self.root_ptr, self.dmem_rdata)),
        ]
        with m.If(wf_we):
            m.d.sync += [wf.w_en.eq(1), wf.w_data.eq(wf_wd)]
        with m.Else():
            m.d.sync += [wf.w_en.eq(0)]

        # Output FIFO write: discovered references
        with m.If(push_work):
            m.d.sync += [of.w_en.eq(1), of.w_data.eq(self.dmem_rdata)]
        with m.Else():
            m.d.sync += [of.w_en.eq(0)]

        with m.If(self.start):
            m.d.sync += [st.eq(S_READ), self.active.eq(1), self.done.eq(0), sc.eq(0), ri.eq(0)]

        with m.If(st == S_READ):
            m.d.comb += self.dmem_addr.eq(op)
            m.d.sync += [osz.eq(self.dmem_rdata[0:20]), st.eq(S_SCAN), sc.eq(sc + 1)]

        with m.If(st == S_SCAN):
            with m.If(ri < osz):
                fa = Signal(32)
                m.d.comb += fa.eq(op + self.OBJ_HEADER_WORDS * 4 + ri * 4)
                m.d.comb += self.dmem_addr.eq(fa)
                m.d.sync += ri.eq(ri + 1)
            with m.Else():
                with m.If(wf.r_rdy):
                    m.d.sync += [op.eq(wf.r_data), wf.r_en.eq(1), st.eq(S_READ)]
                with m.Else():
                    m.d.sync += [st.eq(S_IDLE), self.active.eq(0), self.done.eq(1), self.objects_scanned.eq(sc)]

        # Idle → first root
        with m.If(wf.r_rdy & (st == S_IDLE)):
            m.d.sync += [op.eq(wf.r_data), wf.r_en.eq(1), st.eq(S_READ)]

        return m
