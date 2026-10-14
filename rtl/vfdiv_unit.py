"""Shared iterative IEEE-754 divider for V floating-point elements."""

from amaranth import *


class VFDivUnit(Elaboratable):
    """One-lane binary32/binary64 divider with architectural flags."""

    def __init__(self):
        self.start = Signal()
        self.is_f64 = Signal()
        self.a = Signal(64)
        self.b = Signal(64)
        self.rm = Signal(3)
        self.busy = Signal()
        self.done = Signal()
        self.result = Signal(64)
        self.flags = Signal(5)

    def elaborate(self, platform):
        m = Module()

        divisor = Signal(53)
        remainder = Signal(54)
        quotient = Signal(57)
        count = Signal(6)
        saved_f64 = Signal()
        saved_rm = Signal(3)
        saved_sign = Signal()
        saved_ratio_ge_one = Signal()
        saved_exp = Signal(signed(15))
        state_round = Signal()

        a32 = self.a[0:32]
        b32 = self.b[0:32]
        a64 = self.a
        b64 = self.b

        a32_exp = a32[23:31]
        b32_exp = b32[23:31]
        a32_frac = a32[0:23]
        b32_frac = b32[0:23]
        a64_exp = a64[52:63]
        b64_exp = b64[52:63]
        a64_frac = a64[0:52]
        b64_frac = b64[0:52]

        a32_shift_expr = C(0, range(24))
        b32_shift_expr = C(0, range(24))
        for bit in range(23):
            a32_shift_expr = Mux(a32_frac[bit], 23 - bit, a32_shift_expr)
            b32_shift_expr = Mux(b32_frac[bit], 23 - bit, b32_shift_expr)
        a64_shift_expr = C(0, range(53))
        b64_shift_expr = C(0, range(53))
        for bit in range(52):
            a64_shift_expr = Mux(a64_frac[bit], 52 - bit, a64_shift_expr)
            b64_shift_expr = Mux(b64_frac[bit], 52 - bit, b64_shift_expr)

        a32_shift = Signal(range(24))
        b32_shift = Signal(range(24))
        a64_shift = Signal(range(53))
        b64_shift = Signal(range(53))
        a32_mant = Signal(24)
        b32_mant = Signal(24)
        a64_mant = Signal(53)
        b64_mant = Signal(53)
        a32_norm = Signal(24)
        b32_norm = Signal(24)
        a64_norm = Signal(53)
        b64_norm = Signal(53)
        a32_adjusted_exp = Signal(signed(15))
        b32_adjusted_exp = Signal(signed(15))
        a64_adjusted_exp = Signal(signed(15))
        b64_adjusted_exp = Signal(signed(15))
        selected_a_norm = Signal(53)
        selected_b_norm = Signal(53)
        selected_exp = Signal(signed(15))

        m.d.comb += [
            a32_shift.eq(Mux(a32_exp == 0, a32_shift_expr, 0)),
            b32_shift.eq(Mux(b32_exp == 0, b32_shift_expr, 0)),
            a64_shift.eq(Mux(a64_exp == 0, a64_shift_expr, 0)),
            b64_shift.eq(Mux(b64_exp == 0, b64_shift_expr, 0)),
            a32_mant.eq(Cat(a32_frac, Mux(a32_exp == 0, 0, 1))),
            b32_mant.eq(Cat(b32_frac, Mux(b32_exp == 0, 0, 1))),
            a64_mant.eq(Cat(a64_frac, Mux(a64_exp == 0, 0, 1))),
            b64_mant.eq(Cat(b64_frac, Mux(b64_exp == 0, 0, 1))),
            a32_norm.eq(a32_mant << a32_shift),
            b32_norm.eq(b32_mant << b32_shift),
            a64_norm.eq(a64_mant << a64_shift),
            b64_norm.eq(b64_mant << b64_shift),
            a32_adjusted_exp.eq(Cat(
                Mux(a32_exp == 0, C(1, 8), a32_exp), C(0, 7)).as_signed() -
                a32_shift),
            b32_adjusted_exp.eq(Cat(
                Mux(b32_exp == 0, C(1, 8), b32_exp), C(0, 7)).as_signed() -
                b32_shift),
            a64_adjusted_exp.eq(Cat(
                Mux(a64_exp == 0, C(1, 11), a64_exp), C(0, 4)).as_signed() -
                a64_shift),
            b64_adjusted_exp.eq(Cat(
                Mux(b64_exp == 0, C(1, 11), b64_exp), C(0, 4)).as_signed() -
                b64_shift),
            selected_a_norm.eq(Mux(self.is_f64, a64_norm, a32_norm)),
            selected_b_norm.eq(Mux(self.is_f64, b64_norm, b32_norm)),
            selected_exp.eq(Mux(
                self.is_f64,
                a64_adjusted_exp - b64_adjusted_exp + 1023 -
                    Mux(a64_norm >= b64_norm, 0, 1),
                a32_adjusted_exp - b32_adjusted_exp + 127 -
                    Mux(a32_norm >= b32_norm, 0, 1))),
        ]

        a_nan = Mux(self.is_f64,
                    (a64_exp == 0x7ff) & a64_frac.any(),
                    (a32_exp == 0xff) & a32_frac.any())
        b_nan = Mux(self.is_f64,
                    (b64_exp == 0x7ff) & b64_frac.any(),
                    (b32_exp == 0xff) & b32_frac.any())
        a_snan = Mux(self.is_f64,
                     (a64_exp == 0x7ff) & a64_frac.any() & ~a64_frac[51],
                     (a32_exp == 0xff) & a32_frac.any() & ~a32_frac[22])
        b_snan = Mux(self.is_f64,
                     (b64_exp == 0x7ff) & b64_frac.any() & ~b64_frac[51],
                     (b32_exp == 0xff) & b32_frac.any() & ~b32_frac[22])
        a_inf = Mux(self.is_f64,
                    (a64_exp == 0x7ff) & ~a64_frac.any(),
                    (a32_exp == 0xff) & ~a32_frac.any())
        b_inf = Mux(self.is_f64,
                    (b64_exp == 0x7ff) & ~b64_frac.any(),
                    (b32_exp == 0xff) & ~b32_frac.any())
        a_zero = Mux(self.is_f64, ~a64[0:63].any(), ~a32[0:31].any())
        b_zero = Mux(self.is_f64, ~b64[0:63].any(), ~b32[0:31].any())
        result_sign = Mux(self.is_f64, a64[63] ^ b64[63], a32[31] ^ b32[31])
        invalid = a_snan | b_snan | (a_zero & b_zero) | (a_inf & b_inf)
        divide_by_zero = ~a_nan & ~a_inf & ~a_zero & b_zero
        canonical_nan = Mux(self.is_f64, C(0x7ff8000000000000, 64),
                            C(0x000000007fc00000, 64))
        infinity = Mux(self.is_f64,
                       Cat(C(0, 52), C(0x7ff, 11), result_sign),
                       Cat(C(0, 23), C(0xff, 8), result_sign, C(0, 32)))
        signed_zero = Mux(self.is_f64,
                          Cat(C(0, 63), result_sign),
                          Cat(C(0, 31), result_sign, C(0, 32)))

        trial_remainder = Signal(54)
        quotient_bit = Signal()
        next_remainder = Signal(54)
        m.d.comb += [
            trial_remainder.eq(Mux(
                count == Mux(saved_f64, 57, 28),
                remainder,
                Cat(C(0, 1), remainder[0:53]))),
            quotient_bit.eq(trial_remainder >= divisor),
            next_remainder.eq(Mux(quotient_bit,
                                  trial_remainder - divisor,
                                  trial_remainder)),
        ]

        def round_format(mant_width, exponent_width, max_exp):
            sig_width = mant_width + 4
            shift_width = sig_width.bit_length()
            sig = Signal(sig_width)
            shift = Signal(range(sig_width + 1))
            retained = Signal(mant_width)
            guard = Signal()
            sticky_mask = Signal(sig_width)
            sticky = Signal()
            inexact = Signal()
            increment = Signal()
            rounded = Signal(mant_width + 1)
            final_exp = Signal(exponent_width + 1)
            final_frac = Signal(mant_width - 1)
            overflow = Signal()
            underflow = Signal()
            to_inf = Signal()
            sign = saved_sign
            m.d.comb += [
                sig.eq(Mux(saved_ratio_ge_one,
                           quotient[0:sig_width],
                           quotient[0:sig_width] << 1)),
                shift.eq(Mux(saved_exp > 0, 4,
                             Mux(5 - saved_exp >= sig_width,
                                 sig_width, 5 - saved_exp))),
                retained.eq(sig >> shift),
                guard.eq(Mux(shift != 0,
                             (sig >> (shift - C(1, shift_width)).as_unsigned())[0],
                             0)),
                sticky_mask.eq((C(1, sig_width) <<
                                Mux(shift != 0,
                                    (shift - C(1, shift_width)).as_unsigned(),
                                    0)) - 1),
                sticky.eq(((sig & sticky_mask) != 0) | (remainder != 0)),
                inexact.eq(guard | sticky),
                increment.eq(Mux(saved_rm == 0,
                                 guard & (sticky | retained[0]),
                                 Mux(saved_rm == 1, 0,
                                 Mux(saved_rm == 2, sign & inexact,
                                 Mux(saved_rm == 3, ~sign & inexact,
                                     guard))))),
                rounded.eq(retained + increment),
                final_exp.eq(Mux(saved_exp <= 0,
                                 Mux(rounded[mant_width - 1], 1, 0),
                                 saved_exp + rounded[mant_width])),
                final_frac.eq(Mux(rounded[mant_width],
                                  rounded[1:mant_width],
                                  rounded[0:mant_width - 1])),
                overflow.eq(final_exp >= max_exp),
                underflow.eq((final_exp == 0) & inexact),
                to_inf.eq((saved_rm == 0) | (saved_rm == 4) |
                          ((saved_rm == 3) & ~sign) |
                          ((saved_rm == 2) & sign)),
            ]
            finite = Mux(overflow,
                         Mux(to_inf,
                             Cat(C(0, mant_width - 1),
                                 C(max_exp, exponent_width), sign),
                             Cat(C((1 << (mant_width - 1)) - 1,
                                   mant_width - 1),
                                 C(max_exp - 1, exponent_width), sign)),
                         Cat(final_frac, final_exp[0:exponent_width], sign))
            flags = Mux(overflow, C(0b00101, 5),
                        Mux(underflow, C(0b00011, 5),
                            Mux(inexact, C(0b00001, 5), C(0, 5))))
            return finite, flags

        result32, flags32 = round_format(24, 8, 0xff)
        result64, flags64 = round_format(53, 11, 0x7ff)

        m.d.sync += self.done.eq(0)
        with m.If(self.start & ~self.busy):
            m.d.sync += [
                saved_f64.eq(self.is_f64),
                saved_rm.eq(self.rm),
                saved_sign.eq(result_sign),
                self.flags.eq(0),
            ]
            with m.If(a_nan | b_nan | (a_zero & b_zero) | (a_inf & b_inf)):
                m.d.sync += [
                    self.result.eq(canonical_nan),
                    self.flags.eq(Mux(invalid, 0b10000, 0)),
                    self.done.eq(1),
                ]
            with m.Elif(a_inf | b_zero):
                m.d.sync += [
                    self.result.eq(infinity),
                    self.flags.eq(Mux(divide_by_zero, 0b01000, 0)),
                    self.done.eq(1),
                ]
            with m.Elif(a_zero | b_inf):
                m.d.sync += [self.result.eq(signed_zero), self.done.eq(1)]
            with m.Else():
                m.d.sync += [
                    divisor.eq(selected_b_norm),
                    remainder.eq(Cat(selected_a_norm, C(0, 1))),
                    quotient.eq(0),
                    count.eq(Mux(self.is_f64, 57, 28)),
                    saved_ratio_ge_one.eq(selected_a_norm >= selected_b_norm),
                    saved_exp.eq(selected_exp),
                    self.busy.eq(1),
                    state_round.eq(0),
                ]
        with m.Elif(self.busy & ~state_round):
            m.d.sync += [
                remainder.eq(next_remainder),
                quotient.eq((quotient << 1) | quotient_bit),
                count.eq(count - 1),
            ]
            with m.If(count == 1):
                m.d.sync += state_round.eq(1)
        with m.Elif(self.busy & state_round):
            m.d.sync += [
                self.result.eq(Mux(saved_f64,
                                   result64,
                                   Cat(result32, C(0, 32)))),
                self.flags.eq(Mux(saved_f64, flags64, flags32)),
                self.busy.eq(0),
                self.done.eq(1),
                state_round.eq(0),
            ]

        return m
