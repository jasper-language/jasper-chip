from amaranth.sim import Simulator

from rtl.vfsqrt_unit import VFSqrtUnit


def test_vfsqrt_ieee_cases():
    dut = VFSqrtUnit()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    cases = [
        # is_f64, operand, rm, result, flags
        (0, 0x40800000, 0, 0x40000000, 0x00),  # sqrt(4.0f) = 2.0f
        (0, 0x41100000, 0, 0x40400000, 0x00),  # sqrt(9.0f) = 3.0f
        (0, 0x00000000, 0, 0x00000000, 0x00),
        (0, 0x80000000, 0, 0x80000000, 0x00),
        (0, 0xBF800000, 0, 0x7FC00000, 0x10),
        (0, 0x7F812345, 0, 0x7FC00000, 0x10),
        (0, 0x7FC12345, 0, 0x7FC00000, 0x00),
        (0, 0x7F800000, 0, 0x7F800000, 0x00),
        (0, 0x40000000, 0, 0x3FB504F3, 0x01),
        (0, 0x40000000, 1, 0x3FB504F3, 0x01),
        (0, 0x40000000, 2, 0x3FB504F3, 0x01),
        (0, 0x40000000, 3, 0x3FB504F4, 0x01),
        (0, 0x40000000, 4, 0x3FB504F3, 0x01),
        (1, 0x4022000000000000, 0, 0x4008000000000000, 0x00),
        (1, 0x4000000000000000, 0, 0x3FF6A09E667F3BCD, 0x01),
        # Binary64 sqrt(2) distinguishes directed rounding from RNE/RMM.
        (1, 0x4000000000000000, 1, 0x3FF6A09E667F3BCC, 0x01),
        (1, 0x4000000000000000, 2, 0x3FF6A09E667F3BCC, 0x01),
        (1, 0x4000000000000000, 3, 0x3FF6A09E667F3BCD, 0x01),
        (1, 0x4000000000000000, 4, 0x3FF6A09E667F3BCD, 0x01),
        # Exact normal and subnormal-source roots do not raise NX.
        (1, 0x4010000000000000, 0, 0x4000000000000000, 0x00),
        (1, 0x3FD0000000000000, 0, 0x3FE0000000000000, 0x00),
        (1, 0x0000000000000001, 0, 0x1E60000000000000, 0x00),
        # Zero sign is preserved; negative nonzero operands raise NV.
        (1, 0x0000000000000000, 0, 0x0000000000000000, 0x00),
        (1, 0x8000000000000000, 0, 0x8000000000000000, 0x00),
        (1, 0xC010000000000000, 0, 0x7FF8000000000000, 0x10),
        # Infinity and NaN classification use canonical NaN results.
        (1, 0x7FF0000000000000, 0, 0x7FF0000000000000, 0x00),
        (1, 0xFFF0000000000000, 0, 0x7FF8000000000000, 0x10),
        (1, 0x7FF8000000001234, 0, 0x7FF8000000000000, 0x00),
        (1, 0x7FF0000000001234, 0, 0x7FF8000000000000, 0x10),
    ]

    def proc():
        for is_f64, operand, rm, expected, expected_flags in cases:
            yield dut.is_f64.eq(is_f64)
            yield dut.a.eq(operand)
            yield dut.rm.eq(rm)
            yield dut.start.eq(1)
            yield
            yield dut.start.eq(0)
            for _ in range(70):
                if (yield dut.done):
                    break
                yield
            else:
                assert False, "VFSqrtUnit did not complete"
            assert (yield dut.result) == expected
            assert (yield dut.flags) == expected_flags
            yield

    sim.add_sync_process(proc)
    sim.run()
