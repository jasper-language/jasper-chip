from amaranth import *


class VFFloatToIntRTZUnit(Elaboratable):
    """Combinational RVV FP32/FP64 to integer conversion."""

    def __init__(self):
        self.value = Signal(64)
        self.is_f64 = Signal()
        self.int64 = Signal()
        self.unsigned = Signal()
        self.rm = Signal(3)
        self.result = Signal(64)
        self.flags = Signal(5)

    def elaborate(self, platform):
        m = Module()

        def conversion(value_width, exponent_bits, fraction_bits, bias,
                       integer_width):
            value = self.value[:value_width]
            fraction = value[:fraction_bits]
            exponent = value[fraction_bits:fraction_bits + exponent_bits]
            sign = value[-1]
            mantissa = Signal(fraction_bits + 1)
            magnitude = Signal(integer_width + 1)
            rounded_magnitude = Signal(integer_width + 1)
            shift = Signal(range(integer_width + 1))
            guard = Signal()
            lower = Signal()
            increment = Signal()
            finite_nonzero = Signal()
            special = Signal()
            invalid = Signal()
            inexact = Signal()
            signed_limit = Const(1 << (integer_width - 1), integer_width + 1)
            unsigned_limit = Const((1 << integer_width) - 1,
                                   integer_width + 1)
            result = Signal(integer_width)

            m.d.comb += [
                mantissa.eq(Cat(fraction, exponent != 0)),
                magnitude.eq(0),
                shift.eq(0),
                guard.eq(0),
                lower.eq(0),
                finite_nonzero.eq((exponent != 0) | (fraction != 0)),
                special.eq(exponent == (1 << exponent_bits) - 1),
            ]
            with m.If(exponent < bias):
                with m.If(exponent == bias - 1):
                    m.d.comb += [
                        guard.eq(1),
                        lower.eq(fraction != 0),
                    ]
                with m.Else():
                    m.d.comb += lower.eq(finite_nonzero)
            with m.Elif(exponent < bias + fraction_bits):
                m.d.comb += [
                    shift.eq(bias + fraction_bits - exponent),
                    magnitude.eq(mantissa >> shift),
                    guard.eq((mantissa >> (shift - 1).as_unsigned())[0]),
                    lower.eq((mantissa &
                        ((Const(1, integer_width + 1) <<
                          (shift - 1).as_unsigned()) - 1)) != 0),
                ]
            with m.Elif(exponent < bias + integer_width):
                m.d.comb += [
                    shift.eq(exponent - (bias + fraction_bits)),
                    magnitude.eq(mantissa << shift),
                ]

            m.d.comb += [
                inexact.eq((guard | lower) & ~special),
                increment.eq(0),
            ]
            with m.Switch(self.rm):
                with m.Case(0):
                    m.d.comb += increment.eq(guard & (lower | magnitude[0]))
                with m.Case(2):
                    m.d.comb += increment.eq(sign & inexact)
                with m.Case(3):
                    m.d.comb += increment.eq(~sign & inexact)
                with m.Case(4):
                    m.d.comb += increment.eq(guard)
            m.d.comb += [
                rounded_magnitude.eq(magnitude + increment),
                invalid.eq(
                    special |
                    (self.unsigned & sign & (rounded_magnitude != 0)) |
                    (self.unsigned & (rounded_magnitude > unsigned_limit)) |
                    (~self.unsigned & ~sign & (rounded_magnitude >= signed_limit)) |
                    (~self.unsigned & sign & (rounded_magnitude > signed_limit)) |
                    ((exponent >= bias + integer_width) & finite_nonzero)),
                result.eq(Mux(sign, -rounded_magnitude, rounded_magnitude)),
            ]
            with m.If(invalid):
                with m.If(self.unsigned):
                    m.d.comb += result.eq(Mux(
                        sign & ~(special & (fraction != 0)),
                        0, Const(-1, integer_width)))
                with m.Else():
                    m.d.comb += result.eq(Mux(sign & ~((exponent ==
                        (1 << exponent_bits) - 1) & (fraction != 0)),
                        Const(1 << (integer_width - 1), integer_width),
                        Const((1 << (integer_width - 1)) - 1,
                              integer_width)))
            return result, invalid, inexact

        result32, invalid32, inexact32 = conversion(32, 8, 23, 127, 32)
        result32to64, invalid32to64, inexact32to64 = conversion(
            32, 8, 23, 127, 64)
        result64to32, invalid64to32, inexact64to32 = conversion(
            64, 11, 52, 1023, 32)
        result64, invalid64, inexact64 = conversion(64, 11, 52, 1023, 64)
        selected_invalid = Mux(self.is_f64,
                               Mux(self.int64, invalid64, invalid64to32),
                               Mux(self.int64, invalid32to64, invalid32))
        selected_inexact = Mux(self.is_f64,
                               Mux(self.int64, inexact64, inexact64to32),
                               Mux(self.int64, inexact32to64, inexact32))
        m.d.comb += [
            self.result.eq(Mux(self.is_f64,
                               Mux(self.int64, result64, result64to32),
                               Mux(self.int64, result32to64, result32))),
            self.flags.eq(Cat(selected_inexact & ~selected_invalid,
                              Const(0, 3), selected_invalid)),
        ]
        return m
