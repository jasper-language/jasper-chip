"""RV32 Zknh scalar SHA-2 instruction execution unit."""

from amaranth import C, Elaboratable, Module, Signal


OP_IMM = 0x13
OP = 0x33


class Zknh(Elaboratable):
    """Execute the complete RV32 Zknh instruction set.

    Zknh contains four unary SHA-256 operations and six RV32-only
    two-register operations used to implement SHA-512 with register pairs.
    """

    def __init__(self, xlen=32):
        if xlen != 32:
            raise ValueError("Zknh RV32 execution unit requires xlen=32")

        self.xlen = xlen
        self.valid = Signal()
        self.opcode = Signal(7)
        self.funct3 = Signal(3)
        self.funct7 = Signal(7)
        self.rs1 = Signal(5)
        self.rs2 = Signal(5)
        self.rd = Signal(5)
        self.rs1v = Signal(32)
        self.rs2v = Signal(32)

        self.matched = Signal()
        self.wb_en = Signal()
        self.wb_data = Signal(32)
        self.alu_out = Signal(32)
        self.bp_mispredict = Signal()

    @staticmethod
    def _ror32(value, amount):
        return (value >> amount) | (value << (32 - amount))

    def elaborate(self, platform):
        m = Module()
        a = self.rs1v
        b = self.rs2v

        m.d.comb += [
            self.matched.eq(0),
            self.wb_en.eq(0),
            self.wb_data.eq(0),
            self.alu_out.eq(0),
            self.bp_mispredict.eq(0),
        ]

        sha256 = (
            self.valid
            & (self.opcode == OP_IMM)
            & (self.funct7 == 0b0001000)
            & (self.funct3 == 0b001)
            & (self.rs2 < 4)
        )
        sha512 = (
            self.valid
            & (self.opcode == OP)
            & (self.funct3 == 0b000)
            & (
                (self.funct7 == 0b0101000)
                | (self.funct7 == 0b0101001)
                | (self.funct7 == 0b0101010)
                | (self.funct7 == 0b0101110)
                | (self.funct7 == 0b0101011)
                | (self.funct7 == 0b0101111)
            )
        )

        with m.If(sha256):
            m.d.comb += [self.matched.eq(1), self.wb_en.eq(1)]
            with m.Switch(self.rs2):
                with m.Case(0):  # SHA256SUM0
                    m.d.comb += self.wb_data.eq(
                        self._ror32(a, 2) ^ self._ror32(a, 13) ^ self._ror32(a, 22)
                    )
                with m.Case(1):  # SHA256SUM1
                    m.d.comb += self.wb_data.eq(
                        self._ror32(a, 6) ^ self._ror32(a, 11) ^ self._ror32(a, 25)
                    )
                with m.Case(2):  # SHA256SIG0
                    m.d.comb += self.wb_data.eq(
                        self._ror32(a, 7) ^ self._ror32(a, 18) ^ (a >> 3)
                    )
                with m.Case(3):  # SHA256SIG1
                    m.d.comb += self.wb_data.eq(
                        self._ror32(a, 17) ^ self._ror32(a, 19) ^ (a >> 10)
                    )
        with m.Elif(sha512):
            m.d.comb += [self.matched.eq(1), self.wb_en.eq(1)]
            with m.Switch(self.funct7):
                with m.Case(0b0101000):  # SHA512SUM0R, a=lo, b=hi
                    m.d.comb += self.wb_data.eq(
                        (a << 25) ^ (a << 30) ^ (a >> 28)
                        ^ (b >> 7) ^ (b >> 2) ^ (b << 4)
                    )
                with m.Case(0b0101001):  # SHA512SUM1R, a=lo, b=hi
                    m.d.comb += self.wb_data.eq(
                        (a << 23) ^ (a >> 14) ^ (a >> 18)
                        ^ (b >> 9) ^ (b << 18) ^ (b << 14)
                    )
                with m.Case(0b0101010):  # SHA512SIG0L, a=lo, b=hi
                    m.d.comb += self.wb_data.eq(
                        (a >> 1) ^ (a >> 7) ^ (a >> 8)
                        ^ (b << 31) ^ (b << 25) ^ (b << 24)
                    )
                with m.Case(0b0101110):  # SHA512SIG0H, a=hi, b=lo
                    m.d.comb += self.wb_data.eq(
                        (a >> 1) ^ (a >> 7) ^ (a >> 8)
                        ^ (b << 31) ^ (b << 24)
                    )
                with m.Case(0b0101011):  # SHA512SIG1L, a=lo, b=hi
                    m.d.comb += self.wb_data.eq(
                        (a << 3) ^ (a >> 6) ^ (a >> 19)
                        ^ (b >> 29) ^ (b << 26) ^ (b << 13)
                    )
                with m.Case(0b0101111):  # SHA512SIG1H, a=hi, b=lo
                    m.d.comb += self.wb_data.eq(
                        (a << 3) ^ (a >> 6) ^ (a >> 19)
                        ^ (b >> 29) ^ (b << 13)
                    )

        m.d.comb += self.alu_out.eq(self.wb_data)
        return m
