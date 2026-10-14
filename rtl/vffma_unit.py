from amaranth import Cat, Const, Elaboratable, Module, Mux, Signal, signed


class _BinaryFMA(Elaboratable):
    def __init__(self, exponent_bits, fraction_bits):
        self.exponent_bits = exponent_bits
        self.fraction_bits = fraction_bits
        self.width = 1 + exponent_bits + fraction_bits
        self.a = Signal(self.width)
        self.b = Signal(self.width)
        self.c = Signal(self.width)
        self.negate_product = Signal()
        self.negate_addend = Signal()
        self.rm = Signal(3)
        self.result = Signal(self.width)
        self.flags = Signal(5)

    def elaborate(self, platform):
        m = Module()
        eb = self.exponent_bits
        fb = self.fraction_bits
        precision = fb + 1
        bias = (1 << (eb - 1)) - 1
        max_exp = (1 << eb) - 1
        product_width = 2 * precision
        guard_width = precision + 3
        wide_width = product_width + guard_width

        def unpack(value, name):
            sign = value[self.width - 1]
            exponent = value[fb:fb + eb]
            fraction = value[:fb]
            zero = (exponent == 0) & ~fraction.any()
            inf = (exponent == max_exp) & ~fraction.any()
            nan = (exponent == max_exp) & fraction.any()
            snan = nan & ~fraction[fb - 1]

            def leading_shift(low=0, high=fb):
                if high - low == 1:
                    return Mux(fraction[low],
                               Const(fb - low, range(fb + 2)),
                               Const(0, range(fb + 2)))
                middle = (low + high) // 2
                return Mux(fraction[middle:high].any(),
                           leading_shift(middle, high),
                           leading_shift(low, middle))

            shift = Signal(range(fb + 2), name=f"{name}_shift")
            mantissa = Signal(precision, name=f"{name}_mantissa")
            adjusted_exp = Signal(signed(eb + 3), name=f"{name}_exp")
            m.d.comb += shift.eq(leading_shift())
            with m.If(exponent == 0):
                m.d.comb += [
                    mantissa.eq(fraction << shift),
                    adjusted_exp.eq(Const(1, signed(eb + 3)) - shift),
                ]
            with m.Else():
                m.d.comb += [
                    mantissa.eq(Cat(fraction, Const(1, 1))),
                    adjusted_exp.eq(exponent),
                ]
            return sign, zero, inf, nan, snan, mantissa, adjusted_exp

        a_sign, a_zero, a_inf, a_nan, a_snan, a_mant, a_exp = \
            unpack(self.a, "a")
        b_sign, b_zero, b_inf, b_nan, b_snan, b_mant, b_exp = \
            unpack(self.b, "b")
        c_sign, _, c_inf, c_nan, c_snan, c_mant, c_exp = \
            unpack(self.c, "c")

        product = Signal(product_width)
        product_sig = Signal(product_width)
        product_exp = Signal(signed(eb + 4))
        product_sign = a_sign ^ b_sign ^ self.negate_product
        addend_sign = c_sign ^ self.negate_addend
        m.d.comb += product.eq(a_mant * b_mant)
        with m.If(product[product_width - 1]):
            m.d.comb += [
                product_sig.eq(product),
                product_exp.eq(a_exp + b_exp - bias + 1),
            ]
        with m.Else():
            m.d.comb += [
                product_sig.eq(product << 1),
                product_exp.eq(a_exp + b_exp - bias),
            ]

        addend_sig = Signal(product_width)
        common_exp = Signal(signed(eb + 4))
        difference = Signal(eb + 2)
        product_larger = product_exp >= c_exp
        m.d.comb += [
            addend_sig.eq(c_mant << precision),
            common_exp.eq(Mux(product_larger, product_exp, c_exp)),
            difference.eq(Mux(product_larger, product_exp - c_exp,
                              c_exp - product_exp)),
        ]
        product_wide = Signal(wide_width)
        addend_wide = Signal(wide_width)
        m.d.comb += [
            product_wide.eq(product_sig << guard_width),
            addend_wide.eq(addend_sig << guard_width),
        ]

        def jam_shift(value, amount, name):
            current = value
            sticky = Const(0, 1)
            distance = 1
            stage = 0
            while distance < wide_width:
                shifted = Signal(wide_width,
                                 name=f"{name}_shift_{stage}")
                lost = Signal(name=f"{name}_lost_{stage}")
                m.d.comb += [
                    shifted.eq(Mux(amount[stage], current >> distance,
                                   current)),
                    lost.eq(amount[stage] & current[:distance].any()),
                ]
                sticky = sticky | lost
                current = shifted
                stage += 1
                distance <<= 1
            result = Signal(wide_width, name=f"{name}_jammed")
            with m.If(amount >= wide_width):
                m.d.comb += result.eq(value.any())
            with m.Else():
                m.d.comb += result.eq(current | sticky)
            return result

        shifted_product = jam_shift(product_wide, difference, "product")
        shifted_addend = jam_shift(addend_wide, difference, "addend")
        aligned_product = Mux(product_larger, product_wide, shifted_product)
        aligned_addend = Mux(product_larger, shifted_addend, addend_wide)
        magnitude = Signal(wide_width + 1)
        finite_sign = Signal()
        with m.If(product_sign == addend_sign):
            m.d.comb += [magnitude.eq(aligned_product + aligned_addend),
                         finite_sign.eq(product_sign)]
        with m.Elif(aligned_product >= aligned_addend):
            m.d.comb += [magnitude.eq(aligned_product - aligned_addend),
                         finite_sign.eq(product_sign)]
        with m.Else():
            m.d.comb += [magnitude.eq(aligned_addend - aligned_product),
                         finite_sign.eq(addend_sign)]

        def leading_position(low=0, high=wide_width + 1):
            if high - low == 1:
                return Mux(magnitude[low],
                           Const(low, range(wide_width + 1)),
                           Const(0, range(wide_width + 1)))
            middle = (low + high) // 2
            return Mux(magnitude[middle:high].any(),
                       leading_position(middle, high),
                       leading_position(low, middle))

        leading = Signal(range(wide_width + 1))
        normal_exp = Signal(signed(eb + 5))
        shift_amount = Signal(range(wide_width + 2))
        m.d.comb += [
            leading.eq(leading_position()),
            normal_exp.eq(common_exp + leading - (wide_width - 1)),
        ]
        with m.If(normal_exp > 0):
            m.d.comb += shift_amount.eq(leading - fb)
        with m.Else():
            m.d.comb += shift_amount.eq(2 * precision + 4 - common_exp)

        shifted = Signal(wide_width + 1)
        guard = Signal()
        sticky_mask = Signal(wide_width + 1)
        sticky = Signal()
        m.d.comb += [
            shifted.eq(magnitude >> shift_amount),
            guard.eq(Mux(shift_amount == 0, 0,
                         (magnitude >>
                          (shift_amount - 1).as_unsigned())[0])),
            sticky_mask.eq((Const(1, wide_width + 2) <<
                            Mux(shift_amount == 0, 0,
                                (shift_amount - 1).as_unsigned())) - 1),
            sticky.eq(Mux(shift_amount <= 1, 0,
                          (magnitude & sticky_mask).any())),
        ]
        retained = shifted[:precision]
        inexact = guard | sticky
        increment = Signal()
        m.d.comb += increment.eq(
            Mux(self.rm == 0, guard & (sticky | retained[0]),
                Mux(self.rm == 1, 0,
                    Mux(self.rm == 2, finite_sign & inexact,
                        Mux(self.rm == 3, ~finite_sign & inexact,
                            Mux(self.rm == 4, guard, 0)))))
        )
        rounded = Signal(precision + 1)
        rounded_exp = Signal(signed(eb + 5))
        rounded_fraction = Signal(fb)
        m.d.comb += rounded.eq(retained + increment)
        with m.If(normal_exp > 0):
            with m.If(rounded[precision]):
                m.d.comb += [rounded_exp.eq(normal_exp + 1),
                             rounded_fraction.eq(rounded[1:precision])]
            with m.Else():
                m.d.comb += [rounded_exp.eq(normal_exp),
                             rounded_fraction.eq(rounded[:fb])]
        with m.Elif(rounded[fb]):
            m.d.comb += [rounded_exp.eq(1), rounded_fraction.eq(0)]
        with m.Else():
            m.d.comb += [rounded_exp.eq(0),
                         rounded_fraction.eq(rounded[:fb])]

        overflow = rounded_exp >= max_exp
        underflow = (rounded_exp == 0) & inexact
        to_inf = ((self.rm == 0) | (self.rm == 4) |
                  ((self.rm == 2) & finite_sign) |
                  ((self.rm == 3) & ~finite_sign))
        finite_result = Signal(self.width)
        with m.If(overflow):
            m.d.comb += finite_result.eq(Mux(
                to_inf, Cat(Const(0, fb), Const(max_exp, eb), finite_sign),
                Cat(Const((1 << fb) - 1, fb), Const(max_exp - 1, eb),
                    finite_sign)))
        with m.Elif(magnitude == 0):
            m.d.comb += finite_result.eq(Cat(
                Const(0, self.width - 1),
                Mux(product_sign == addend_sign, product_sign,
                    self.rm == 2)))
        with m.Else():
            m.d.comb += finite_result.eq(
                Cat(rounded_fraction, rounded_exp[:eb], finite_sign))

        invalid_product = (a_zero & b_inf) | (a_inf & b_zero)
        product_inf = (a_inf | b_inf) & ~invalid_product
        invalid_sum = product_inf & c_inf & (product_sign != addend_sign)
        invalid = invalid_product | invalid_sum
        any_nan = a_nan | b_nan | c_nan
        any_snan = a_snan | b_snan | c_snan
        canonical_nan = Const((max_exp << fb) | (1 << (fb - 1)),
                              self.width)
        m.d.comb += [self.result.eq(0), self.flags.eq(0)]
        with m.If(any_nan | invalid):
            m.d.comb += [self.result.eq(canonical_nan),
                         self.flags.eq(Mux(any_snan | invalid, 0b10000, 0))]
        with m.Elif(product_inf):
            m.d.comb += self.result.eq(
                Cat(Const(0, fb), Const(max_exp, eb), product_sign))
        with m.Elif(c_inf):
            m.d.comb += self.result.eq(
                Cat(Const(0, fb), Const(max_exp, eb), addend_sign))
        with m.Else():
            m.d.comb += [
                self.result.eq(finite_result),
                self.flags.eq(Cat(inexact, underflow, overflow,
                                  Const(0, 2)) |
                              Mux(overflow, 0b00101, 0)),
            ]
        return m


