from amaranth import *

from .isa_module import ISAExtension
from .isa import OP


class Zicond(ISAExtension):
    def __init__(self, xlen=32):
        super().__init__(xlen=xlen, name="zicond")

    def elaborate(self, platform):
        m = Module()

        is_eqz = self.funct3 == 0b101
        is_nez = self.funct3 == 0b111
        matched = (
            self.valid
            & (self.opcode == OP)
            & (self.funct7 == 0b0000111)
            & (is_eqz | is_nez)
        )
        zero_result = (is_eqz & (self.ex1_b == 0)) | (is_nez & (self.ex1_b != 0))

        m.d.comb += [
            self.matched.eq(matched),
            self.alu_out.eq(Mux(matched, Mux(zero_result, 0, self.ex1_a), 0)),
            self.wb_en.eq(matched),
            self.wb_data.eq(Mux(matched, Mux(zero_result, 0, self.ex1_a), 0)),
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

        return m
