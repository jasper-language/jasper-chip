from amaranth import *

from .isa_module import ISAExtension
from .isa import OP


class RV32M(ISAExtension):
    def __init__(self, xlen=32):
        super().__init__(xlen=xlen, name="rv32m")
        self._xlen = xlen

    def elaborate(self, platform):
        m = Module()

        m.d.comb += [
            self.matched.eq(self.valid & (self.opcode == OP) & (self.funct7 == 0b0000001)),
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

        mul_result = Signal(64)
        min_s32 = Const(0x80000000, 32)
        neg1_s32 = Const(0xFFFFFFFF, 32)

        with m.Switch(self.funct3):
            with m.Case(0b000):
                m.d.comb += mul_result.eq(self.ex1_a.as_signed() * self.ex1_b.as_signed())
                m.d.comb += [
                    self.wb_en.eq(1),
                    self.wb_data.eq(mul_result[0:32]),
                ]
            with m.Case(0b001):
                m.d.comb += mul_result.eq(self.ex1_a.as_signed() * self.ex1_b.as_signed())
                m.d.comb += [
                    self.wb_en.eq(1),
                    self.wb_data.eq(mul_result[32:64]),
                ]
            with m.Case(0b010):
                mula = Signal(signed(32))
                mulb = Signal(32)
                m.d.comb += [
                    mula.eq(self.ex1_a.as_signed()),
                    mulb.eq(self.ex1_b),
                ]
                m.d.comb += mul_result.eq(mula * mulb)
                m.d.comb += [
                    self.wb_en.eq(1),
                    self.wb_data.eq(mul_result[32:64]),
                ]
            with m.Case(0b011):
                m.d.comb += mul_result.eq(self.ex1_a * self.ex1_b)
                m.d.comb += [
                    self.wb_en.eq(1),
                    self.wb_data.eq(mul_result[32:64]),
                ]
            with m.Case(0b100):
                a_abs = Signal(32)
                b_abs = Signal(32)
                q_abs = Signal(32)
                neg_a = Signal(32)
                neg_b = Signal(32)
                neg_q = Signal(32)
                sign = Signal()
                m.d.comb += [
                    sign.eq(self.ex1_a[31] ^ self.ex1_b[31]),
                    neg_a.eq((~self.ex1_a) + 1),
                    neg_b.eq((~self.ex1_b) + 1),
                    a_abs.eq(Mux(self.ex1_a[31], neg_a, self.ex1_a)),
                    b_abs.eq(Mux(self.ex1_b[31], neg_b, self.ex1_b)),
                    q_abs.eq(a_abs // b_abs),
                    neg_q.eq((~q_abs) + 1),
                ]
                with m.If(self.ex1_b == 0):
                    m.d.comb += [
                        self.wb_en.eq(1),
                        self.wb_data.eq(neg1_s32),
                    ]
                with m.Elif((self.ex1_a == min_s32) & (self.ex1_b.as_signed() == Const(-1, signed(32)))):
                    m.d.comb += [
                        self.wb_en.eq(1),
                        self.wb_data.eq(min_s32),
                    ]
                with m.Else():
                    m.d.comb += [
                        self.wb_en.eq(1),
                        self.wb_data.eq(Mux(sign, neg_q, q_abs)),
                    ]
            with m.Case(0b101):
                with m.If(self.ex1_b == 0):
                    m.d.comb += [
                        self.wb_en.eq(1),
                        self.wb_data.eq(neg1_s32),
                    ]
                with m.Else():
                    m.d.comb += [
                        self.wb_en.eq(1),
                        self.wb_data.eq(self.ex1_a.as_unsigned() // self.ex1_b.as_unsigned()),
                    ]
            with m.Case(0b110):
                a_abs = Signal(32)
                b_abs = Signal(32)
                q_abs = Signal(32)
                neg_a = Signal(32)
                neg_b = Signal(32)
                neg_q = Signal(32)
                div_result = Signal(32)
                sign = Signal()
                m.d.comb += [
                    sign.eq(self.ex1_a[31] ^ self.ex1_b[31]),
                    neg_a.eq((~self.ex1_a) + 1),
                    neg_b.eq((~self.ex1_b) + 1),
                    a_abs.eq(Mux(self.ex1_a[31], neg_a, self.ex1_a)),
                    b_abs.eq(Mux(self.ex1_b[31], neg_b, self.ex1_b)),
                    q_abs.eq(a_abs // b_abs),
                    neg_q.eq((~q_abs) + 1),
                    div_result.eq(Mux(sign, neg_q, q_abs)),
                ]
                with m.If(self.ex1_b == 0):
                    m.d.comb += [
                        self.wb_en.eq(1),
                        self.wb_data.eq(self.ex1_a),
                    ]
                with m.Elif((self.ex1_a == min_s32) & (self.ex1_b.as_signed() == Const(-1, signed(32)))):
                    m.d.comb += [
                        self.wb_en.eq(1),
                        self.wb_data.eq(0),
                    ]
                with m.Else():
                    m.d.comb += [
                        self.wb_en.eq(1),
                        self.wb_data.eq(self.ex1_a - (div_result * self.ex1_b)),
                    ]
            with m.Case(0b111):
                with m.If(self.ex1_b == 0):
                    m.d.comb += [
                        self.wb_en.eq(1),
                        self.wb_data.eq(self.ex1_a),
                    ]
                with m.Else():
                    m.d.comb += [
                        self.wb_en.eq(1),
                        self.wb_data.eq(self.ex1_a.as_unsigned() % self.ex1_b.as_unsigned()),
                    ]

        return m
