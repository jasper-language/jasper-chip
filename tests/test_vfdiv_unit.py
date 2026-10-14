"""Fast IEEE compliance tests for the shared V floating divider."""

from amaranth.sim import Simulator, Tick

from rtl.vfdiv_unit import VFDivUnit


def test_vfdiv_unit_rounding_special_values_and_flags():
    dut = VFDivUnit()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    observed = []
    cases = [
        (0, 0x3F800000, 0x40400000, 0, 0x3EAAAAAB, 0x01),
        (0, 0x3F800000, 0x40400000, 1, 0x3EAAAAAA, 0x01),
        (0, 0x3F800000, 0x40400000, 2, 0x3EAAAAAA, 0x01),
        (0, 0x3F800000, 0x40400000, 3, 0x3EAAAAAB, 0x01),
        (0, 0x3F800000, 0x40400000, 4, 0x3EAAAAAB, 0x01),
        (0, 0xBF800000, 0x40400000, 2, 0xBEAAAAAB, 0x01),
        (0, 0xBF800000, 0x40400000, 3, 0xBEAAAAAA, 0x01),
        (0, 0x40C00000, 0x40000000, 0, 0x40400000, 0x00),
        (0, 0x3F800000, 0x00000000, 0, 0x7F800000, 0x08),
        (0, 0x00000000, 0x00000000, 0, 0x7FC00000, 0x10),
        (0, 0x7F812345, 0x3F800000, 0, 0x7FC00000, 0x10),
        (0, 0x7F7FFFFF, 0x3F000000, 0, 0x7F800000, 0x05),
        (0, 0x00000001, 0x40000000, 0, 0x00000000, 0x03),
        (0, 0x00000001, 0x40000000, 4, 0x00000001, 0x03),
        (1, 0x4018000000000000, 0x4000000000000000, 0,
         0x4008000000000000, 0x00),
        (1, 0x7FF0000000000001, 0x3FF0000000000000, 0,
         0x7FF8000000000000, 0x10),
        # Binary64 recurring quotients exercise all standard rounding modes.
        (1, 0x3FF0000000000000, 0x4008000000000000, 0,
         0x3FD5555555555555, 0x01),
        (1, 0x3FF0000000000000, 0x4008000000000000, 1,
         0x3FD5555555555555, 0x01),
        (1, 0x3FF0000000000000, 0x4008000000000000, 2,
         0x3FD5555555555555, 0x01),
        (1, 0x3FF0000000000000, 0x4008000000000000, 3,
         0x3FD5555555555556, 0x01),
        (1, 0x3FF0000000000000, 0x4008000000000000, 4,
         0x3FD5555555555555, 0x01),
        (1, 0xBFF0000000000000, 0x4008000000000000, 0,
         0xBFD5555555555555, 0x01),
        (1, 0xBFF0000000000000, 0x4008000000000000, 1,
         0xBFD5555555555555, 0x01),
        (1, 0xBFF0000000000000, 0x4008000000000000, 2,
         0xBFD5555555555556, 0x01),
        (1, 0xBFF0000000000000, 0x4008000000000000, 3,
         0xBFD5555555555555, 0x01),
        # Special values distinguish DZ from NV and preserve quotient sign.
        (1, 0x3FF0000000000000, 0x0000000000000000, 0,
         0x7FF0000000000000, 0x08),
        (1, 0xBFF0000000000000, 0x0000000000000000, 0,
         0xFFF0000000000000, 0x08),
        (1, 0x0000000000000000, 0x0000000000000000, 0,
         0x7FF8000000000000, 0x10),
        (1, 0x7FF0000000000000, 0x7FF0000000000000, 0,
         0x7FF8000000000000, 0x10),
        (1, 0x7FF8000000001234, 0x3FF0000000000000, 0,
         0x7FF8000000000000, 0x00),
        (1, 0x3FF0000000000000, 0xFFF0000000000000, 0,
         0x8000000000000000, 0x00),
        # Gradual underflow: exact subnormal versus inexact half-minimum.
        (1, 0x0010000000000000, 0x4000000000000000, 0,
         0x0008000000000000, 0x00),
        (1, 0x0000000000000001, 0x4000000000000000, 0,
         0x0000000000000000, 0x03),
        (1, 0x0000000000000001, 0x4000000000000000, 3,
         0x0000000000000001, 0x03),
        (1, 0x0000000000000001, 0x4000000000000000, 4,
         0x0000000000000001, 0x03),
        (1, 0x8000000000000001, 0x4000000000000000, 2,
         0x8000000000000001, 0x03),
        (1, 0x8000000000000001, 0x4000000000000000, 3,
         0x8000000000000000, 0x03),
        # Overflow destination depends on sign and directed rounding.
        (1, 0x7FEFFFFFFFFFFFFF, 0x3FE0000000000000, 0,
         0x7FF0000000000000, 0x05),
        (1, 0x7FEFFFFFFFFFFFFF, 0x3FE0000000000000, 1,
         0x7FEFFFFFFFFFFFFF, 0x05),
        (1, 0xFFEFFFFFFFFFFFFF, 0x3FE0000000000000, 2,
         0xFFF0000000000000, 0x05),
        (1, 0xFFEFFFFFFFFFFFFF, 0x3FE0000000000000, 3,
         0xFFEFFFFFFFFFFFFF, 0x05),
    ]

    def process():
        for is_f64, a, b, rm, expected, flags in cases:
            yield dut.is_f64.eq(is_f64)
            yield dut.a.eq(a)
            yield dut.b.eq(b)
            yield dut.rm.eq(rm)
            yield dut.start.eq(1)
            yield Tick()
            yield dut.start.eq(0)
            for _ in range(64):
                if (yield dut.done):
                    break
                yield Tick()
            else:
                raise AssertionError("VFDivUnit did not complete")
            observed.append(((yield dut.result), (yield dut.flags), expected, flags))
            yield Tick()

    sim.add_process(process)
    sim.run()
    for result, flags, expected, expected_flags in observed:
        assert result == expected
        assert flags == expected_flags
