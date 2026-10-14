"""Legal encoding decoder for RISC-V V 7-bit FP estimates."""

from amaranth import Const, Elaboratable, Module, Mux, Signal


class VFEstimate7Decode(Elaboratable):
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
        self.match = Signal()
        self.legal = Signal()
        self.vd = Signal(5)
        self.vs2 = Signal(5)
        self.reciprocal_sqrt = Signal()
        self.is_f64 = Signal()
        self.vm = Signal()
        self.vta = Signal()
        self.vma = Signal()
        self.element = Signal(8)
        self.evl = Signal(8)
        self.tail_limit = Signal(8)

    def elaborate(self, platform):
        m = Module()
        vd = self.insn[7:12]
        funct3 = self.insn[12:15]
        rs1 = self.insn[15:20]
        vs2 = self.insn[20:25]
        vm = self.insn[25]
        funct6 = self.insn[26:32]
        match = ((self.insn[:7] == 0x57) & (funct6 == 0x13) &
                 (funct3 == 0b001) & ((rs1 == 4) | (rs1 == 5)))
        reciprocal = rs1 == 5
        group_regs = Signal(4)
        width_legal = Signal()
        m.d.comb += [
            group_regs.eq(1),
            width_legal.eq(Mux(
                self.vtype[3:6] == 2, Const(self.enable_fp32),
                Mux(self.vtype[3:6] == 3, Const(self.enable_fp64), 0))),
        ]
        with m.Switch(self.vtype[:3]):
            with m.Case(1):
                m.d.comb += group_regs.eq(2)
            with m.Case(2):
                m.d.comb += group_regs.eq(4)
            with m.Case(3):
                m.d.comb += group_regs.eq(8)
        group_legal = ((self.vtype[:3] != 4) &
                       ((vd & (group_regs - 1)) == 0) &
                       ((vs2 & (group_regs - 1)) == 0) &
                       (vd + group_regs <= 32) &
                       (vs2 + group_regs <= 32) & (vm | (vd != 0)))
        m.d.comb += [
            self.match.eq(match),
            self.legal.eq(match & ~self.vtype[self.xlen - 1] &
                          width_legal & group_legal &
                          (~reciprocal | (self.frm <= 4))),
            self.vd.eq(vd), self.vs2.eq(vs2),
            self.reciprocal_sqrt.eq(rs1 == 4),
            self.is_f64.eq(self.vtype[3:6] == 3), self.vm.eq(vm),
            self.vta.eq(self.vtype[6]), self.vma.eq(self.vtype[7]),
            self.element.eq(self.vstart), self.evl.eq(self.vl),
            self.tail_limit.eq(Mux(self.vstart >= self.vl,
                                   self.vl, self.vlmax)),
        ]
        return m
