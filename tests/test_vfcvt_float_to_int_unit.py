"""IEEE boundary tests for the shared V float-to-integer converter."""

from amaranth.sim import Settle, Simulator

from rtl.vfcvt_float_to_int_unit import VFFloatToIntRTZUnit


def test_vfcvt_f64_to_integer_rounding_special_values_and_limits():
    dut = VFFloatToIntRTZUnit()
    sim = Simulator(dut)
    cases = [
        # int64, unsigned, operand, rm, result, flags
        (1, 0, 0x3FF8000000000000, 0, 2, 0x01),
        (1, 0, 0x3FF8000000000000, 1, 1, 0x01),
        (1, 0, 0x3FF8000000000000, 2, 1, 0x01),
        (1, 0, 0x3FF8000000000000, 3, 2, 0x01),
        (1, 0, 0x3FF8000000000000, 4, 2, 0x01),
        (1, 0, 0xBFF8000000000000, 0, 0xFFFFFFFFFFFFFFFE, 0x01),
        (1, 0, 0xBFF8000000000000, 1, 0xFFFFFFFFFFFFFFFF, 0x01),
        (1, 0, 0xBFF8000000000000, 2, 0xFFFFFFFFFFFFFFFE, 0x01),
        (1, 0, 0xBFF8000000000000, 3, 0xFFFFFFFFFFFFFFFF, 0x01),
        (1, 0, 0xBFF8000000000000, 4, 0xFFFFFFFFFFFFFFFE, 0x01),
        # Tie-to-even and tie-to-maximum-magnitude differ at 0.5.
        (1, 0, 0x3FE0000000000000, 0, 0, 0x01),
        (1, 0, 0x3FE0000000000000, 4, 1, 0x01),
        (1, 0, 0xBFE0000000000000, 0, 0, 0x01),
        (1, 0, 0xBFE0000000000000, 4, 0xFFFFFFFFFFFFFFFF, 0x01),
        # Tiny finite values are inexact but not invalid.
        (1, 0, 0x0000000000000001, 0, 0, 0x01),
        (1, 0, 0x8000000000000001, 3, 0, 0x01),
        # Unsigned negative values are valid only when rounding produces zero.
        (1, 1, 0xBFE0000000000000, 1, 0, 0x01),
        (1, 1, 0xBFE0000000000000, 3, 0, 0x01),
        (1, 1, 0xBFE0000000000000, 2, 0, 0x10),
        (1, 1, 0xBFE0000000000000, 4, 0, 0x10),
        # Signed 64-bit endpoints and their first out-of-range neighbor.
        (1, 0, 0xC3E0000000000000, 0, 0x8000000000000000, 0),
        (1, 0, 0x43E0000000000000, 0, 0x7FFFFFFFFFFFFFFF, 0x10),
        # NaNs saturate high independent of sign; infinities saturate by sign.
        (1, 0, 0x7FF8000000001234, 0, 0x7FFFFFFFFFFFFFFF, 0x10),
        (1, 0, 0xFFF0000000001234, 0, 0x7FFFFFFFFFFFFFFF, 0x10),
        (1, 0, 0x7FF0000000000000, 0, 0x7FFFFFFFFFFFFFFF, 0x10),
        (1, 0, 0xFFF0000000000000, 0, 0x8000000000000000, 0x10),
        (1, 1, 0x7FF8000000001234, 0, 0xFFFFFFFFFFFFFFFF, 0x10),
        (1, 1, 0xFFF0000000000000, 0, 0, 0x10),
        # D to 32-bit signed/unsigned boundaries retain only 32 result bits.
        (0, 0, 0xC1E0000000000000, 0, 0x80000000, 0),
        (0, 0, 0x41E0000000000000, 0, 0x7FFFFFFF, 0x10),
        (0, 1, 0x41EFFFFFFFE00000, 0, 0xFFFFFFFF, 0),
        (0, 1, 0x41F0000000000000, 0, 0xFFFFFFFF, 0x10),
        (0, 1, 0xBFF0000000000000, 0, 0, 0x10),
    ]

    def process():
        yield dut.is_f64.eq(1)
        for int64, unsigned, value, rm, expected, flags in cases:
            yield dut.int64.eq(int64)
            yield dut.unsigned.eq(unsigned)
            yield dut.value.eq(value)
            yield dut.rm.eq(rm)
            yield Settle()
            result = yield dut.result
            actual_flags = yield dut.flags
            context = (int64, unsigned, hex(value), rm,
                       hex(result), hex(actual_flags))
            assert result == expected, context
            assert actual_flags == flags, context

    sim.add_process(process)
    sim.run()
