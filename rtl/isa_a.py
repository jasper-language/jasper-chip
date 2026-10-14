from amaranth import *

from .isa_module import ISAExtension
from .isa import AMO


class A(ISAExtension):
    def __init__(self, xlen=32):
        super().__init__(xlen=xlen, name="a")
        self._xlen = xlen

    def elaborate(self, platform):
        m = Module()

        m.d.comb += [
            self.matched.eq(0),
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

        is_amo = self.valid & (self.opcode == AMO) & (self.funct3 == 0b010)
        m.d.comb += self.matched.eq(is_amo)

        funct5 = Signal(5)
        m.d.comb += funct5.eq(self.funct7 >> 2)

        with m.If(is_amo):
            m.d.comb += [
                self.wb_en.eq(1),
                self.mem_addr.eq(self.ex1_a),
            ]

            with m.Switch(funct5):
                with m.Case(0b00010):
                    m.d.comb += self.is_load.eq(1)

                with m.Case(0b00011):
                    m.d.comb += [
                        self.is_store.eq(1),
                        self.mem_wdata.eq(self.ex1_b),
                        self.wb_data.eq(0),
                    ]

                with m.Case(0b00000):
                    m.d.comb += [
                        self.is_load.eq(1),
                        self.is_store.eq(1),
                        self.alu_out.eq(self.ex1_a + self.ex1_b),
                        self.mem_wdata.eq(self.alu_out),
                    ]

                with m.Case(0b00001):
                    m.d.comb += [
                        self.is_load.eq(1),
                        self.is_store.eq(1),
                        self.alu_out.eq(self.ex1_b),
                        self.mem_wdata.eq(self.alu_out),
                    ]

                with m.Case(0b01100):
                    m.d.comb += [
                        self.is_load.eq(1),
                        self.is_store.eq(1),
                        self.alu_out.eq(self.ex1_a & self.ex1_b),
                        self.mem_wdata.eq(self.alu_out),
                    ]

                with m.Case(0b01000):
                    m.d.comb += [
                        self.is_load.eq(1),
                        self.is_store.eq(1),
                        self.alu_out.eq(self.ex1_a | self.ex1_b),
                        self.mem_wdata.eq(self.alu_out),
                    ]

                with m.Case(0b00100):
                    m.d.comb += [
                        self.is_load.eq(1),
                        self.is_store.eq(1),
                        self.alu_out.eq(self.ex1_a ^ self.ex1_b),
                        self.mem_wdata.eq(self.alu_out),
                    ]

                with m.Case(0b10000):
                    m.d.comb += [self.is_load.eq(1), self.is_store.eq(1)]
                    with m.If(self.ex1_a.as_signed() <= self.ex1_b.as_signed()):
                        m.d.comb += self.alu_out.eq(self.ex1_a)
                    with m.Else():
                        m.d.comb += self.alu_out.eq(self.ex1_b)
                    m.d.comb += self.mem_wdata.eq(self.alu_out)

                with m.Case(0b10100):
                    m.d.comb += [self.is_load.eq(1), self.is_store.eq(1)]
                    with m.If(self.ex1_a.as_signed() >= self.ex1_b.as_signed()):
                        m.d.comb += self.alu_out.eq(self.ex1_a)
                    with m.Else():
                        m.d.comb += self.alu_out.eq(self.ex1_b)
                    m.d.comb += self.mem_wdata.eq(self.alu_out)

                with m.Case(0b11000):
                    m.d.comb += [self.is_load.eq(1), self.is_store.eq(1)]
                    with m.If(self.ex1_a <= self.ex1_b):
                        m.d.comb += self.alu_out.eq(self.ex1_a)
                    with m.Else():
                        m.d.comb += self.alu_out.eq(self.ex1_b)
                    m.d.comb += self.mem_wdata.eq(self.alu_out)

                with m.Case(0b11100):
                    m.d.comb += [self.is_load.eq(1), self.is_store.eq(1)]
                    with m.If(self.ex1_a >= self.ex1_b):
                        m.d.comb += self.alu_out.eq(self.ex1_a)
                    with m.Else():
                        m.d.comb += self.alu_out.eq(self.ex1_b)
                    m.d.comb += self.mem_wdata.eq(self.alu_out)

        return m
