"""Exact RISC-V binary32-to-binary64 widening conversion."""

from amaranth import Cat, Const, Elaboratable, Module, Mux, Signal


class VFWidenFloatUnit(Elaboratable):
    def __init__(self):
        self.value = Signal(32)
        self.result = Signal(64)
        self.flags = Signal(5)

    def elaborate(self, platform):
        m = Module()
        sign = self.value[31]
        exp = self.value[23:31]
        frac = self.value[:23]
        is_nan = (exp == 0xff) & frac.any()
        is_snan = is_nan & ~frac[22]
        leading = Signal(range(23))
        normalized = Signal(53)
        m.d.comb += [leading.eq(0), normalized.eq(frac << (Const(52, 6) - leading).as_unsigned()),
                     self.result.eq(0), self.flags.eq(0)]
        for bit in range(23):
            with m.If(frac[bit]):
                m.d.comb += leading.eq(bit)
        with m.If(exp == 0xff):
            m.d.comb += [
                self.result.eq(Mux(
                    is_nan, Const(0x7ff8000000000000, 64),
                    Cat(Const(0, 52), Const(0x7ff, 11), sign))),
                self.flags.eq(Mux(is_snan, 0b10000, 0)),
            ]
        with m.Elif(exp == 0):
            with m.If(frac.any()):
                m.d.comb += self.result.eq(
                    Cat(normalized[:52], leading + 874, sign))
            with m.Else():
                m.d.comb += self.result.eq(Cat(Const(0, 63), sign))
        with m.Else():
            m.d.comb += self.result.eq(
                Cat(Const(0, 29), frac, (exp + Const(896, 11))[:11], sign))
        return m
