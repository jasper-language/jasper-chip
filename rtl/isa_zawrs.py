"""Zawrs wait-on-reservation-set instructions."""

from amaranth import Module

from .isa import SYSTEM
from .isa_module import ISAExtension


class Zawrs(ISAExtension):
    """Recognize WRS.NTO/WRS.STO and legally resume immediately.

    The architecture permits both instructions to terminate their wait for any
    implementation-defined reason. This implementation takes that permitted
    path while preserving exact decoding and architectural side effects.
    """

    def __init__(self, xlen=32):
        super().__init__(xlen=xlen, name="zawrs")

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
        exact_system_form = (
            self.valid & (self.opcode == SYSTEM) & (self.funct3 == 0)
            & (self.rd == 0) & (self.rs1 == 0)
        )
        m.d.comb += self.matched.eq(
            exact_system_form & ((self.imm[0:12] == 0x00D) | (self.imm[0:12] == 0x01D))
        )
        return m
