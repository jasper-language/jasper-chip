"""Legal encoding decoder for RISC-V V floating fused operations."""

from amaranth import Const, Elaboratable, Module, Mux, Signal


class VFFMADecode(Elaboratable):
    def __init__(self, xlen=32, enable_fp32=True, enable_fp64=True):
        self.xlen = xlen
        self.enable_fp32 = enable_fp32
        self.enable_fp64 = enable_fp64
        self.insn = Signal(32)
        self.vtype = Signal(xlen)
        self.vl = Signal(8)
        self.vlmax = Signal(8)
        self.vstart = Signal(8)
        self.frm = Signal(3)
        self.scalar = Signal(64)

        self.match = Signal()
        self.legal = Signal()
        self.vd = Signal(5)
        self.vs2 = Signal(5)
        self.vs1 = Signal(5)
        self.is_vv = Signal()
        self.is_f64 = Signal()
        self.widen = Signal()
        self.accumulate = Signal()
        self.multiply_only = Signal()
        self.add_only = Signal()
        self.wide_vs2 = Signal()
        self.negate_product = Signal()
        self.negate_addend = Signal()
        self.vm = Signal()
        self.vta = Signal()
        self.vma = Signal()
        self.element = Signal(8)
        self.evl = Signal(8)
        self.tail_limit = Signal(8)
        self.scalar_value = Signal(64)

    def elaborate(self, platform):
        m = Module()
        opcode = self.insn[:7]
        vd = self.insn[7:12]
        funct3 = self.insn[12:15]
        vs1 = self.insn[15:20]
        vs2 = self.insn[20:25]
        vm = self.insn[25]
        funct6 = self.insn[26:32]

        is_form = (funct3 == 0b001) | (funct3 == 0b101)
        is_vffma = (funct6 >= 0x28) & (funct6 <= 0x2f) & is_form
        is_vfwmul = (funct6 == 0x38) & is_form
        is_vfwfma = (funct6 >= 0x3c) & (funct6 <= 0x3f) & is_form
        is_vfwadd = (((funct6 == 0x30) | (funct6 == 0x32) |
                      (funct6 == 0x34) | (funct6 == 0x36)) & is_form)
        match = (opcode == 0x57) & (is_vffma | is_vfwmul |
                                    is_vfwfma | is_vfwadd)
        widen = is_vfwmul | is_vfwfma | is_vfwadd
        wide_vs2 = is_vfwadd & funct6[2]
        is_vv = funct3 == 0b001

        source_group = Signal(4)
        dest_group = Signal(5)
        source2_group = Signal(5)
        width_legal = Signal()
        groups_legal = Signal()
        vs2_overlap_ok = Signal()
        vs1_overlap_ok = Signal()
        m.d.comb += [
            source_group.eq(1),
            width_legal.eq(Mux(
                widen,
                (self.vtype[3:6] == 2) & Const(self.enable_fp32) &
                Const(self.enable_fp64),
                Mux(self.vtype[3:6] == 2, Const(self.enable_fp32),
                    (self.vtype[3:6] == 3) & Const(self.enable_fp64)))),
        ]
        with m.Switch(self.vtype[:3]):
            with m.Case(1):
                m.d.comb += source_group.eq(2)
            with m.Case(2):
                m.d.comb += source_group.eq(4)
            with m.Case(3):
                m.d.comb += source_group.eq(8)
        m.d.comb += [
            dest_group.eq(Mux(widen, source_group << 1, source_group)),
            source2_group.eq(Mux(wide_vs2, source_group << 1,
                                 source_group)),
            vs2_overlap_ok.eq(
                ~widen | wide_vs2 |
                (vs2 + source2_group <= vd) |
                (vd + dest_group <= vs2) |
                (vs2 == vd + dest_group - source2_group)),
            vs1_overlap_ok.eq(
                ~widen | ~is_vv |
                (vs1 + source_group <= vd) |
                (vd + dest_group <= vs1) |
                (vs1 == vd + dest_group - source_group)),
            groups_legal.eq(
                (self.vtype[:3] <= Mux(widen, 2, 3)) &
                ((vd & (dest_group - 1)) == 0) &
                ((vs2 & (source2_group - 1)) == 0) &
                (~is_vv | ((vs1 & (source_group - 1)) == 0)) &
                (vd + dest_group <= 32) &
                (vs2 + source2_group <= 32) &
                (~is_vv | (vs1 + source_group <= 32)) &
                vs2_overlap_ok & vs1_overlap_ok & (vm | (vd != 0))),
            self.match.eq(match),
            self.legal.eq(match & ~self.vtype[self.xlen - 1] &
                          width_legal & groups_legal & (self.frm <= 4)),
            self.vd.eq(vd), self.vs2.eq(vs2), self.vs1.eq(vs1),
            self.is_vv.eq(is_vv),
            self.is_f64.eq(~widen & (self.vtype[3:6] == 3)),
            self.widen.eq(widen),
            self.accumulate.eq(is_vfwfma | funct6[2]),
            self.multiply_only.eq(is_vfwmul),
            self.add_only.eq(is_vfwadd),
            self.wide_vs2.eq(wide_vs2),
            self.negate_product.eq(Mux(
                is_vfwmul, 0, Mux(is_vfwadd, funct6[1], funct6[0]))),
            self.negate_addend.eq(Mux(
                is_vfwmul | is_vfwadd, 0, funct6[0] ^ funct6[1])),
            self.vm.eq(vm), self.vta.eq(self.vtype[6]),
            self.vma.eq(self.vtype[7]), self.element.eq(self.vstart),
            self.evl.eq(self.vl),
            self.tail_limit.eq(Mux(self.vstart >= self.vl,
                                   self.vl, self.vlmax)),
            self.scalar_value.eq(Mux(
                is_vv, 0,
                Mux(widen | (self.vtype[3:6] == 2),
                    Mux(self.scalar[32:64].all(), self.scalar,
                        Const(0xffffffff7fc00000, 64)),
                    self.scalar))),
        ]
        return m
