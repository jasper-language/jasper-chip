from amaranth import *


class BranchPredictor(Elaboratable):
    BTB_SIZE = 8
    BHT_SIZE = 16
    RAS_SIZE = 4

    def __init__(self, xlen=32):
        self.xlen = xlen
        self.pc = Signal(xlen)
        self.pred_pc = Signal(xlen)
        self.pred_taken = Signal()
        self.pred_is_jal = Signal()
        self.pred_is_jalr = Signal()

        self.br_valid = Signal()
        self.br_pc = Signal(xlen)
        self.br_target = Signal(xlen)
        self.br_taken = Signal()
        self.br_is_branch = Signal()
        self.br_is_jal = Signal()
        self.br_is_jalr = Signal()
        self.mispredict = Signal()

    def elaborate(self, platform):
        m = Module()
        XLEN = self.xlen

        btb_v = Array(Signal(name=f"bv{i}") for i in range(self.BTB_SIZE))
        btb_tag = Array(Signal(XLEN - 5, name=f"bt{i}") for i in range(self.BTB_SIZE))
        btb_tgt = Array(Signal(XLEN, name=f"btt{i}") for i in range(self.BTB_SIZE))

        bht = Array(Signal(2, name=f"bh{i}") for i in range(self.BHT_SIZE))

        ras = Array(Signal(XLEN, name=f"rs{i}") for i in range(self.RAS_SIZE))
        ras_wptr = Signal(range(self.RAS_SIZE), reset=0)
        ras_rptr = Signal(range(self.RAS_SIZE), reset=0)

        btb_idx = Signal(3)
        m.d.comb += btb_idx.eq(self.pc[2:5])

        bht_idx = Signal(4)
        m.d.comb += bht_idx.eq(self.pc[2:6] ^ self.pc[6:10])

        tag_match = Signal()
        m.d.comb += tag_match.eq(btb_tag[btb_idx] == self.pc[5:])
        btb_hit = Signal()
        m.d.comb += btb_hit.eq(btb_v[btb_idx] & tag_match)

        btb_pred_taken = Signal()
        m.d.comb += btb_pred_taken.eq(bht[bht_idx][1])

        ras_top = Signal(XLEN)
        m.d.comb += ras_top.eq(ras[ras_rptr])

        pred_pc_next = Signal(XLEN)
        m.d.comb += [
            pred_pc_next.eq(Mux(btb_hit & btb_pred_taken, btb_tgt[btb_idx], self.pc + 4)),
            self.pred_pc.eq(pred_pc_next),
            self.pred_taken.eq(btb_hit & btb_pred_taken),
            self.pred_is_jal.eq(0),
            self.pred_is_jalr.eq(0),
        ]

        br_btb_idx = Signal(3)
        m.d.comb += br_btb_idx.eq(self.br_pc[2:5])
        br_bht_idx = Signal(4)
        m.d.comb += br_bht_idx.eq(self.br_pc[2:6] ^ self.br_pc[6:10])

        br_tag_match = Signal()
        m.d.comb += br_tag_match.eq(btb_tag[br_btb_idx] == self.br_pc[5:])
        br_btb_hit = Signal()
        m.d.comb += br_btb_hit.eq(btb_v[br_btb_idx] & br_tag_match)

        br_was_pred_taken = Signal()
        m.d.comb += br_was_pred_taken.eq(br_btb_hit & (bht[br_bht_idx][1]))

        with m.If(self.br_valid & (self.br_is_branch | self.br_is_jal) & self.br_taken):
            m.d.sync += [
                btb_v[br_btb_idx].eq(1),
                btb_tag[br_btb_idx].eq(self.br_pc[5:]),
                btb_tgt[br_btb_idx].eq(self.br_target),
            ]

        with m.If(self.br_valid & (self.br_is_branch | self.br_is_jal)):
            ctr = Signal(2)
            m.d.comb += ctr.eq(bht[br_bht_idx])
            with m.If(self.br_taken):
                with m.If(ctr != 0b11):
                    m.d.sync += bht[br_bht_idx].eq(ctr + 1)
            with m.Else():
                with m.If(ctr != 0b00):
                    m.d.sync += bht[br_bht_idx].eq(ctr - 1)

        with m.If(self.br_valid & self.br_is_jal):
            m.d.sync += [
                ras[ras_wptr].eq(self.br_pc + 4),
                ras_wptr.eq(Mux(ras_wptr == self.RAS_SIZE - 1, 0, ras_wptr + 1)),
                ras_rptr.eq(ras_wptr),
            ]

        with m.If(self.br_valid & self.br_is_jalr):
            m.d.sync += [
                ras_rptr.eq(Mux(ras_rptr == 0, self.RAS_SIZE - 1, ras_rptr - 1)),
            ]

        br_mispredict = Signal()
        m.d.comb += br_mispredict.eq(self.br_valid & self.br_is_branch & (br_was_pred_taken != self.br_taken))
        jalr_mispredict = Signal()
        m.d.comb += jalr_mispredict.eq(self.br_valid & self.br_is_jalr)
        jal_mispredict = Signal()
        m.d.comb += jal_mispredict.eq(0)
        m.d.comb += self.mispredict.eq(br_mispredict | jalr_mispredict | jal_mispredict)

        return m
