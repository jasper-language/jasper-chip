"""Combinational IEEE-754 binary128 add/subtract unit."""

from amaranth import *


class QFAddUnit(Elaboratable):
    def __init__(self):
        self.a = Signal(128)
        self.b = Signal(128)
        self.subtract = Signal()
        self.rm = Signal(3)
        self.result = Signal(128)
        self.flags = Signal(5)

    def elaborate(self, platform):
        m = Module()
        frac_width = 112
        exp_width = 15
        max_exp = 0x7fff
        mant_width = 113
        ext_width = 117
        b_value = Signal(128)
        a_sign = self.a[127]
        b_sign = b_value[127]
        a_exp = self.a[112:127]
        b_exp = b_value[112:127]
        a_frac = self.a[0:112]
        b_frac = b_value[0:112]
        a_nan = (a_exp == max_exp) & a_frac.any()
        b_nan = (b_exp == max_exp) & b_frac.any()
        a_snan = a_nan & ~a_frac[111]
        b_snan = b_nan & ~b_frac[111]
        a_inf = (a_exp == max_exp) & ~a_frac.any()
        b_inf = (b_exp == max_exp) & ~b_frac.any()
        a_zero = ~a_exp.any() & ~a_frac.any()
        b_zero = ~b_exp.any() & ~b_frac.any()
        a_mant = Signal(mant_width)
        b_mant = Signal(mant_width)
        a_ge = Signal()
        sign = Signal()
        large_exp = Signal(16)
        small_exp = Signal(16)
        large_mant = Signal(mant_width)
        small_mant = Signal(mant_width)
        delta = Signal(16)
        shift = Signal(range(ext_width + 1))
        large_ext = Signal(ext_width)
        small_ext = Signal(ext_width)
        shifted = Signal(ext_width)
        shift_mask = Signal(ext_width)
        sticky = Signal()
        same_sign = Signal()
        add_sum = Signal(ext_width + 1)
        diff = Signal(ext_width)
        leading_shift = Signal(range(ext_width + 1))
        actual_shift = Signal(range(ext_width + 1))
        norm = Signal(ext_width)
        norm_exp = Signal(16)
        inexact = Signal()
        increment = Signal()
        rounded = Signal(mant_width + 1)
        packed_exp = Signal(16)
        final_exp = Signal(16)
        final_frac = Signal(frac_width)
        overflow = Signal()
        tiny = Signal()
        overflow_to_inf = Signal()
        invalid = Signal()
        canonical_nan = C((max_exp << frac_width) | (1 << 111), 128)
        m.d.comb += [
            b_value.eq(Cat(self.b[0:127], self.b[127] ^ self.subtract)),
            self.result.eq(canonical_nan),
            self.flags.eq(0),
            a_mant.eq(Cat(a_frac, Mux(a_exp == 0, 0, 1))),
            b_mant.eq(Cat(b_frac, Mux(b_exp == 0, 0, 1))),
            a_ge.eq((a_exp > b_exp) |
                    ((a_exp == b_exp) & (a_frac >= b_frac))),
            sign.eq(Mux(a_ge, a_sign, b_sign)),
            large_exp.eq(Mux(a_ge, Mux(a_exp == 0, 1, a_exp),
                             Mux(b_exp == 0, 1, b_exp))),
            small_exp.eq(Mux(a_ge, Mux(b_exp == 0, 1, b_exp),
                             Mux(a_exp == 0, 1, a_exp))),
            large_mant.eq(Mux(a_ge, a_mant, b_mant)),
            small_mant.eq(Mux(a_ge, b_mant, a_mant)),
            delta.eq(large_exp - small_exp),
            shift.eq(Mux(delta >= ext_width, ext_width, delta)),
            large_ext.eq(large_mant << 3),
            small_ext.eq(small_mant << 3),
            shift_mask.eq((C(1, ext_width) << shift) - 1),
            sticky.eq((small_ext & shift_mask) != 0),
            shifted.eq((small_ext >> shift) | sticky),
            same_sign.eq(a_sign == b_sign),
            add_sum.eq(large_ext + shifted),
            diff.eq(large_ext - shifted),
            leading_shift.eq(0),
            actual_shift.eq(Mux(leading_shift > (large_exp - 1),
                                large_exp - 1, leading_shift)),
            norm.eq(0),
            norm_exp.eq(large_exp),
        ]
        for bit in range(ext_width):
            with m.If(diff[bit]):
                m.d.comb += leading_shift.eq(
                    ext_width - 2 - bit if bit <= ext_width - 2 else 0)
        with m.If(same_sign):
            with m.If(add_sum[ext_width]):
                m.d.comb += [
                    norm.eq((add_sum >> 1) | add_sum[0]),
                    norm_exp.eq(large_exp + 1),
                ]
            with m.Else():
                m.d.comb += norm.eq(add_sum[0:ext_width])
        with m.Else():
            m.d.comb += [
                norm.eq(diff << actual_shift),
                norm_exp.eq(large_exp - actual_shift),
            ]
        m.d.comb += [
            inexact.eq(norm[0:3] != 0),
            increment.eq(Mux(self.rm == 0,
                norm[2] & (norm[1] | norm[0] | norm[3]),
                Mux(self.rm == 1, 0,
                Mux(self.rm == 2, sign & inexact,
                Mux(self.rm == 3, ~sign & inexact, norm[2]))))),
            rounded.eq(norm[3:ext_width] + increment),
            packed_exp.eq(Mux((norm_exp == 1) & ~norm[ext_width - 1],
                              0, norm_exp)),
            final_exp.eq(Mux(rounded[mant_width], packed_exp + 1,
                         Mux((packed_exp == 0) & rounded[mant_width - 1],
                             1, packed_exp))),
            final_frac.eq(Mux(rounded[mant_width],
                              rounded[1:mant_width],
                              rounded[0:frac_width])),
            overflow.eq(final_exp >= max_exp),
            tiny.eq((final_exp == 0) & inexact),
            overflow_to_inf.eq((self.rm == 0) | (self.rm == 4) |
                               ((self.rm == 3) & ~sign) |
                               ((self.rm == 2) & sign)),
            invalid.eq(a_snan | b_snan |
                       (a_inf & b_inf & (a_sign != b_sign))),
        ]
        with m.If(a_nan | b_nan |
                  (a_inf & b_inf & (a_sign != b_sign))):
            m.d.comb += self.result.eq(canonical_nan)
        with m.Elif(a_inf):
            m.d.comb += self.result.eq(self.a)
        with m.Elif(b_inf):
            m.d.comb += self.result.eq(b_value)
        with m.Elif((a_zero & b_zero) | (~same_sign & (diff == 0))):
            m.d.comb += self.result.eq(Cat(
                C(0, 127),
                Mux(a_zero & b_zero & (a_sign == b_sign),
                    a_sign, self.rm == 2)))
        with m.Elif(overflow):
            m.d.comb += self.result.eq(Mux(
                overflow_to_inf,
                Cat(C(0, 112), C(max_exp, 15), sign),
                Cat(C((1 << 112) - 1, 112), C(max_exp - 1, 15), sign)))
        with m.Else():
            m.d.comb += self.result.eq(Cat(
                final_frac, final_exp[0:15], sign))
        with m.If(invalid):
            m.d.comb += self.flags.eq(0b10000)
        with m.Elif(overflow):
            m.d.comb += self.flags.eq(0b00101)
        with m.Elif(tiny):
            m.d.comb += self.flags.eq(0b00011)
        with m.Elif(inexact):
            m.d.comb += self.flags.eq(0b00001)
        return m
