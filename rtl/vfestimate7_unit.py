"""RISC-V V vfrec7/vfrsqrt7 exact table-defined estimate unit."""

from amaranth import Array, Cat, Const, Elaboratable, Module, Mux, Signal, signed


REC7_TABLE = (127, 125, 123, 121, 119, 117, 116, 114, 112, 110, 109, 107, 105, 104, 102, 100, 99, 97, 96, 94, 93, 91, 90, 88, 87, 85, 84, 83, 81, 80, 79, 77, 76, 75, 74, 72, 71, 70, 69, 68, 66, 65, 64, 63, 62, 61, 60, 59, 58, 57, 56, 55, 54, 53, 52, 51, 50, 49, 48, 47, 46, 45, 44, 43, 42, 41, 40, 40, 39, 38, 37, 36, 35, 35, 34, 33, 32, 31, 31, 30, 29, 28, 28, 27, 26, 25, 25, 24, 23, 23, 22, 21, 21, 20, 19, 19, 18, 17, 17, 16, 15, 15, 14, 14, 13, 12, 12, 11, 11, 10, 9, 9, 8, 8, 7, 7, 6, 5, 5, 4, 4, 3, 3, 2, 2, 1, 1, 0)
RSQRT7_TABLE = (52, 51, 50, 48, 47, 46, 44, 43, 42, 41, 40, 39, 38, 36, 35, 34, 33, 32, 31, 30, 30, 29, 28, 27, 26, 25, 24, 23, 23, 22, 21, 20, 19, 19, 18, 17, 16, 16, 15, 14, 14, 13, 12, 12, 11, 10, 10, 9, 9, 8, 7, 7, 6, 6, 5, 4, 4, 3, 3, 2, 2, 1, 1, 0, 127, 125, 123, 121, 119, 118, 116, 114, 113, 111, 109, 108, 106, 105, 103, 102, 100, 99, 97, 96, 95, 93, 92, 91, 90, 88, 87, 86, 85, 84, 83, 82, 80, 79, 78, 77, 76, 75, 74, 73, 72, 71, 70, 70, 69, 68, 67, 66, 65, 64, 63, 63, 62, 61, 60, 59, 59, 58, 57, 56, 56, 55, 54, 53)


class VFEstimate7Unit(Elaboratable):
    def __init__(self):
        self.value = Signal(64)
        self.is_f64 = Signal()
        self.reciprocal_sqrt = Signal()
        self.rm = Signal(3)
        self.result = Signal(64)
        self.flags = Signal(5)

    @staticmethod
    def _format(m, value, width, exp_bits, frac_bits, bias, reciprocal_sqrt, rm):
        sign = value[width - 1]
        exp = value[frac_bits:frac_bits + exp_bits]
        frac = value[:frac_bits]
        exp_all_ones = (1 << exp_bits) - 1
        canonical_nan = (exp_all_ones << frac_bits) | (1 << (frac_bits - 1))
        infinity = exp_all_ones << frac_bits
        max_finite = ((exp_all_ones - 1) << frac_bits) | ((1 << frac_bits) - 1)
        is_nan = (exp == exp_all_ones) & frac.any()
        is_snan = is_nan & ~frac[frac_bits - 1]
        is_inf = (exp == exp_all_ones) & ~frac.any()
        is_zero = (exp == 0) & ~frac.any()
        leading = Signal(range(frac_bits + 1))
        normalized_frac = Signal(frac_bits)
        normalized_exp = Signal(signed(exp_bits + 2))
        m.d.comb += [
            leading.eq(frac_bits),
            normalized_frac.eq(Mux(exp == 0, frac << (leading + 1), frac)),
            normalized_exp.eq(Mux(exp == 0, -leading, exp)),
        ]
        for bit in range(frac_bits):
            with m.If(frac[bit]):
                m.d.comb += leading.eq(frac_bits - 1 - bit)

        rec_table = Array(Const(v, 7) for v in REC7_TABLE)
        rsqrt_table = Array(Const(v, 7) for v in RSQRT7_TABLE)
        rec_index = normalized_frac[frac_bits - 7:frac_bits]
        rsqrt_index = Cat(normalized_frac[frac_bits - 6:frac_bits],
                          normalized_exp[0])
        estimate = Signal(7)
        m.d.comb += estimate.eq(Mux(reciprocal_sqrt,
                                    rsqrt_table[rsqrt_index],
                                    rec_table[rec_index]))
        common_frac = Cat(Const(0, frac_bits - 7), estimate)
        rsqrt_exp = Signal(signed(exp_bits + 2))
        rec_exp = Signal(signed(exp_bits + 2))
        m.d.comb += [
            rsqrt_exp.eq((3 * bias - 1 - normalized_exp) >> 1),
            rec_exp.eq(2 * bias - 1 - normalized_exp),
        ]
        rec_significand = Cat(Const(0, frac_bits - 7), estimate, Const(1, 1))
        rec_subnormal = Signal(frac_bits)
        m.d.comb += rec_subnormal.eq(
            rec_significand >> (1 - rec_exp).as_unsigned())
        finite_result = Signal(width)
        m.d.comb += finite_result.eq(Mux(
            reciprocal_sqrt,
            Cat(common_frac, rsqrt_exp[:exp_bits], sign),
            Mux(rec_exp <= 0,
                Cat(rec_subnormal, Const(0, exp_bits), sign),
                Cat(common_frac, rec_exp[:exp_bits], sign))))

        overflow_to_inf = Mux(sign,
            (rm == 2) | (rm == 0) | (rm == 4),
            (rm == 3) | (rm == 0) | (rm == 4))
        overflow_result = Cat(Const(max_finite, width - 1), sign)
        overflow_result = Mux(overflow_to_inf,
                              Cat(Const(infinity, width - 1), sign),
                              overflow_result)
        result = Signal(width)
        flags = Signal(5)
        m.d.comb += [result.eq(finite_result), flags.eq(0)]
        with m.If(is_nan):
            m.d.comb += [
                result.eq(Const(canonical_nan, width)),
                flags.eq(Mux(is_snan, 0b10000, 0)),
            ]
        with m.Elif(is_zero):
            m.d.comb += [
                result.eq(Cat(Const(infinity, width - 1), sign)),
                flags.eq(0b01000),
            ]
        with m.Elif(is_inf):
            with m.If(reciprocal_sqrt & sign):
                m.d.comb += [result.eq(Const(canonical_nan, width)),
                             flags.eq(0b10000)]
            with m.Else():
                m.d.comb += result.eq(Cat(Const(0, width - 1), sign))
        with m.Elif(reciprocal_sqrt & sign):
            m.d.comb += [result.eq(Const(canonical_nan, width)),
                         flags.eq(0b10000)]
        with m.Elif(~reciprocal_sqrt & (rec_exp > 2 * bias)):
            m.d.comb += [result.eq(overflow_result), flags.eq(0b00101)]
        return result, flags

    def elaborate(self, platform):
        m = Module()
        result32, flags32 = self._format(
            m, self.value[:32], 32, 8, 23, 127,
            self.reciprocal_sqrt, self.rm)
        result64, flags64 = self._format(
            m, self.value, 64, 11, 52, 1023,
            self.reciprocal_sqrt, self.rm)
        m.d.comb += [
            self.result.eq(Mux(self.is_f64, result64, result32)),
            self.flags.eq(Mux(self.is_f64, flags64, flags32)),
        ]
        return m
