from amaranth import *

from .isa_module import ISAExtension
from .isa import OP


class Zmmul(ISAExtension):
    def __init__(self, xlen=32):
        super().__init__(xlen=xlen, name="zmmul")

    def elaborate(self, platform):
        m = Module()

        is_mul = (self.opcode == OP) & (self.funct7 == 0b0000001) & \
                 ((self.funct3 == 0b000) | (self.funct3 == 0b001) |
                  (self.funct3 == 0b010) | (self.funct3 == 0b011))
        m.d.comb += self.matched.eq(self.valid & is_mul)

        m.d.comb += [
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

        signed_product = Signal(signed(2 * self.xlen))
        mixed_product = Signal(signed(2 * self.xlen + 2))
        unsigned_product = Signal(2 * self.xlen)
        signed_a = Cat(self.ex1_a, self.ex1_a[-1]).as_signed()
        unsigned_b = Cat(self.ex1_b, Const(0, 1)).as_signed()
        m.d.comb += [
            signed_product.eq(self.ex1_a.as_signed() * self.ex1_b.as_signed()),
            mixed_product.eq(signed_a * unsigned_b),
            unsigned_product.eq(self.ex1_a * self.ex1_b),
        ]

        with m.If(self.matched):
            m.d.comb += self.wb_en.eq(1)
            with m.Switch(self.funct3):
                with m.Case(0b000):
                    m.d.comb += [
                        self.wb_data.eq(signed_product[:self.xlen]),
                        self.alu_out.eq(signed_product[:self.xlen]),
                    ]
                with m.Case(0b001):
                    m.d.comb += [
                        self.wb_data.eq(signed_product[self.xlen:2 * self.xlen]),
                        self.alu_out.eq(signed_product[self.xlen:2 * self.xlen]),
                    ]
                with m.Case(0b010):
                    m.d.comb += [
                        self.wb_data.eq(mixed_product[self.xlen:2 * self.xlen]),
                        self.alu_out.eq(mixed_product[self.xlen:2 * self.xlen]),
                    ]
                with m.Case(0b011):
                    m.d.comb += [
                        self.wb_data.eq(unsigned_product[self.xlen:2 * self.xlen]),
                        self.alu_out.eq(unsigned_product[self.xlen:2 * self.xlen]),
                    ]

        return m
