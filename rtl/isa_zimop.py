"""Zimop may-be-operation instruction execution."""

from amaranth import Module

from .isa import SYSTEM
from .isa_module import ISAExtension


class Zimop(ISAExtension):
    """Execute all 32 MOP.R and all 8 MOP.RR standard encodings."""

    def __init__(self, xlen=32):
        super().__init__(xlen=xlen, name="zimop")

    def elaborate(self, platform):
        m = Module()
        m.d.comb += [
            self.matched.eq(0), self.wb_en.eq(0), self.wb_data.eq(0), self.alu_out.eq(0),
            self.mem_addr.eq(0), self.mem_wdata.eq(0), self.redirect.eq(0), self.redirect_pc.eq(0),
            self.trap.eq(0), self.br_valid.eq(0), self.br_pc.eq(0), self.br_target.eq(0),
            self.br_taken.eq(0), self.br_is_branch.eq(0), self.br_is_jal.eq(0),
            self.br_is_jalr.eq(0), self.is_load.eq(0), self.is_store.eq(0),
            self.is_branch.eq(0), self.is_jal.eq(0), self.is_jalr.eq(0), self.is_fence.eq(0),
            self.is_gc.eq(0), self.gc_op.eq(0), self.gc_rd.eq(0), self.gc_rs1.eq(0),
            self.gc_rs2.eq(0), self.gc_is_reloc.eq(0),
        ]
        common = (
            self.valid & (self.opcode == SYSTEM) & (self.funct3 == 0b100)
            & self.funct7[6] & (self.funct7[3:5] == 0)
        )
        is_mop_r = ~self.funct7[0] & (self.rs2[2:5] == 0b111)
        is_mop_rr = self.funct7[0]
        m.d.comb += self.matched.eq(common & (is_mop_r | is_mop_rr))
        with m.If(self.matched):
            m.d.comb += [self.wb_en.eq(1), self.wb_data.eq(0)]
        return m
