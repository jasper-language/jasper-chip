from amaranth import *


class VFNarrowFloatUnit(Elaboratable):
    """Combinational IEEE binary64-to-binary32 narrowing conversion."""

    def __init__(self):
        self.value = Signal(64)
        self.rm = Signal(3)
        self.round_odd = Signal()
        self.result = Signal(32)
        self.flags = Signal(5)

    def elaborate(self, platform):
        m = Module()
        exp = self.value[52:63]
        frac = self.value[:52]
        sign = self.value[63]
        mant = Signal(53)
        shamt = Signal(6)
        half_shamt = Signal(6)
        base = Signal(25)
        rounded = Signal(26)
        discard_mask = Signal(53)
        lower_mask = Signal(53)
        inexact = Signal()
        guard = Signal()
        lower = Signal()
        increment = Signal()
        target_exp = Signal(9)
        final_exp = Signal(9)
        final_frac = Signal(23)
        overflow = Signal()
        to_inf = Signal()
        is_nan = (exp == 0x7FF) & frac.any()
        is_snan = is_nan & ~frac[51]

        m.d.comb += [
            mant.eq(Cat(frac, exp != 0)), shamt.eq(0), half_shamt.eq(0),
            base.eq(0), discard_mask.eq(0), lower_mask.eq(0),
            inexact.eq(0), guard.eq(0), lower.eq(0), target_exp.eq(0),
            final_exp.eq(0), final_frac.eq(0),
        ]
        with m.If((exp >= 897) & (exp != 0x7FF)):
            m.d.comb += [
                shamt.eq(29), half_shamt.eq(28), base.eq(mant >> 29),
                target_exp.eq(exp - 896),
            ]
        with m.Elif((exp >= 874) & (exp < 897)):
            m.d.comb += [
                shamt.eq(926 - exp), half_shamt.eq(shamt - 1),
                base.eq(mant >> shamt),
            ]
        with m.Elif(exp == 873):
            m.d.comb += [inexact.eq(1), guard.eq(1), lower.eq(frac != 0)]
        with m.Elif((exp != 0) | (frac != 0)):
            m.d.comb += inexact.eq(1)

        with m.If((exp >= 874) & (exp != 0x7FF)):
            m.d.comb += [
                discard_mask.eq((C(1, 53) << shamt) - 1),
                lower_mask.eq((C(1, 53) << half_shamt) - 1),
                inexact.eq((mant & discard_mask) != 0),
                guard.eq(mant.bit_select(half_shamt, 1)),
                lower.eq((mant & lower_mask) != 0),
            ]

        m.d.comb += increment.eq(Mux(
            self.rm == 0, guard & (lower | base[0]),
            Mux(self.rm == 2, sign & inexact,
                Mux(self.rm == 3, ~sign & inexact,
                    Mux(self.rm == 4, guard, 0)))))
        m.d.comb += rounded.eq(Mux(
            self.round_odd, base | inexact, base + increment))

        with m.If(exp >= 897):
            m.d.comb += [
                final_exp.eq(Mux(rounded[24], target_exp + 1, target_exp)),
                final_frac.eq(Mux(rounded[24], rounded[1:24],
                                   rounded[0:23])),
            ]
        with m.Else():
            m.d.comb += [
                final_exp.eq(Mux(rounded[23], 1, 0)),
                final_frac.eq(Mux(rounded[23], 0, rounded[0:23])),
            ]

        m.d.comb += [
            overflow.eq((exp != 0x7FF) & (final_exp >= 0xFF)),
            to_inf.eq(~self.round_odd & ((self.rm == 0) | (self.rm == 4) |
                      ((self.rm == 2) & sign) | ((self.rm == 3) & ~sign))),
            self.result.eq(Cat(final_frac, final_exp[:8], sign)),
            self.flags.eq(0),
        ]
        with m.If(is_nan):
            m.d.comb += [
                self.result.eq(0x7FC00000),
                self.flags.eq(Mux(is_snan, 0x10, 0)),
            ]
        with m.Elif(exp == 0x7FF):
            m.d.comb += self.result.eq(Cat(C(0, 23), C(0xFF, 8), sign))
        with m.Elif(overflow):
            m.d.comb += [
                self.result.eq(Mux(
                    to_inf, Cat(C(0, 23), C(0xFF, 8), sign),
                    Cat(C(0x7FFFFF, 23), C(0xFE, 8), sign))),
                self.flags.eq(0x05),
            ]
        with m.Elif(inexact & (final_exp == 0)):
            m.d.comb += self.flags.eq(0x03)
        with m.Elif(inexact):
            m.d.comb += self.flags.eq(0x01)
        return m
