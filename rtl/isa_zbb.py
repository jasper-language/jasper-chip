from amaranth import *

from .isa_module import ISAExtension
from .isa import OP


class Zbb(ISAExtension):
    def __init__(self, xlen=32):
        super().__init__(xlen=xlen, name="zbb")
        self._xlen = xlen

    def elaborate(self, platform):
        m = Module()
        XLEN = self._xlen

        m.d.comb += [
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

        is_subop = (self.opcode == OP) & (self.funct7 == 0b0110000) & (self.funct3 == 0b001) & \
                   ((self.rs2 == 0b00000) | (self.rs2 == 0b00001) | (self.rs2 == 0b00010))
        is_sext = (self.opcode == OP) & (self.funct7 == 0b0110000) & (self.funct3 == 0b100) & \
                  ((self.rs2 == 0b00100) | (self.rs2 == 0b00101) | (self.rs2 == 0b00110))
        is_rev8 = (self.opcode == OP) & (self.funct7 == 0b0110101) & (self.funct3 == 0b101) & (self.rs2 == 0b00111)
        is_minmax = (self.opcode == OP) & (self.funct7 == 0b0000101) & \
                    ((self.funct3 == 0b100) | (self.funct3 == 0b101) | (self.funct3 == 0b110) | (self.funct3 == 0b111))
        is_orcb = (self.opcode == OP) & (self.funct7 == 0b0010101) & (self.funct3 == 0b111)

        any_match = is_subop | is_sext | is_rev8 | is_minmax | is_orcb
        m.d.comb += self.matched.eq(self.valid & any_match)

        alu_result = Signal(XLEN)
        m.d.comb += alu_result.eq(0)

        with m.If(is_subop & self.valid):
            with m.Switch(self.rs2):
                with m.Case(0b00000):  # CLZ
                    clz = Signal(6)
                    clz_val = C(XLEN, 6)
                    for i in range(XLEN):
                        clz_val = Mux(self.ex1_a[i], C(XLEN - 1 - i, 6), clz_val)
                    m.d.comb += clz.eq(clz_val)
                    m.d.comb += alu_result.eq(clz)
                with m.Case(0b00001):  # CTZ
                    ctz = Signal(6)
                    ctz_val = C(XLEN, 6)
                    for i in range(XLEN):
                        ctz_val = Mux(self.ex1_a[XLEN - 1 - i], C(XLEN - 1 - i, 6), ctz_val)
                    m.d.comb += ctz.eq(ctz_val)
                    m.d.comb += alu_result.eq(ctz)
                with m.Case(0b00010):  # CPOP
                    pcount = Signal(6)
                    pop = self.ex1_a[0]
                    for i in range(1, XLEN):
                        pop = pop + self.ex1_a[i]
                    m.d.comb += pcount.eq(pop)
                    m.d.comb += alu_result.eq(pcount)

        with m.Elif(is_sext & self.valid):
            with m.Switch(self.rs2):
                with m.Case(0b00100):  # SEXT_B
                    m.d.comb += alu_result.eq(
                        Cat(self.ex1_a[0:8], *[self.ex1_a[7]] * (XLEN - 8))
                    )
                with m.Case(0b00101):  # SEXT_H
                    m.d.comb += alu_result.eq(
                        Cat(self.ex1_a[0:16], *[self.ex1_a[15]] * (XLEN - 16))
                    )
                with m.Case(0b00110):  # ZEXT_H
                    m.d.comb += alu_result.eq(
                        Cat(self.ex1_a[0:16], C(0, XLEN - 16))
                    )

        with m.Elif(is_rev8 & self.valid):
            if XLEN == 32:
                m.d.comb += alu_result.eq(Cat(
                    self.ex1_a[24:32],
                    self.ex1_a[16:24],
                    self.ex1_a[8:16],
                    self.ex1_a[0:8],
                ))
            else:
                m.d.comb += alu_result.eq(Cat(
                    self.ex1_a[56:64],
                    self.ex1_a[48:56],
                    self.ex1_a[40:48],
                    self.ex1_a[32:40],
                    self.ex1_a[24:32],
                    self.ex1_a[16:24],
                    self.ex1_a[8:16],
                    self.ex1_a[0:8],
                ))

        with m.Elif(is_minmax & self.valid):
            with m.Switch(self.funct3):
                with m.Case(0b100):  # MIN (signed)
                    a_lt_b = Signal()
                    rest_lt = Signal()
                    m.d.comb += rest_lt.eq(
                        self.ex1_a[0:XLEN - 1].as_unsigned() < self.ex1_b[0:XLEN - 1].as_unsigned()
                    )
                    m.d.comb += a_lt_b.eq(
                        (self.ex1_a[XLEN - 1] & ~self.ex1_b[XLEN - 1]) |
                        (~(self.ex1_a[XLEN - 1] ^ self.ex1_b[XLEN - 1]) & rest_lt)
                    )
                    m.d.comb += alu_result.eq(Mux(a_lt_b, self.ex1_a, self.ex1_b))
                with m.Case(0b101):  # MINU (unsigned)
                    ult = Signal()
                    m.d.comb += ult.eq(self.ex1_a.as_unsigned() < self.ex1_b.as_unsigned())
                    m.d.comb += alu_result.eq(Mux(ult, self.ex1_a, self.ex1_b))
                with m.Case(0b110):  # MAX (signed)
                    a_lt_b = Signal()
                    rest_lt = Signal()
                    m.d.comb += rest_lt.eq(
                        self.ex1_a[0:XLEN - 1].as_unsigned() < self.ex1_b[0:XLEN - 1].as_unsigned()
                    )
                    m.d.comb += a_lt_b.eq(
                        (self.ex1_a[XLEN - 1] & ~self.ex1_b[XLEN - 1]) |
                        (~(self.ex1_a[XLEN - 1] ^ self.ex1_b[XLEN - 1]) & rest_lt)
                    )
                    m.d.comb += alu_result.eq(Mux(a_lt_b, self.ex1_b, self.ex1_a))
                with m.Case(0b111):  # MAXU (unsigned)
                    ult = Signal()
                    m.d.comb += ult.eq(self.ex1_a.as_unsigned() < self.ex1_b.as_unsigned())
                    m.d.comb += alu_result.eq(Mux(ult, self.ex1_b, self.ex1_a))

        with m.Elif(is_orcb & self.valid):
            if XLEN == 32:
                b0 = Signal()
                b1 = Signal()
                b2 = Signal()
                b3 = Signal()
                m.d.comb += b0.eq(self.ex1_a[0] | self.ex1_a[1] | self.ex1_a[2] | self.ex1_a[3] |
                                  self.ex1_a[4] | self.ex1_a[5] | self.ex1_a[6] | self.ex1_a[7])
                m.d.comb += b1.eq(self.ex1_a[8] | self.ex1_a[9] | self.ex1_a[10] | self.ex1_a[11] |
                                  self.ex1_a[12] | self.ex1_a[13] | self.ex1_a[14] | self.ex1_a[15])
                m.d.comb += b2.eq(self.ex1_a[16] | self.ex1_a[17] | self.ex1_a[18] | self.ex1_a[19] |
                                  self.ex1_a[20] | self.ex1_a[21] | self.ex1_a[22] | self.ex1_a[23])
                m.d.comb += b3.eq(self.ex1_a[24] | self.ex1_a[25] | self.ex1_a[26] | self.ex1_a[27] |
                                  self.ex1_a[28] | self.ex1_a[29] | self.ex1_a[30] | self.ex1_a[31])
                m.d.comb += alu_result.eq(Cat(*[b0] * 8, *[b1] * 8, *[b2] * 8, *[b3] * 8))

        m.d.comb += [
            self.wb_en.eq(self.matched),
            self.wb_data.eq(alu_result),
        ]

        return m
