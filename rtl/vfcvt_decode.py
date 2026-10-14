"""Complete legal decoder for the 21 RISC-V V conversion sub-operations."""

from amaranth import Const, Elaboratable, Module, Mux, Signal


class VFCvtDecode(Elaboratable):
    SAME = 0
    WIDEN = 1
    NARROW = 2

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
        self.mode = Signal(2)
        self.vd = Signal(5)
        self.vs2 = Signal(5)
        self.vm = Signal()
        self.vta = Signal()
        self.vma = Signal()
        self.to_int = Signal()
        self.int_to_float = Signal()
        self.float_to_float = Signal()
        self.unsigned = Signal()
        self.fixed_rtz = Signal()
        self.round_odd = Signal()
        self.input_f64 = Signal()
        self.output_f64 = Signal()
        self.source_group = Signal(4)
        self.dest_group = Signal(4)
        self.use_snapshot = Signal()
        self.high_overlap = Signal()
        self.low_overlap = Signal()
        self.element = Signal(8)
        self.evl = Signal(8)
        self.tail_limit = Signal(8)

    def elaborate(self, platform):
        m = Module()
        vd = self.insn[7:12]
        funct3 = self.insn[12:15]
        subop = self.insn[15:20]
        vs2 = self.insn[20:25]
        vm = self.insn[25]
        funct6 = self.insn[26:32]

        same = ((subop == 0x00) | (subop == 0x01) |
                (subop == 0x02) | (subop == 0x03) |
                (subop == 0x06) | (subop == 0x07))
        widen = ((subop == 0x08) | (subop == 0x09) |
                 (subop == 0x0a) | (subop == 0x0b) |
                 (subop == 0x0c) | (subop == 0x0e) |
                 (subop == 0x0f))
        narrow = ((subop == 0x10) | (subop == 0x11) |
                  (subop == 0x12) | (subop == 0x13) |
                  (subop == 0x14) | (subop == 0x15) |
                  (subop == 0x16) | (subop == 0x17))
        match = ((self.insn[:7] == 0x57) & (funct6 == 0x12) &
                 (funct3 == 0b001) & (same | widen | narrow))
        mode = Mux(widen, self.WIDEN, Mux(narrow, self.NARROW, self.SAME))

        same_group = Signal(4)
        double_group = Signal(4)
        lmul_reserved = self.vtype[:3] == 4
        lmul_too_large = self.vtype[:3] == 3
        m.d.comb += [same_group.eq(1), double_group.eq(1)]
        with m.Switch(self.vtype[:3]):
            with m.Case(0):
                m.d.comb += double_group.eq(2)
            with m.Case(1):
                m.d.comb += [same_group.eq(2), double_group.eq(4)]
            with m.Case(2):
                m.d.comb += [same_group.eq(4), double_group.eq(8)]
            with m.Case(3):
                m.d.comb += [same_group.eq(8), double_group.eq(8)]

        source_group = Mux(narrow, double_group, same_group)
        dest_group = Mux(widen, double_group, same_group)
        source_aligned = ((source_group == 1) |
                          ((vs2 & (source_group - 1)) == 0))
        dest_aligned = ((dest_group == 1) |
                        ((vd & (dest_group - 1)) == 0))
        disjoint = ((vd + dest_group <= vs2) |
                    (vs2 + source_group <= vd))
        integer_lmul = self.vtype[:3] <= 2
        high_overlap = (widen & integer_lmul &
                        (vs2 == vd + source_group))
        low_overlap = narrow & (vd == vs2)

        to_int = ((subop == 0x00) | (subop == 0x01) |
                  (subop == 0x06) | (subop == 0x07) |
                  (subop == 0x08) | (subop == 0x09) |
                  (subop == 0x0e) | (subop == 0x0f) |
                  (subop == 0x10) | (subop == 0x11) |
                  (subop == 0x16) | (subop == 0x17))
        int_to_float = ((subop == 0x02) | (subop == 0x03) |
                        (subop == 0x0a) | (subop == 0x0b) |
                        (subop == 0x12) | (subop == 0x13))
        float_to_float = (subop == 0x0c) | (subop == 0x14) | (subop == 0x15)
        unsigned = ((subop == 0x00) | (subop == 0x02) |
                    (subop == 0x06) | (subop == 0x08) |
                    (subop == 0x0a) | (subop == 0x0e) |
                    (subop == 0x10) | (subop == 0x12) |
                    (subop == 0x16))
        fixed_rtz = ((subop == 0x06) | (subop == 0x07) |
                     (subop == 0x0e) | (subop == 0x0f) |
                     (subop == 0x16) | (subop == 0x17))
        round_odd = subop == 0x15
        input_f64 = ((same & (self.vtype[3:6] == 3)) | narrow)
        output_f64 = ((same & (self.vtype[3:6] == 3)) | widen)
        same_width_ok = ((self.vtype[3:6] == 2) &
                         Const(self.enable_fp32) |
                         (self.vtype[3:6] == 3) &
                         Const(self.enable_fp64))
        width_ok = Mux(same, same_width_ok,
                       (self.vtype[3:6] == 2) &
                       Const(self.enable_fp32) & Const(self.enable_fp64))
        overlap_ok = Mux(same, 1, disjoint | high_overlap | low_overlap)
        rm_ok = fixed_rtz | round_odd | (self.frm <= 4)
        group_ok = (~lmul_reserved & (~(widen | narrow) | ~lmul_too_large) &
                    source_aligned & dest_aligned &
                    (vs2 + source_group <= 32) &
                    (vd + dest_group <= 32) & overlap_ok &
                    (vm | (vd != 0)))

        m.d.comb += [
            self.match.eq(match),
            self.legal.eq(match & ~self.vtype[self.xlen - 1] &
                          width_ok & group_ok & rm_ok),
            self.mode.eq(mode), self.vd.eq(vd), self.vs2.eq(vs2),
            self.vm.eq(vm), self.vta.eq(self.vtype[6]),
            self.vma.eq(self.vtype[7]), self.to_int.eq(to_int),
            self.int_to_float.eq(int_to_float),
            self.float_to_float.eq(float_to_float),
            self.unsigned.eq(unsigned), self.fixed_rtz.eq(fixed_rtz),
            self.round_odd.eq(round_odd), self.input_f64.eq(input_f64),
            self.output_f64.eq(output_f64),
            self.source_group.eq(source_group),
            self.dest_group.eq(dest_group), self.use_snapshot.eq(widen | narrow),
            self.high_overlap.eq(high_overlap), self.low_overlap.eq(low_overlap),
            self.element.eq(self.vstart), self.evl.eq(self.vl),
            self.tail_limit.eq(Mux(self.vstart >= self.vl,
                                   self.vl, self.vlmax)),
        ]
        return m
