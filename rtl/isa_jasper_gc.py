from amaranth import *

from .isa_module import ISAExtension
from .isa import CUSTOM0, GC_RELOC, GC_MV_RELOC


class JasperGC(ISAExtension):
    def __init__(self, xlen=32, opcode=CUSTOM0):
        super().__init__(xlen=xlen, name="jasper_gc")
        self._gc_opcode = opcode
        self.gc_fwd_rs1 = Signal(xlen, name="gc_fwd_rs1")
        self.gc_fwd_rs2 = Signal(xlen, name="gc_fwd_rs2")

    def elaborate(self, platform):
        m = Module()

        opcode_match = Signal()
        m.d.comb += opcode_match.eq(self.valid & (self.opcode == self._gc_opcode))

        m.d.comb += [
            self.matched.eq(opcode_match),
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
            self.is_gc.eq(opcode_match),
            self.gc_op.eq(self.funct3),
            self.gc_rd.eq(self.rd),
            self.gc_rs1.eq(self.gc_fwd_rs1),
            self.gc_rs2.eq(self.gc_fwd_rs2),
            self.gc_is_reloc.eq((self.funct3 == GC_RELOC) | (self.funct3 == GC_MV_RELOC)),
        ]

        return m
