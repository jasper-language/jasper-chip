from amaranth import Cat, Const, Elaboratable, Module, Mux, Signal, signed


class QFFMAUnit(Elaboratable):
    """Fused IEEE-754 binary128 multiply-add with one final rounding."""

    def __init__(self):
        self.a = Signal(128)
        self.b = Signal(128)
        self.c = Signal(128)
        self.negate_product = Signal()
        self.negate_addend = Signal()
        self.rm = Signal(3)
        self.result = Signal(128)
        self.flags = Signal(5)

    def elaborate(self, platform):
        m = Module()

        def unpack(value, name):
            sign = value[127]
            exponent = value[112:127]
            fraction = value[:112]
            zero = (exponent == 0) & (fraction == 0)
            inf = (exponent == 0x7fff) & (fraction == 0)
            nan = (exponent == 0x7fff) & (fraction != 0)
            snan = nan & ~fraction[111]
            shift = Signal(7, name=f"{name}_shift")
            def leading_shift(low=0, high=112):
                if high - low == 1:
                    return Mux(fraction[low], Const(112 - low, 7),
                               Const(0, 7))
                middle = (low + high) // 2
                return Mux(fraction[middle:high].any(),
                           leading_shift(middle, high),
                           leading_shift(low, middle))

            shift_expr = leading_shift()
            mantissa = Signal(113, name=f"{name}_mantissa")
            adjusted_exp = Signal(signed(17), name=f"{name}_exp")
            m.d.comb += shift.eq(shift_expr)
            with m.If(exponent == 0):
                m.d.comb += [
                    mantissa.eq(fraction << shift),
                    adjusted_exp.eq(Const(1, signed(17)) - shift),
                ]
            with m.Else():
                m.d.comb += [
                    mantissa.eq(Cat(fraction, Const(1, 1))),
                    adjusted_exp.eq(exponent),
                ]
            return (sign, exponent, fraction, zero, inf, nan, snan,
                    mantissa, adjusted_exp)

        (a_sign, _, _, a_zero, a_inf, a_nan, a_snan,
         a_mant, a_exp) = unpack(self.a, "a")
        (b_sign, _, _, b_zero, b_inf, b_nan, b_snan,
         b_mant, b_exp) = unpack(self.b, "b")
        (c_sign, _, _, c_zero, c_inf, c_nan, c_snan,
         c_mant, c_exp) = unpack(self.c, "c")

        product = Signal(226)
        product_sig = Signal(226)
        product_exp = Signal(signed(18))
        product_sign = a_sign ^ b_sign ^ self.negate_product
        addend_sign = c_sign ^ self.negate_addend
        m.d.comb += product.eq(a_mant * b_mant)
        with m.If(product[225]):
            m.d.comb += [
                product_sig.eq(product),
                product_exp.eq(a_exp + b_exp - 16382),
            ]
        with m.Else():
            m.d.comb += [
                product_sig.eq(product << 1),
                product_exp.eq(a_exp + b_exp - 16383),
            ]

        addend_sig = Signal(226)
        m.d.comb += addend_sig.eq(c_mant << 113)
        common_exp = Signal(signed(18))
        exp_difference = Signal(16)
        product_is_larger = product_exp >= c_exp
        m.d.comb += [
            common_exp.eq(Mux(product_is_larger, product_exp, c_exp)),
            exp_difference.eq(Mux(product_is_larger,
                                  product_exp - c_exp,
                                  c_exp - product_exp)),
        ]

        product_wide = Signal(342)
        addend_wide = Signal(342)
        m.d.comb += [
            product_wide.eq(product_sig << 116),
            addend_wide.eq(addend_sig << 116),
        ]

        def jam_shift(value, amount, name):
            current = value
            sticky = Const(0, 1)
            for stage, distance in enumerate((1, 2, 4, 8, 16, 32, 64,
                                               128, 256)):
                shifted = Signal(342, name=f"{name}_shift_{stage}")
                lost = Signal(name=f"{name}_lost_{stage}")
                m.d.comb += [
                    shifted.eq(Mux(amount[stage], current >> distance,
                                   current)),
                    lost.eq(amount[stage] & current[:distance].any()),
                ]
                sticky = sticky | lost
                current = shifted
            result = Signal(342, name=f"{name}_jammed")
            with m.If(amount >= 342):
                m.d.comb += result.eq(value.any())
            with m.Else():
                m.d.comb += result.eq(current | sticky)
            return result

        shifted_product = jam_shift(product_wide, exp_difference, "product")
        shifted_addend = jam_shift(addend_wide, exp_difference, "addend")
        aligned_product = Signal(342)
        aligned_addend = Signal(342)
        m.d.comb += [
            aligned_product.eq(Mux(product_is_larger, product_wide,
                                   shifted_product)),
            aligned_addend.eq(Mux(product_is_larger, shifted_addend,
                                  addend_wide)),
        ]

        magnitude = Signal(343)
        finite_sign = Signal()
        with m.If(product_sign == addend_sign):
            m.d.comb += [
                magnitude.eq(aligned_product + aligned_addend),
                finite_sign.eq(product_sign),
            ]
        with m.Elif(aligned_product >= aligned_addend):
            m.d.comb += [
                magnitude.eq(aligned_product - aligned_addend),
                finite_sign.eq(product_sign),
            ]
        with m.Else():
            m.d.comb += [
                magnitude.eq(aligned_addend - aligned_product),
                finite_sign.eq(addend_sign),
            ]

        leading_index = Signal(9)
        def leading_position(low=0, high=343):
            if high - low == 1:
                return Mux(magnitude[low], Const(low, 9), Const(0, 9))
            middle = (low + high) // 2
            return Mux(magnitude[middle:high].any(),
                       leading_position(middle, high),
                       leading_position(low, middle))

        leading_expr = leading_position()
        m.d.comb += leading_index.eq(leading_expr)

        normal_exp = Signal(signed(19))
        shift_amount = Signal(10)
        m.d.comb += normal_exp.eq(common_exp + leading_index - 341)
        with m.If(normal_exp > 0):
            m.d.comb += shift_amount.eq(leading_index - 112)
        with m.Else():
            m.d.comb += shift_amount.eq(230 - common_exp)

        shifted_magnitude = Signal(343)
        guard = Signal()
        sticky_mask = Signal(343)
        sticky = Signal()
        m.d.comb += [
            shifted_magnitude.eq(magnitude >> shift_amount),
            guard.eq(Mux(shift_amount == 0, 0,
                         (magnitude >>
                          (shift_amount - 1).as_unsigned())[0])),
            sticky_mask.eq((Const(1, 344) <<
                            Mux(shift_amount == 0, 0,
                                (shift_amount - 1).as_unsigned())) - 1),
            sticky.eq(Mux(shift_amount <= 1, 0,
                          (magnitude & sticky_mask).any())),
        ]
        retained = shifted_magnitude[:113]
        inexact = guard | sticky
        increment = Signal()
        m.d.comb += increment.eq(
            Mux(self.rm == 0, guard & (sticky | retained[0]),
                Mux(self.rm == 1, 0,
                    Mux(self.rm == 2, finite_sign & inexact,
                        Mux(self.rm == 3, ~finite_sign & inexact,
                            Mux(self.rm == 4, guard, 0)))))
        )
        rounded = Signal(114)
        rounded_exp = Signal(signed(19))
        rounded_fraction = Signal(112)
        m.d.comb += rounded.eq(retained + increment)
        with m.If(normal_exp > 0):
            with m.If(rounded[113]):
                m.d.comb += [
                    rounded_exp.eq(normal_exp + 1),
                    rounded_fraction.eq(rounded[1:113]),
                ]
            with m.Else():
                m.d.comb += [
                    rounded_exp.eq(normal_exp),
                    rounded_fraction.eq(rounded[:112]),
                ]
        with m.Elif(rounded[112]):
            m.d.comb += [rounded_exp.eq(1), rounded_fraction.eq(0)]
        with m.Else():
            m.d.comb += [
                rounded_exp.eq(0),
                rounded_fraction.eq(rounded[:112]),
            ]

        overflow = rounded_exp >= 0x7fff
        underflow = (rounded_exp == 0) & inexact
        overflow_to_inf = ((self.rm == 0) | (self.rm == 4) |
                           ((self.rm == 2) & finite_sign) |
                           ((self.rm == 3) & ~finite_sign))
        finite_result = Signal(128)
        with m.If(overflow):
            m.d.comb += finite_result.eq(
                Mux(overflow_to_inf,
                    Cat(Const(0, 112), Const(0x7fff, 15), finite_sign),
                    Cat(Const((1 << 112) - 1, 112), Const(0x7ffe, 15),
                        finite_sign))
            )
        with m.Elif(magnitude == 0):
            m.d.comb += finite_result.eq(
                Cat(Const(0, 127),
                    Mux(product_sign == addend_sign, product_sign,
                        self.rm == 2))
            )
        with m.Else():
            m.d.comb += finite_result.eq(
                Cat(rounded_fraction, rounded_exp[:15], finite_sign)
            )

        invalid_product = (a_zero & b_inf) | (a_inf & b_zero)
        product_inf = (a_inf | b_inf) & ~invalid_product
        invalid_inf_sum = product_inf & c_inf & (product_sign != addend_sign)
        invalid = invalid_product | invalid_inf_sum
        any_nan = a_nan | b_nan | c_nan
        any_snan = a_snan | b_snan | c_snan
        canonical_nan = Const(0x7fff8000000000000000000000000000, 128)

        m.d.comb += [self.result.eq(0), self.flags.eq(0)]
        with m.If(any_nan | invalid):
            m.d.comb += [
                self.result.eq(canonical_nan),
                self.flags.eq(Mux(any_snan | invalid, 0b10000, 0)),
            ]
        with m.Elif(product_inf):
            m.d.comb += self.result.eq(
                Cat(Const(0, 112), Const(0x7fff, 15), product_sign)
            )
        with m.Elif(c_inf):
            m.d.comb += self.result.eq(
                Cat(Const(0, 112), Const(0x7fff, 15), addend_sign)
            )
        with m.Else():
            m.d.comb += [
                self.result.eq(finite_result),
                self.flags.eq(Cat(inexact, underflow, overflow, Const(0, 1),
                                  Const(0, 1)) |
                              Mux(overflow, 0b00101, 0)),
            ]

        return m
