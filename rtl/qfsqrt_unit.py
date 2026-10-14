from amaranth import Cat, Const, Elaboratable, Module, Mux, Signal, signed


class QFSqrtUnit(Elaboratable):
    """Combinational IEEE-754 binary128 square-root unit."""

    def __init__(self):
        self.a = Signal(128)
        self.rm = Signal(3)
        self.result = Signal(128)
        self.flags = Signal(5)  # NV, DZ, OF, UF, NX

    def elaborate(self, platform):
        m = Module()

        sign = self.a[127]
        exponent = self.a[112:127]
        fraction = self.a[:112]
        is_zero = (exponent == 0) & (fraction == 0)
        is_inf = (exponent == 0x7fff) & (fraction == 0)
        is_nan = (exponent == 0x7fff) & (fraction != 0)
        is_snan = is_nan & ~fraction[111]

        sub_shift = Signal(7)
        def leading_shift(low=0, high=112):
            if high - low == 1:
                return Mux(fraction[low], Const(112 - low, 7), Const(0, 7))
            middle = (low + high) // 2
            return Mux(fraction[middle:high].any(),
                       leading_shift(middle, high),
                       leading_shift(low, middle))

        shift_expr = leading_shift()
        m.d.comb += sub_shift.eq(shift_expr)

        mantissa = Signal(113)
        unbiased_exp = Signal(signed(16))
        with m.If(exponent == 0):
            m.d.comb += [
                mantissa.eq(fraction << sub_shift),
                unbiased_exp.eq(Const(-16382, signed(16)) - sub_shift),
            ]
        with m.Else():
            m.d.comb += [
                mantissa.eq(Cat(fraction, Const(1, 1))),
                unbiased_exp.eq(Cat(exponent, Const(0, 1)).as_signed() -
                                    16383),
            ]

        # A 117-bit root supplies the 113 result bits and four rounding bits.
        # Odd exponents move one power of two into the significand.
        radicand = Signal(234)
        m.d.comb += radicand.eq(
            Mux(unbiased_exp[0], mantissa << 121, mantissa << 120)
        )

        remainders = [Signal(236, name=f"sqrt_rem_{i}") for i in range(118)]
        roots = [Signal(117, name=f"sqrt_root_{i}") for i in range(118)]
        m.d.comb += [remainders[0].eq(0), roots[0].eq(0)]
        for stage in range(117):
            pair_index = 116 - stage
            shifted_rem = Signal(236, name=f"sqrt_shifted_rem_{stage}")
            trial = Signal(236, name=f"sqrt_trial_{stage}")
            m.d.comb += [
                shifted_rem.eq(
                    (remainders[stage] << 2) |
                    radicand[2 * pair_index:2 * pair_index + 2]
                ),
                trial.eq((roots[stage] << 2) | 1),
            ]
            with m.If(shifted_rem >= trial):
                m.d.comb += [
                    remainders[stage + 1].eq(shifted_rem - trial),
                    roots[stage + 1].eq((roots[stage] << 1) | 1),
                ]
            with m.Else():
                m.d.comb += [
                    remainders[stage + 1].eq(shifted_rem),
                    roots[stage + 1].eq(roots[stage] << 1),
                ]

        root = roots[117]
        retained = root[4:117]
        guard = root[3]
        round_bit = root[2]
        sticky = root[:2].any() | (remainders[117] != 0)
        inexact = guard | round_bit | sticky
        increment = Signal()
        m.d.comb += increment.eq(
            Mux(self.rm == 0, guard & (round_bit | sticky | retained[0]),
                Mux(self.rm == 1, 0,
                    Mux(self.rm == 2, 0,
                        Mux(self.rm == 3, inexact,
                            Mux(self.rm == 4, guard, 0)))))
        )
        rounded = Signal(114)
        m.d.comb += rounded.eq(retained + increment)

        result_exp_unbiased = Signal(signed(16))
        result_exp = Signal(15)
        result_fraction = Signal(112)
        m.d.comb += result_exp_unbiased.eq(unbiased_exp >> 1)
        with m.If(rounded[113]):
            m.d.comb += [
                result_exp.eq(result_exp_unbiased + 16384),
                result_fraction.eq(rounded[1:113]),
            ]
        with m.Else():
            m.d.comb += [
                result_exp.eq(result_exp_unbiased + 16383),
                result_fraction.eq(rounded[:112]),
            ]

        canonical_nan = Const(0x7fff8000000000000000000000000000, 128)
        m.d.comb += [self.result.eq(0), self.flags.eq(0)]
        with m.If(is_nan):
            m.d.comb += [
                self.result.eq(canonical_nan),
                self.flags.eq(Mux(is_snan, 0b10000, 0)),
            ]
        with m.Elif(sign & ~is_zero):
            m.d.comb += [
                self.result.eq(canonical_nan),
                self.flags.eq(0b10000),
            ]
        with m.Elif(is_inf | is_zero):
            m.d.comb += self.result.eq(self.a)
        with m.Else():
            m.d.comb += [
                self.result.eq(Cat(result_fraction, result_exp, Const(0, 1))),
                self.flags.eq(inexact),
            ]

        return m
