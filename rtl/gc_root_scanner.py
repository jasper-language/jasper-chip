# rtl/gc_root_scanner.py
from amaranth import *
from amaranth.lib.fifo import SyncFIFO

class GCRootScanner(Elaboratable):
    def __init__(self, fifo_depth=16, scan_fifo_depth=8):
        self.fifo_depth = fifo_depth; self.scan_fifo_depth = scan_fifo_depth
        self.root_valid = Signal(); self.root_ready = Signal()
        self.root_ptr = Signal(32); self.root_tag = Signal(8)
        self.scan_valid = Signal(); self.scan_ready = Signal()
        self.scan_card = Signal(32); self.scan_obj = Signal(32)
        self.start = Signal(); self.active = Signal(); self.done = Signal()
        self.root_count = Signal(32)

    def elaborate(self, platform):
        m = Module()
        rf = SyncFIFO(width=40, depth=self.fifo_depth)
        sf = SyncFIFO(width=64, depth=self.scan_fifo_depth)
        m.submodules.rf = rf; m.submodules.sf = sf
        S_IDLE, S_WORK = 0, 1
        st = Signal(2); rc = Signal(32)
        ptr = Signal(32); tag = Signal(8); fire = Signal()

        m.d.comb += [
            fire.eq((st == S_WORK) & rf.r_rdy & sf.w_rdy),
            rf.w_data.eq(Cat(self.root_tag, self.root_ptr)),
            rf.w_en.eq(self.root_valid & rf.w_rdy),
            self.root_ready.eq(rf.w_rdy),
            self.scan_valid.eq(sf.r_rdy),
            sf.r_en.eq(self.scan_ready & sf.r_rdy),
            self.scan_card.eq(sf.r_data[0:32]),
            self.scan_obj.eq(sf.r_data[32:64]),
            ptr.eq(rf.r_data[0:32]), tag.eq(rf.r_data[32:40]),
        ]

        with m.If(self.start):
            m.d.sync += [st.eq(S_WORK), self.active.eq(1), self.done.eq(0), rc.eq(0)]

        with m.If((st == S_WORK) & rf.r_rdy & sf.w_rdy):
            m.d.sync += [
                rf.r_en.eq(1), sf.w_en.eq(1),
                sf.w_data.eq(Cat(ptr, ptr)),
                rc.eq(rc + 1),
            ]
        with m.Else():
            m.d.sync += [rf.r_en.eq(0), sf.w_en.eq(0)]

        with m.If((st == S_WORK) & ~rf.r_rdy & ~fire):
            m.d.sync += [st.eq(S_IDLE), self.active.eq(0), self.done.eq(1), self.root_count.eq(rc)]

        return m
