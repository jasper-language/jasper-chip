"""RV32 Zksh scalar SM3 permutation instructions."""

from amaranth import Module

from .isa import OP_IMM
from .isa_module import ISAExtension


class Zksh(ISAExtension):
    """Execute the complete SM3P0 and SM3P1 instruction set."""

    def __init__(self, xlen=32):
        if xlen != 32:
            raise ValueError("RV32 Zksh execution requires xlen=32")
        super().__init__(xlen=xlen, name="zksh")

    @staticmethod
    def _rol32(value, amount):
        return (value << amount) | (value >> (32 - amount))

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
        is_sm3 = (
            self.valid & (self.opcode == OP_IMM) & (self.funct7 == 0b0001000)
            & (self.funct3 == 0b001) & ((self.rs2 == 8) | (self.rs2 == 9))
        )
        m.d.comb += self.matched.eq(is_sm3)
        with m.If(self.matched):
            m.d.comb += self.wb_en.eq(1)
            with m.If(self.rs2 == 8):  # SM3P0
                m.d.comb += self.wb_data.eq(
                    self.ex1_a ^ self._rol32(self.ex1_a, 9) ^ self._rol32(self.ex1_a, 17)
                )
            with m.Else():  # SM3P1
                m.d.comb += self.wb_data.eq(
                    self.ex1_a ^ self._rol32(self.ex1_a, 15) ^ self._rol32(self.ex1_a, 23)
                )
        m.d.comb += self.alu_out.eq(self.wb_data)
        return m
