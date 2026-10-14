"""Legal encoding decoder for RISC-V V memory instructions."""

from amaranth import Const, Elaboratable, Module, Mux, Signal


class VMemoryDecode(Elaboratable):
    def __init__(self, xlen=32):
        self.xlen = xlen
        self.insn = Signal(32)
        self.is_load = Signal()
        self.vtype = Signal(xlen)
        self.vl = Signal(8)
        self.vlmax = Signal(8)
        self.vstart = Signal(8)

        self.legal = Signal()
        self.indexed = Signal()
        self.strided = Signal()
        self.fof = Signal()
        self.whole = Signal()
        self.mask = Signal()
        self.vm = Signal()
        self.vma = Signal()
        self.vta = Signal()
        self.vreg = Signal(5)
        self.index_vreg = Signal(5)
        self.eew_bytes = Signal(4)
        self.index_bytes = Signal(4)
        self.fields = Signal(4)
        self.field_stride = Signal(4)
        self.element = Signal(8)
        self.evl = Signal(8)
        self.tail_limit = Signal(8)

    def elaborate(self, platform):
        m = Module()
        rd = self.insn[7:12]
        funct3 = self.insn[12:15]
        rs2 = self.insn[20:25]
        vm = self.insn[25]
        mop = self.insn[26:28]
        nf = self.insn[29:32]

        encoded_bytes = Signal(4)
        data_bytes = Signal(4)
        index_bytes = Signal(4)
        fields = Signal(4)
        field_stride = Signal(4)
        data_group_bytes = Signal(11)
        index_group_bytes = Signal(11)
        index_group_regs = Signal(4)
        total_data_regs = Signal(7)
        whole_evl = Signal(8)
        is_indexed = mop[0]
        is_strided = mop == 0b10
        is_whole = (mop == 0) & (rs2 == 0b01000)
        is_mask = (mop == 0) & (rs2 == 0b01011)
        is_fof = self.is_load & (mop == 0) & (rs2 == 0b10000)
        normal_unit = (mop == 0) & (rs2 == 0)
        width_valid = ((funct3 == 0b000) | (funct3 == 0b101) |
                       (funct3 == 0b110) | (funct3 == 0b111))
        mode_valid = (is_indexed | is_strided | normal_unit |
                      is_whole | is_mask | is_fof)
        whole_count_valid = ((nf == 0) | (nf == 1) | (nf == 3) | (nf == 7))

        m.d.comb += [
            encoded_bytes.eq(Mux(funct3 == 0b000, 1,
                Mux(funct3 == 0b101, 2,
                    Mux(funct3 == 0b110, 4, 8)))),
            data_bytes.eq(Mux(is_mask, 1,
                Mux(is_indexed, Const(1, 4) << self.vtype[3:6],
                    encoded_bytes))),
            index_bytes.eq(encoded_bytes),
            fields.eq(Mux(is_whole | is_mask, 1, nf + 1)),
            data_group_bytes.eq(self.vlmax * data_bytes),
            index_group_bytes.eq(self.vlmax * index_bytes),
            field_stride.eq(Mux(is_whole | is_mask, 1,
                                (data_group_bytes + 15) >> 4)),
            index_group_regs.eq((index_group_bytes + 15) >> 4),
            total_data_regs.eq(Mux(is_whole, nf + 1,
                Mux(is_mask, 1, field_stride * fields))),
            whole_evl.eq(Mux(encoded_bytes == 1, (nf + 1) << 4,
                Mux(encoded_bytes == 2, (nf + 1) << 3,
                    Mux(encoded_bytes == 4, (nf + 1) << 2,
                        (nf + 1) << 1)))),
        ]

        data_alignment_ok = ((field_stride <= 1) |
                             ((rd & (field_stride - 1)) == 0))
        index_alignment_ok = ((index_group_regs <= 1) |
                              ((rs2 & (index_group_regs - 1)) == 0))
        indexed_load_overlap = (self.is_load & is_indexed &
            ~((rd + total_data_regs <= rs2) |
              (rs2 + index_group_regs <= rd)))
        regular_legal = (
            ~self.vtype[self.xlen - 1] &
            (data_group_bytes >= 2) & (data_group_bytes <= 128) &
            (field_stride >= 1) & (field_stride <= 8) &
            (total_data_regs <= 8) & data_alignment_ok &
            (rd + total_data_regs <= 32) &
            (~is_indexed |
             ((index_group_bytes >= 2) & (index_group_bytes <= 128) &
              (index_group_regs <= 8) & index_alignment_ok &
              (rs2 + index_group_regs <= 32) & ~indexed_load_overlap)) &
            (vm | ~self.is_load | (rd != 0)))
        whole_legal = (is_whole & whole_count_valid & vm &
                       ((rd & nf) == 0) & (rd + nf + 1 <= 32))
        mask_legal = (is_mask & (funct3 == 0) & (nf == 0) & vm)

        m.d.comb += [
            self.legal.eq(width_valid & ~self.insn[28] & mode_valid &
                Mux(is_whole, whole_legal,
                    Mux(is_mask, mask_legal, regular_legal))),
            self.indexed.eq(is_indexed), self.strided.eq(is_strided),
            self.fof.eq(is_fof), self.whole.eq(is_whole),
            self.mask.eq(is_mask), self.vm.eq(vm),
            self.vma.eq(self.vtype[7]), self.vta.eq(self.vtype[6]),
            self.vreg.eq(rd), self.index_vreg.eq(rs2),
            self.eew_bytes.eq(data_bytes), self.index_bytes.eq(index_bytes),
            self.fields.eq(fields), self.field_stride.eq(field_stride),
            self.element.eq(Mux(is_whole | is_mask, 0, self.vstart)),
            self.evl.eq(Mux(is_whole, whole_evl,
                Mux(is_mask, (self.vl + 7) >> 3, self.vl))),
            self.tail_limit.eq(Mux(is_whole, whole_evl,
                Mux(is_mask, (self.vl + 7) >> 3,
                    Mux(self.vstart >= self.vl, self.vl, self.vlmax)))),
        ]
        return m
