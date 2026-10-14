"""Shared iterative IEEE-754 square-root unit for V elements."""

from amaranth import *


class VFSqrtUnit(Elaboratable):
    def __init__(self):
        self.start = Signal()
        self.is_f64 = Signal()
        self.a = Signal(64)
        self.rm = Signal(3)
        self.busy = Signal()
        self.done = Signal()
        self.result = Signal(64)
        self.flags = Signal(5)

    def elaborate(self, platform):
        m = Module()

        radicand = Signal(114)
        remainder = Signal(116)
        root = Signal(57)
        count = Signal(6)
        saved_f64 = Signal()
        saved_rm = Signal(3)
        saved_exp = Signal(signed(15))
        state_round = Signal()

        a32 = self.a[0:32]
        a64 = self.a
        a32_exp = a32[23:31]
        a32_frac = a32[0:23]
        a64_exp = a64[52:63]
        a64_frac = a64[0:52]
        a32_shift_expr = C(0, range(24))
        for bit in range(23):
            a32_shift_expr = Mux(a32_frac[bit], 23 - bit, a32_shift_expr)
        a64_shift_expr = C(0, range(53))
        for bit in range(52):
            a64_shift_expr = Mux(a64_frac[bit], 52 - bit, a64_shift_expr)

        a32_shift = Signal(range(24))
        a64_shift = Signal(range(53))
        a32_mant = Signal(24)
        a64_mant = Signal(53)
        a32_norm = Signal(24)
        a64_norm = Signal(53)
        a32_adjusted_exp = Signal(signed(15))
        a64_adjusted_exp = Signal(signed(15))
        unbiased_exp = Signal(signed(15))
        selected_norm = Signal(53)
        selected_result_exp = Signal(signed(15))
        selected_shift = Signal(7)
        m.d.comb += [
            a32_shift.eq(Mux(a32_exp == 0, a32_shift_expr, 0)),
            a64_shift.eq(Mux(a64_exp == 0, a64_shift_expr, 0)),
            a32_mant.eq(Cat(a32_frac, Mux(a32_exp == 0, 0, 1))),
            a64_mant.eq(Cat(a64_frac, Mux(a64_exp == 0, 0, 1))),
            a32_norm.eq(a32_mant << a32_shift),
            a64_norm.eq(a64_mant << a64_shift),
            a32_adjusted_exp.eq(Cat(
                Mux(a32_exp == 0, C(1, 8), a32_exp), C(0, 7)).as_signed() -
                a32_shift),
            a64_adjusted_exp.eq(Cat(
                Mux(a64_exp == 0, C(1, 11), a64_exp), C(0, 4)).as_signed() -
                a64_shift),
            unbiased_exp.eq(Mux(self.is_f64,
                                a64_adjusted_exp - 1023,
                                a32_adjusted_exp - 127)),
            selected_norm.eq(Mux(self.is_f64, a64_norm, a32_norm)),
            selected_result_exp.eq((unbiased_exp >> 1) +
                                    Mux(self.is_f64, 1023, 127)),
            selected_shift.eq(Mux(self.is_f64, 60, 31) + unbiased_exp[0]),
        ]

        a_nan = Mux(self.is_f64,
                    (a64_exp == 0x7ff) & a64_frac.any(),
                    (a32_exp == 0xff) & a32_frac.any())
        a_snan = Mux(self.is_f64,
                     (a64_exp == 0x7ff) & a64_frac.any() & ~a64_frac[51],
                     (a32_exp == 0xff) & a32_frac.any() & ~a32_frac[22])
        a_inf = Mux(self.is_f64,
                    (a64_exp == 0x7ff) & ~a64_frac.any(),
                    (a32_exp == 0xff) & ~a32_frac.any())
        a_zero = Mux(self.is_f64, ~a64[0:63].any(), ~a32[0:31].any())
        a_sign = Mux(self.is_f64, a64[63], a32[31])
        canonical_nan = Mux(self.is_f64, C(0x7ff8000000000000, 64),
                            C(0x000000007fc00000, 64))
        signed_zero = Mux(self.is_f64, a64,
                          Cat(a32, C(0, 32)))
        positive_inf = Mux(self.is_f64, C(0x7ff0000000000000, 64),
                           C(0x000000007f800000, 64))

        pair = Signal(2)
        shifted_remainder = Signal(116)
        trial = Signal(116)
        take = Signal()
        m.d.comb += [
                pair.eq(radicand.word_select((count - 1).as_unsigned(), 2)),
            shifted_remainder.eq((remainder << 2) | pair),
            trial.eq((root << 2) | 1),
            take.eq(shifted_remainder >= trial),
        ]

        def round_format(mant_width, exponent_width):
            sig_width = mant_width + 4
            retained = Signal(mant_width)
            guard = root[3]
            sticky = Signal()
            inexact = Signal()
            increment = Signal()
            rounded = Signal(mant_width + 1)
            final_exp = Signal(exponent_width + 1)
            final_frac = Signal(mant_width - 1)
            m.d.comb += [
                retained.eq(root[4:sig_width]),
                sticky.eq(root[0:3].any() | remainder.any()),
                inexact.eq(guard | sticky),
                increment.eq(Mux(saved_rm == 0,
                                 guard & (sticky | retained[0]),
                                 Mux(saved_rm == 1, 0,
                                 Mux(saved_rm == 2, 0,
                                 Mux(saved_rm == 3, inexact,
                                     guard))))),
                rounded.eq(retained + increment),
                final_exp.eq(saved_exp + rounded[mant_width]),
                final_frac.eq(Mux(rounded[mant_width],
                                  rounded[1:mant_width],
                                  rounded[0:mant_width - 1])),
            ]
            return (Cat(final_frac, final_exp[0:exponent_width], C(0, 1)),
                    Mux(inexact, C(0b00001, 5), C(0, 5)))

        result32, flags32 = round_format(24, 8)
        result64, flags64 = round_format(53, 11)

        m.d.sync += self.done.eq(0)
        with m.If(self.start & ~self.busy):
            m.d.sync += [saved_f64.eq(self.is_f64), saved_rm.eq(self.rm),
                         self.flags.eq(0)]
            with m.If(a_nan | (a_sign & ~a_zero)):
                m.d.sync += [
                    self.result.eq(canonical_nan),
                    self.flags.eq(Mux(a_snan | (a_sign & ~a_zero), 0b10000, 0)),
                    self.done.eq(1),
                ]
            with m.Elif(a_zero):
                m.d.sync += [self.result.eq(signed_zero), self.done.eq(1)]
            with m.Elif(a_inf):
                m.d.sync += [self.result.eq(positive_inf), self.done.eq(1)]
            with m.Else():
                m.d.sync += [
                    radicand.eq(selected_norm << selected_shift),
                    remainder.eq(0), root.eq(0),
                    count.eq(Mux(self.is_f64, 57, 28)),
                    saved_exp.eq(selected_result_exp),
                    self.busy.eq(1), state_round.eq(0),
                ]
        with m.Elif(self.busy & ~state_round):
            m.d.sync += [
                remainder.eq(Mux(take, shifted_remainder - trial,
                                 shifted_remainder)),
                root.eq((root << 1) | take),
                count.eq(count - 1),
            ]
            with m.If(count == 1):
                m.d.sync += state_round.eq(1)
        with m.Elif(self.busy & state_round):
            m.d.sync += [
                self.result.eq(Mux(saved_f64, result64,
                                   Cat(result32, C(0, 32)))),
                self.flags.eq(Mux(saved_f64, flags64, flags32)),
                self.busy.eq(0), self.done.eq(1), state_round.eq(0),
            ]
        return m
