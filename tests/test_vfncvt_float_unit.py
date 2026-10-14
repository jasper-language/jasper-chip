"""IEEE boundary tests for V binary64-to-binary32 narrowing."""

from amaranth.sim import Settle, Simulator

from rtl.vfncvt_float_unit import VFNarrowFloatUnit


def test_vfncvt_f64_to_f32_rounding_special_values_and_flags():
    dut = VFNarrowFloatUnit()
    sim = Simulator(dut)
    cases = [
        # value, rm, round_odd, result, flags
        (0x3FF0000000000000, 0, 0, 0x3F800000, 0),
        (0x8000000000000000, 0, 0, 0x80000000, 0),
        # Halfway above +1.0 distinguishes all standard rounding modes.
        (0x3FF0000010000000, 0, 0, 0x3F800000, 0x01),
        (0x3FF0000010000000, 1, 0, 0x3F800000, 0x01),
        (0x3FF0000010000000, 2, 0, 0x3F800000, 0x01),
        (0x3FF0000010000000, 3, 0, 0x3F800001, 0x01),
        (0x3FF0000010000000, 4, 0, 0x3F800001, 0x01),
        # Negative directed rounding reverses the RDN/RUP choice.
        (0xBFF0000010000000, 0, 0, 0xBF800000, 0x01),
        (0xBFF0000010000000, 1, 0, 0xBF800000, 0x01),
        (0xBFF0000010000000, 2, 0, 0xBF800001, 0x01),
        (0xBFF0000010000000, 3, 0, 0xBF800000, 0x01),
        (0xBFF0000010000000, 4, 0, 0xBF800001, 0x01),
        # Round-to-odd forces the retained significand LSB when inexact.
        (0x3FF0000010000000, 0, 1, 0x3F800001, 0x01),
        (0x3FF0000030000000, 0, 1, 0x3F800001, 0x01),
        # Exact extrema and overflow destination selection.
        (0x47EFFFFFE0000000, 0, 0, 0x7F7FFFFF, 0),
        (0x47F0000000000000, 0, 0, 0x7F800000, 0x05),
        (0x47F0000000000000, 1, 0, 0x7F7FFFFF, 0x05),
        (0x47F0000000000000, 2, 0, 0x7F7FFFFF, 0x05),
        (0x47F0000000000000, 3, 0, 0x7F800000, 0x05),
        (0xC7F0000000000000, 2, 0, 0xFF800000, 0x05),
        (0xC7F0000000000000, 3, 0, 0xFF7FFFFF, 0x05),
        (0x47F0000000000000, 0, 1, 0x7F7FFFFF, 0x05),
        # Exact minimum normal/subnormal and inexact half-minimum subnormal.
        (0x3810000000000000, 0, 0, 0x00800000, 0),
        (0x36A0000000000000, 0, 0, 0x00000001, 0),
        (0x3690000000000000, 0, 0, 0x00000000, 0x03),
        (0x3690000000000000, 1, 0, 0x00000000, 0x03),
        (0x3690000000000000, 2, 0, 0x00000000, 0x03),
        (0x3690000000000000, 3, 0, 0x00000001, 0x03),
        (0x3690000000000000, 4, 0, 0x00000001, 0x03),
        (0xB690000000000000, 2, 0, 0x80000001, 0x03),
        (0xB690000000000000, 3, 0, 0x80000000, 0x03),
        (0x3690000000000000, 0, 1, 0x00000001, 0x03),
        # NaNs canonicalize, signaling NaNs raise NV, infinities preserve sign.
        (0x7FF8000000001234, 0, 0, 0x7FC00000, 0),
        (0x7FF0000000001234, 0, 0, 0x7FC00000, 0x10),
        (0x7FF0000000000000, 0, 0, 0x7F800000, 0),
        (0xFFF0000000000000, 0, 0, 0xFF800000, 0),
    ]

    def process():
        for value, rm, round_odd, expected, flags in cases:
            yield dut.value.eq(value)
            yield dut.rm.eq(rm)
            yield dut.round_odd.eq(round_odd)
            yield Settle()
            result = yield dut.result
            actual_flags = yield dut.flags
            context = (hex(value), rm, round_odd,
                       hex(result), hex(actual_flags))
            assert result == expected, context
            assert actual_flags == flags, context

    sim.add_process(process)
    sim.run()
