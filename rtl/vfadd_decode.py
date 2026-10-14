"""Legal encoding decoder for RISC-V V floating add/subtract."""

from amaranth import Const, Elaboratable, Module, Mux, Signal


class VFAddDecode(Elaboratable):
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
        self.subtract = Signal()
        self.reverse = Signal()
        self.is_f64 = Signal()
        self.vm = Signal()
        self.vta = Signal()
        self.vma = Signal()
        self.element = Signal(8)
        self.evl = Signal(8)
        self.tail_limit = Signal(8)
        self.scalar_value = Signal(64)

    def elaborate(self, platform):
        m = Module()
        vd = self.insn[7:12]
        funct3 = self.insn[12:15]
        vs1 = self.insn[15:20]
        vs2 = self.insn[20:25]
        vm = self.insn[25]
        funct6 = self.insn[26:32]
        is_vv = funct3 == 0b001
        is_vf = funct3 == 0b101
        reverse = (funct6 == 0x27) & is_vf
        subtract = ((funct6 == 0x02) & (is_vv | is_vf)) | reverse
        match = ((self.insn[:7] == 0x57) &
                 (((funct6 == 0x00) | (funct6 == 0x02)) &
                  (is_vv | is_vf) | reverse))
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
                       (~is_vv | ((vs1 & (group_regs - 1)) == 0)) &
                       (vd <= 32 - group_regs) &
                       (vs2 <= 32 - group_regs) &
                       (~is_vv | (vs1 <= 32 - group_regs)) &
                       (vm | (vd != 0)))
        m.d.comb += [
            self.match.eq(match),
            self.legal.eq(match & width_legal & group_legal &
                          (self.frm <= 4) &
                          ~self.vtype[self.xlen - 1]),
            self.vd.eq(vd), self.vs2.eq(vs2), self.vs1.eq(vs1),
            self.is_vv.eq(is_vv), self.subtract.eq(subtract),
            self.reverse.eq(reverse),
            self.is_f64.eq(self.vtype[3:6] == 3), self.vm.eq(vm),
            self.vta.eq(self.vtype[6]), self.vma.eq(self.vtype[7]),
            self.element.eq(self.vstart), self.evl.eq(self.vl),
            self.tail_limit.eq(Mux(self.vstart >= self.vl,
                                   self.vl, self.vlmax)),
            self.scalar_value.eq(Mux(
                self.vtype[3:6] == 3, self.scalar,
                Mux(self.scalar[32:64].all(), self.scalar,
                    Const(0xffffffff7fc00000, 64)))),
        ]
        return m
