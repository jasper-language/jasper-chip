from functools import reduce
from amaranth import *

from .isa_module import ISAExtension
from .isa import OP


class Zbc(ISAExtension):
    def __init__(self, xlen=32):
        super().__init__(xlen=xlen, name="zbc")

    def elaborate(self, platform):
        m = Module()
        XLEN = self.xlen

        m.d.comb += [
            self.matched.eq(
                self.valid & (self.opcode == OP) & (self.funct7 == 0b0000101) &
                ((self.funct3 == 0b001) | (self.funct3 == 0b011) | (self.funct3 == 0b010))
            ),
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

        # Carry-less multiply: XOR all partial products (no carries)
        prod = Signal(2 * XLEN)
        terms = []
        for i in range(XLEN):
            terms.append(Mux(self.ex1_b[i], self.ex1_a << i, 0))
        m.d.comb += prod.eq(reduce(lambda a, b: a ^ b, terms))

        clmul  = prod[0:XLEN]
        clmulh = prod[XLEN:2 * XLEN]

        # CLMULR returns the XLEN-bit product window shifted right by XLEN-1.
        clmulr = prod[XLEN - 1:2 * XLEN - 1]

        with m.Switch(self.funct3):
            with m.Case(0b001):
                m.d.comb += [
                    self.alu_out.eq(clmul),
                    self.wb_en.eq(1),
                    self.wb_data.eq(clmul),
                ]
            with m.Case(0b011):
                m.d.comb += [
                    self.alu_out.eq(clmulh),
                    self.wb_en.eq(1),
                    self.wb_data.eq(clmulh),
                ]
            with m.Case(0b010):
                m.d.comb += [
                    self.alu_out.eq(clmulr),
                    self.wb_en.eq(1),
                    self.wb_data.eq(clmulr),
                ]

        return m
