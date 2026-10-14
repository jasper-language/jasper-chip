from amaranth import *

from .isa import OP, OP_IMM, LOAD, STORE


class ZC(Elaboratable):
    def __init__(self, xlen=32):
        self.xlen = xlen

        self.insn16 = Signal(16)
        self.c_expanded = Signal(32)
        self.c_is_compressed = Signal()

        self.override_insn32 = Signal(32)
        self.override_valid = Signal()
        self.override_illegal = Signal()

    def elaborate(self, platform):
        m = Module()

        i16 = self.insn16
        op = i16[0:2]
        funct3 = i16[13:16]
        funct2 = i16[10:12]

        rd_s  = (C(8, 5) + i16[2:5])[:5]
        rs1_s = (C(8, 5) + i16[7:10])[:5]
        rs2_s = (C(8, 5) + i16[2:5])[:5]

        is_insn16 = (op != 0b11)
        is_zcb_q0 = is_insn16 & (op == 0b00) & (funct3 == 0b100)
        is_zcb_q1 = is_insn16 & (op == 0b01) & (funct3 == 0b100) & (funct2 == 0b11) & i16[12]

        is_zc = is_zcb_q0 | is_zcb_q1

        m.d.comb += [
            self.override_insn32.eq(0),
            self.override_valid.eq(0),
            self.override_illegal.eq(1),
        ]

        with m.If(is_zc):
            with m.If(is_zcb_q0):
                funct2_zcb = i16[10:12]
                with m.Switch(funct2_zcb):
                    with m.Case(0b00):
                        lb_imm = Cat(i16[6:7], i16[5:6], C(0, 10))
                        m.d.comb += self.override_insn32.eq(
                            Cat(C(LOAD, 7), rd_s, C(0b100, 3), rs1_s, lb_imm))
                        m.d.comb += self.override_illegal.eq(0)
                    with m.Case(0b01):
                        with m.If(~i16[6]):
                            lhu_imm = Cat(C(0, 1), i16[5:6], C(0, 10))
                            m.d.comb += self.override_insn32.eq(
                                Cat(C(LOAD, 7), rd_s, C(0b101, 3), rs1_s, lhu_imm))
                            m.d.comb += self.override_illegal.eq(0)
                        with m.Else():
                            lh_imm = Cat(C(0, 1), i16[5:6], C(0, 10))
                            m.d.comb += self.override_insn32.eq(
                                Cat(C(LOAD, 7), rd_s, C(0b001, 3), rs1_s, lh_imm))
                            m.d.comb += self.override_illegal.eq(0)
                    with m.Case(0b10):
                        sb_imm = Cat(i16[6:7], i16[5:6], C(0, 10))
                        m.d.comb += self.override_insn32.eq(
                            Cat(C(STORE, 7), sb_imm[0:5], C(0b000, 3), rs1_s, rs2_s, sb_imm[5:12]))
                        m.d.comb += self.override_illegal.eq(0)
                    with m.Case(0b11):
                        sh_imm = Cat(C(0, 1), i16[5:6], C(0, 10))
                        m.d.comb += self.override_insn32.eq(
                            Cat(C(STORE, 7), sh_imm[0:5], C(0b001, 3), rs1_s, rs2_s, sh_imm[5:12]))
                        m.d.comb += self.override_illegal.eq(0)
                    with m.Default():
                        m.d.comb += self.override_illegal.eq(1)
            with m.Else():
                op5 = i16[5:7]
                with m.Switch(op5):
                    with m.Case(0b10):
                        m.d.comb += self.override_insn32.eq(
                            Cat(C(OP, 7), rs1_s, C(0, 3), rs1_s, rs2_s, C(0b0000001, 7)))
                        m.d.comb += self.override_illegal.eq(0)
                    with m.Case(0b11):
                        with m.Switch(i16[2:5]):
                            with m.Case(0b000):
                                m.d.comb += self.override_insn32.eq(
                                    Cat(C(OP_IMM, 7), rs1_s,
                                        C(0b111, 3), rs1_s, C(0xFF, 12)))
                                m.d.comb += self.override_illegal.eq(0)
                            with m.Case(0b001):
                                m.d.comb += self.override_insn32.eq(
                                    Cat(C(OP_IMM, 7), rs1_s,
                                        C(0b001, 3), rs1_s, C(0x604, 12)))
                                m.d.comb += self.override_illegal.eq(0)
                            with m.Case(0b010):
                                m.d.comb += self.override_insn32.eq(
                                    Cat(C(OP, 7), rs1_s,
                                        C(0b100, 3), rs1_s,
                                        C(0, 5), C(0b0000100, 7)))
                                m.d.comb += self.override_illegal.eq(0)
                            with m.Case(0b011):
                                m.d.comb += self.override_insn32.eq(
                                    Cat(C(OP_IMM, 7), rs1_s,
                                        C(0b001, 3), rs1_s, C(0x605, 12)))
                                m.d.comb += self.override_illegal.eq(0)
                            with m.Case(0b101):
                                m.d.comb += self.override_insn32.eq(
                                    Cat(C(OP_IMM, 7), rs1_s,
                                        C(0b100, 3), rs1_s, C(0xFFF, 12)))
                                m.d.comb += self.override_illegal.eq(0)
                            with m.Default():
                                m.d.comb += self.override_illegal.eq(1)
                    with m.Default():
                        m.d.comb += self.override_illegal.eq(1)
            m.d.comb += self.override_valid.eq(~self.override_illegal)

        return m
