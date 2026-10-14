"""Combinational restoring IEEE-754 binary128 divider."""

from amaranth import *


class QFDivUnit(Elaboratable):
    def __init__(self):
        self.a = Signal(128)
        self.b = Signal(128)
        self.rm = Signal(3)
        self.result = Signal(128)
        self.flags = Signal(5)

    def elaborate(self, platform):
        m = Module()
        bias = 16383
        max_exp = 0x7fff
        sign = self.a[127] ^ self.b[127]
        a_exp, b_exp = self.a[112:127], self.b[112:127]
        a_frac, b_frac = self.a[0:112], self.b[0:112]
        a_nan = (a_exp == max_exp) & a_frac.any()
        b_nan = (b_exp == max_exp) & b_frac.any()
        a_snan = a_nan & ~a_frac[111]
        b_snan = b_nan & ~b_frac[111]
        a_inf = (a_exp == max_exp) & ~a_frac.any()
        b_inf = (b_exp == max_exp) & ~b_frac.any()
        a_zero = ~a_exp.any() & ~a_frac.any()
        b_zero = ~b_exp.any() & ~b_frac.any()
        def leading_shift(fraction, low=0, high=112):
            if high - low == 1:
                return Mux(fraction[low], C(112 - low, 7), C(0, 7))
            middle = (low + high) // 2
            return Mux(fraction[middle:high].any(),
                       leading_shift(fraction, middle, high),
                       leading_shift(fraction, low, middle))

        a_shift_expr = leading_shift(a_frac)
        b_shift_expr = leading_shift(b_frac)
        a_shift = Signal(range(114))
        b_shift = Signal(range(114))
        a_mant = Signal(113)
        b_mant = Signal(113)
        a_norm = Signal(113)
        b_norm = Signal(113)
        a_adjusted_exp = Signal(signed(18))
        b_adjusted_exp = Signal(signed(18))
        ratio_ge_one = Signal()
        numerator = Signal(114)
        exponent = Signal(signed(19))
        m.d.comb += [
            a_shift.eq(Mux(a_exp == 0, a_shift_expr, 0)),
            b_shift.eq(Mux(b_exp == 0, b_shift_expr, 0)),
            a_mant.eq(Cat(a_frac, Mux(a_exp == 0, 0, 1))),
            b_mant.eq(Cat(b_frac, Mux(b_exp == 0, 0, 1))),
            a_norm.eq(a_mant << a_shift),
            b_norm.eq(b_mant << b_shift),
            a_adjusted_exp.eq(Cat(Mux(a_exp == 0, C(1, 15), a_exp),
                                  C(0, 3)).as_signed() - a_shift),
            b_adjusted_exp.eq(Cat(Mux(b_exp == 0, C(1, 15), b_exp),
                                  C(0, 3)).as_signed() - b_shift),
            ratio_ge_one.eq(a_norm >= b_norm),
            numerator.eq(Mux(ratio_ge_one, a_norm, a_norm << 1)),
            exponent.eq(a_adjusted_exp - b_adjusted_exp + bias -
                        Mux(ratio_ge_one, 0, 1)),
        ]
        remainders = [Signal(114, name="qdiv_rem_0")]
        m.d.comb += remainders[0].eq(numerator - b_norm)
        quotient_high_to_low = []
        for stage in range(116):
            shifted = Signal(114, name=f"qdiv_shifted_{stage}")
            bit = Signal(name=f"qdiv_bit_{115 - stage}")
            next_rem = Signal(114, name=f"qdiv_rem_{stage + 1}")
            m.d.comb += [
                shifted.eq(remainders[-1] << 1),
                bit.eq(shifted >= b_norm),
                next_rem.eq(Mux(bit, shifted - b_norm, shifted)),
            ]
            quotient_high_to_low.append(bit)
            remainders.append(next_rem)
        quotient = Signal(117)
        m.d.comb += quotient.eq(Cat(
            *reversed(quotient_high_to_low), C(1, 1)))
        desired_shift = Signal(signed(20))
        shift = Signal(range(118))
        retained = Signal(114)
        guard = Signal()
        sticky = Signal()
        inexact = Signal()
        increment = Signal()
        rounded = Signal(114)
        final_exp = Signal(16)
        final_frac = Signal(112)
        overflow = Signal()
        underflow = Signal()
        to_inf = Signal()
        invalid = Signal()
        divide_by_zero = Signal()
        canonical_nan = C((max_exp << 112) | (1 << 111), 128)
        m.d.comb += [
            self.result.eq(canonical_nan),
            self.flags.eq(0),
            desired_shift.eq(Mux(exponent > 0, 4, 5 - exponent)),
            shift.eq(Mux(desired_shift >= 117, 117, desired_shift)),
            retained.eq(quotient >> shift),
            guard.eq(Mux(desired_shift > 117, 0,
                         (quotient >> (shift - 1).as_unsigned())[0])),
            sticky.eq(Mux(desired_shift > 117,
                          quotient.any() | remainders[-1].any(),
                          ((quotient & ((C(1, 117) <<
                            (shift - 1).as_unsigned()) - 1)) != 0) |
                          remainders[-1].any())),
            inexact.eq(guard | sticky),
            increment.eq(Mux(self.rm == 0,
                guard & (sticky | retained[0]),
                Mux(self.rm == 1, 0,
                Mux(self.rm == 2, sign & inexact,
                Mux(self.rm == 3, ~sign & inexact, guard))))),
            rounded.eq(retained + increment),
            final_exp.eq(Mux(exponent <= 0,
                             Mux(rounded[112], 1, 0),
                             exponent + rounded[113])),
            final_frac.eq(Mux(rounded[113],
                              rounded[1:113], rounded[0:112])),
            overflow.eq(final_exp >= max_exp),
            underflow.eq((final_exp == 0) & inexact),
            to_inf.eq((self.rm == 0) | (self.rm == 4) |
                      ((self.rm == 3) & ~sign) |
                      ((self.rm == 2) & sign)),
            invalid.eq(a_snan | b_snan | (a_zero & b_zero) |
                       (a_inf & b_inf)),
            divide_by_zero.eq(~a_nan & ~a_inf & ~a_zero & b_zero),
        ]
        with m.If(a_nan | b_nan | (a_zero & b_zero) | (a_inf & b_inf)):
            m.d.comb += self.result.eq(canonical_nan)
        with m.Elif(a_inf | b_zero):
            m.d.comb += self.result.eq(Cat(C(0, 112), C(max_exp, 15), sign))
        with m.Elif(a_zero | b_inf):
            m.d.comb += self.result.eq(Cat(C(0, 127), sign))
        with m.Elif(overflow):
            m.d.comb += self.result.eq(Mux(
                to_inf,
                Cat(C(0, 112), C(max_exp, 15), sign),
                Cat(C((1 << 112) - 1, 112), C(max_exp - 1, 15), sign)))
        with m.Else():
            m.d.comb += self.result.eq(Cat(final_frac, final_exp[0:15], sign))
        with m.If(invalid):
            m.d.comb += self.flags.eq(0b10000)
        with m.Elif(divide_by_zero):
            m.d.comb += self.flags.eq(0b01000)
        with m.Elif(overflow):
            m.d.comb += self.flags.eq(0b00101)
        with m.Elif(underflow):
            m.d.comb += self.flags.eq(0b00011)
        with m.Elif(inexact):
            m.d.comb += self.flags.eq(0b00001)
        return m
