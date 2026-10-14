from amaranth import *

from .isa_module import ISAExtension
from .isa import OP, OP_IMM


class Zbs(ISAExtension):
    def __init__(self, xlen=32):
        super().__init__(xlen=xlen, name="zbs")
        self._xlen = xlen

    def elaborate(self, platform):
        m = Module()

        m.d.comb += [
            self.wb_en.eq(0),
            self.wb_data.eq(0),
            self.alu_out.eq(0),
            self.mem_addr.eq(0),
            self.mem_wdata.eq(0),
            self.redirect.eq(0),
            self.redirect_pc.eq(0),
            self.trap.eq(0),
            self.br_valid.eq(0),
            self.br_pc.eq(0),
            self.br_target.eq(0),
            self.br_taken.eq(0),
            self.br_is_branch.eq(0),
            self.br_is_jal.eq(0),
            self.br_is_jalr.eq(0),
            self.is_load.eq(0),
            self.is_store.eq(0),
            self.is_branch.eq(0),
            self.is_jal.eq(0),
            self.is_jalr.eq(0),
            self.is_fence.eq(0),
            self.is_gc.eq(0),
            self.gc_op.eq(0),
            self.gc_rd.eq(0),
            self.gc_rs1.eq(0),
            self.gc_rs2.eq(0),
            self.gc_is_reloc.eq(0),
        ]

        is_set_clear_invert = (
            (self.funct3 == 0b001) &
            ((self.funct7 == 0b0010100) |
             (self.funct7 == 0b0100100) |
             (self.funct7 == 0b0110100))
        )
        is_extract = (self.funct3 == 0b101) & (self.funct7 == 0b0100100)
        is_zbs_r = self.valid & (self.opcode == OP) & (is_set_clear_invert | is_extract)
        is_zbs_i = self.valid & (self.opcode == OP_IMM) & (is_set_clear_invert | is_extract)

        m.d.comb += self.matched.eq(is_zbs_r | is_zbs_i)

        bit_pos = Signal(6 if self._xlen >= 64 else 5)
        m.d.comb += bit_pos.eq(Mux(
            is_zbs_r,
            self.ex1_b[0:6] if self._xlen >= 64 else self.ex1_b[0:5],
            self.imm[0:6] if self._xlen >= 64 else self.imm[0:5],
        ))

        sh_one = Signal(self._xlen)
        m.d.comb += sh_one.eq(1 << bit_pos)

        with m.If(self.matched):
            m.d.comb += self.wb_en.eq(1)
            with m.If(self.funct7 == 0b0010100):
                m.d.comb += self.wb_data.eq(self.ex1_a | sh_one)
            with m.Elif((self.funct7 == 0b0100100) & (self.funct3 == 0b001)):
                m.d.comb += self.wb_data.eq(self.ex1_a & ~sh_one)
            with m.Elif(self.funct7 == 0b0110100):
                m.d.comb += self.wb_data.eq(self.ex1_a ^ sh_one)
            with m.Else():
                m.d.comb += self.wb_data.eq((self.ex1_a >> bit_pos) & 1)

        return m
