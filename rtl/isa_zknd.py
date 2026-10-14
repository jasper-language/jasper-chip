"""RV32 Zknd scalar AES decryption instructions."""

from amaranth import Module

from .aes32 import aes32_result
from .isa import OP
from .isa_module import ISAExtension


class Zknd(ISAExtension):
    """Execute AES32DSI and AES32DSMI for all four byte selectors."""

    def __init__(self, xlen=32):
        if xlen != 32:
            raise ValueError("RV32 Zknd execution requires xlen=32")
        super().__init__(xlen=xlen, name="zknd")

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
        funct5 = self.funct7[0:5]
        is_dsi = funct5 == 0b10101
        is_dsmi = funct5 == 0b10111
        m.d.comb += self.matched.eq(
            self.valid & (self.opcode == OP) & (self.funct3 == 0) & (is_dsi | is_dsmi)
        )
        with m.If(self.matched):
            m.d.comb += [
                self.wb_en.eq(1),
                self.wb_data.eq(aes32_result(
                    self.ex1_a, self.ex1_b, self.funct7, inverse=True, mix=is_dsmi
                )),
            ]
        m.d.comb += self.alu_out.eq(self.wb_data)
        return m
