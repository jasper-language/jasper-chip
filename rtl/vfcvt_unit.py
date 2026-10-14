from amaranth import *
from amaranth.lib.coding import PriorityEncoder


class VFIntToFloatUnit(Elaboratable):
    """Combinational RVV signed/unsigned integer to FP32/FP64 converter."""

    def __init__(self):
        self.value = Signal(64)
        self.is_f64 = Signal()
        self.int64 = Signal()
        self.unsigned = Signal()
        self.rm = Signal(3)
        self.result = Signal(64)
        self.flags = Signal(5)
        self.rm_valid = Signal()

    def elaborate(self, platform):
        m = Module()

        def conversion(integer_width, result_width, fraction_bits, bias):
            source = self.value[:integer_width]
            sign = Signal()
            magnitude = Signal(integer_width)
            msb = Signal(range(integer_width))
            shift_right = Signal(range(integer_width + 1))
            shift_left = Signal(range(integer_width + 1))
            retained = Signal(fraction_bits + 2)
            remainder = Signal(integer_width)
            halfway = Signal(integer_width)
            inexact = Signal()
            increment = Signal()
            rounded = Signal(fraction_bits + 3)
            carry = Signal()
            exponent = Signal(range(bias * 2 + 2))
            fraction = Signal(fraction_bits)
            result = Signal(result_width)
            encoder = PriorityEncoder(integer_width)
            m.submodules[f"vfcvt_priority_{integer_width}_{result_width}"] = encoder

            m.d.comb += [
                sign.eq(~self.unsigned & source[-1]),
                magnitude.eq(Mux(sign, -source, source)),
                encoder.i.eq(magnitude[::-1]),
                msb.eq((integer_width - 1) - encoder.o),
            ]

            with m.If(msb > fraction_bits):
                m.d.comb += [
                    shift_right.eq(msb - fraction_bits),
                    shift_left.eq(0),
                    retained.eq(magnitude >> shift_right),
                    remainder.eq(magnitude & ((Const(1, integer_width) << shift_right) - 1)),
                    halfway.eq(Const(1, integer_width) <<
                               (shift_right - 1).as_unsigned()),
                ]
            with m.Else():
                m.d.comb += [
                    shift_right.eq(0),
                    shift_left.eq(fraction_bits - msb),
                    retained.eq(magnitude << shift_left),
                    remainder.eq(0),
                    halfway.eq(0),
                ]

            m.d.comb += [
                inexact.eq(remainder != 0),
                increment.eq(0),
            ]
            with m.Switch(self.rm):
                with m.Case(0):
                    m.d.comb += increment.eq(
                        (remainder > halfway) |
                        ((remainder == halfway) & retained[0]))
                with m.Case(2):
                    m.d.comb += increment.eq(sign & inexact)
                with m.Case(3):
                    m.d.comb += increment.eq(~sign & inexact)
                with m.Case(4):
                    m.d.comb += increment.eq(inexact & (remainder >= halfway))

            m.d.comb += [
                rounded.eq(retained + increment),
                carry.eq(rounded[fraction_bits + 1]),
                exponent.eq(bias + msb + carry),
                fraction.eq(Mux(carry,
                                rounded[1:fraction_bits + 1],
                                rounded[:fraction_bits])),
                result.eq(Mux(magnitude == 0, 0,
                              Cat(fraction,
                                  exponent[:result_width - fraction_bits - 1],
                                  sign))),
            ]
            return result, inexact

        result32, inexact32 = conversion(32, 32, 23, 127)
        result64to32, inexact64to32 = conversion(64, 32, 23, 127)
        result64, inexact64 = conversion(64, 64, 52, 1023)
        m.d.comb += [
            self.rm_valid.eq(self.rm <= 4),
            self.result.eq(Mux(self.is_f64, result64,
                               Mux(self.int64, result64to32, result32))),
            self.flags.eq(Mux(self.is_f64, inexact64,
                              Mux(self.int64, inexact64to32, inexact32))),
        ]
        return m
