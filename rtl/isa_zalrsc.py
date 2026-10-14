from amaranth import *

from .isa_module import ISAExtension
from .isa import AMO


class Zalrsc(ISAExtension):
    def __init__(self, xlen=32):
        super().__init__(xlen=xlen, name="zalrsc")
        self._xlen = xlen

    def elaborate(self, platform):
        m = Module()

        funct5 = self.funct7[2:7]
        is_lr = (funct5 == 0b00010) & (self.rs2 == 0)
        is_sc = funct5 == 0b00011
        is_lrsc = (
            self.valid
            & (self.opcode == AMO)
            & (self.funct3 == 0b010)
            & (is_lr | is_sc)
        )

        m.d.comb += [
            self.matched.eq(is_lrsc),
            self.wb_en.eq(0),
            self.wb_data.eq(0),
            self.alu_out.eq(0),
            self.mem_addr.eq(0),
            self.mem_wdata.eq(0),
            self.redirect.eq(0),
            self.redirect_pc.eq(0),
            self.trap.eq(0),
            self.bp_mispredict.eq(0),
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

        with m.If(is_lrsc):
            m.d.comb += self.mem_addr.eq(self.ex1_a)
            with m.If(is_lr):
                m.d.comb += self.is_load.eq(1)
            with m.Else():
                m.d.comb += [
                    self.is_store.eq(1),
                    self.mem_wdata.eq(self.ex1_b),
                ]

        return m