class VFFMAUnit(Elaboratable):
    """Binary32/binary64 vector fused multiply-add execution unit."""

    def __init__(self):
        self.a = Signal(64)
        self.b = Signal(64)
        self.c = Signal(64)
        self.is_f64 = Signal()
        self.widen = Signal()
        self.widen_addend = Signal()
        self.negate_product = Signal()
        self.negate_addend = Signal()
        self.rm = Signal(3)
        self.result = Signal(64)
        self.flags = Signal(5)

    def elaborate(self, platform):
        m = Module()
        m.submodules.f32 = f32 = _BinaryFMA(8, 23)
        m.submodules.f64 = f64 = _BinaryFMA(11, 52)

        def widen_f32(value, name):
            sign = value[31]
            exponent = value[23:31]
            fraction = value[:23]

            def leading_shift(low=0, high=23):
                if high - low == 1:
                    return Mux(fraction[low], Const(23 - low, 5),
                               Const(0, 5))
                middle = (low + high) // 2
                return Mux(fraction[middle:high].any(),
                           leading_shift(middle, high),
                           leading_shift(low, middle))

            shift = Signal(5, name=f"{name}_shift")
            normalized = Signal(24, name=f"{name}_normalized")
            result = Signal(64, name=f"{name}_f64")
            m.d.comb += [shift.eq(leading_shift()),
                         normalized.eq(fraction << shift)]
            with m.If(exponent == 0xff):
                m.d.comb += result.eq(
                    Cat(Const(0, 29), fraction, Const(0x7ff, 11), sign))
            with m.Elif(exponent != 0):
                m.d.comb += result.eq(
                    Cat(Const(0, 29), fraction, exponent + 896, sign))
            with m.Elif(fraction.any()):
                m.d.comb += result.eq(
                    Cat(Const(0, 29), normalized[:23], 897 - shift, sign))
            with m.Else():
                m.d.comb += result.eq(Cat(Const(0, 63), sign))
            return result

        widen_a = widen_f32(self.a[:32], "a")
        widen_b = widen_f32(self.b[:32], "b")
        widen_c = widen_f32(self.c[:32], "c")
        m.d.comb += [
            f32.a.eq(self.a[:32]), f32.b.eq(self.b[:32]),
            f32.c.eq(self.c[:32]),
            f32.negate_product.eq(self.negate_product),
            f32.negate_addend.eq(self.negate_addend), f32.rm.eq(self.rm),
            f64.a.eq(Mux(self.widen, widen_a, self.a)),
            f64.b.eq(Mux(self.widen, widen_b, self.b)),
            f64.c.eq(Mux(self.widen & self.widen_addend,
                         widen_c, self.c)),
            f64.negate_product.eq(self.negate_product),
            f64.negate_addend.eq(self.negate_addend), f64.rm.eq(self.rm),
            self.result.eq(Mux(self.is_f64 | self.widen,
                               f64.result, f32.result)),
            self.flags.eq(Mux(self.is_f64 | self.widen,
                              f64.flags, f32.flags)),
        ]
        return m
