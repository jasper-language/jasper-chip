from amaranth import Elaboratable, Module, Signal


class BranchCondition(Elaboratable):
    """RISC-V conditional branch comparator for RV32 and RV64."""

    def __init__(self, xlen):
        self.xlen = xlen
        self.funct3 = Signal(3)
        self.lhs = Signal(xlen)
        self.rhs = Signal(xlen)
        self.taken = Signal()

    def elaborate(self, platform):
        m = Module()
        with m.Switch(self.funct3):
            with m.Case(0b000):
                m.d.comb += self.taken.eq(self.lhs == self.rhs)
            with m.Case(0b001):
                m.d.comb += self.taken.eq(self.lhs != self.rhs)
            with m.Case(0b100):
                m.d.comb += self.taken.eq(
                    self.lhs.as_signed() < self.rhs.as_signed())
            with m.Case(0b101):
                m.d.comb += self.taken.eq(
                    self.lhs.as_signed() >= self.rhs.as_signed())
            with m.Case(0b110):
                m.d.comb += self.taken.eq(self.lhs < self.rhs)
            with m.Case(0b111):
                m.d.comb += self.taken.eq(self.lhs >= self.rhs)
        return m
