"""IEEE boundary tests for the shared V integer-to-float converter."""

from amaranth.sim import Settle, Simulator

from rtl.vfcvt_unit import VFIntToFloatUnit


def test_vfcvt_integer_to_float_widths_rounding_and_flags():
    dut = VFIntToFloatUnit()
    sim = Simulator(dut)
    cases = [
        # is_f64, int64, unsigned, value, rm, result, flags
        (1, 1, 0, 0x0000000000000000, 0, 0x0000000000000000, 0),
        (1, 1, 0, 0x8000000000000000, 0, 0xC3E0000000000000, 0),
        # INT64_MAX rounds around the exact 2^63 boundary.
        (1, 1, 0, 0x7FFFFFFFFFFFFFFF, 0, 0x43E0000000000000, 1),
        (1, 1, 0, 0x7FFFFFFFFFFFFFFF, 1, 0x43DFFFFFFFFFFFFF, 1),
        (1, 1, 0, 0x7FFFFFFFFFFFFFFF, 2, 0x43DFFFFFFFFFFFFF, 1),
        (1, 1, 0, 0x7FFFFFFFFFFFFFFF, 3, 0x43E0000000000000, 1),
        (1, 1, 0, 0x7FFFFFFFFFFFFFFF, 4, 0x43E0000000000000, 1),
        # The negative counterpart distinguishes RDN from RUP/RTZ.
        (1, 1, 0, 0x8000000000000001, 0, 0xC3E0000000000000, 1),
        (1, 1, 0, 0x8000000000000001, 1, 0xC3DFFFFFFFFFFFFF, 1),
        (1, 1, 0, 0x8000000000000001, 2, 0xC3E0000000000000, 1),
        (1, 1, 0, 0x8000000000000001, 3, 0xC3DFFFFFFFFFFFFF, 1),
        # UINT64_MAX uses the neighboring values around 2^64.
        (1, 1, 1, 0xFFFFFFFFFFFFFFFF, 0, 0x43F0000000000000, 1),
        (1, 1, 1, 0xFFFFFFFFFFFFFFFF, 1, 0x43EFFFFFFFFFFFFF, 1),
        (1, 1, 1, 0xFFFFFFFFFFFFFFFF, 2, 0x43EFFFFFFFFFFFFF, 1),
        (1, 1, 1, 0xFFFFFFFFFFFFFFFF, 3, 0x43F0000000000000, 1),
        (1, 1, 1, 0xFFFFFFFFFFFFFFFF, 4, 0x43F0000000000000, 1),
        # Halfway integers around 2^53 distinguish RNE from RMM.
        (1, 1, 1, 0x0020000000000001, 0, 0x4340000000000000, 1),
        (1, 1, 1, 0x0020000000000001, 4, 0x4340000000000001, 1),
        (1, 1, 1, 0x0020000000000003, 0, 0x4340000000000002, 1),
        # Binary32 destinations exercise both 32- and 64-bit sources.
        (0, 0, 1, 0x00000000FFFFFFFF, 0, 0x000000004F800000, 1),
        (0, 0, 1, 0x00000000FFFFFFFF, 1, 0x000000004F7FFFFF, 1),
        (0, 0, 0, 0x000000007FFFFFFF, 0, 0x000000004F000000, 1),
        (0, 0, 0, 0x000000007FFFFFFF, 1, 0x000000004EFFFFFF, 1),
        (0, 1, 1, 0xFFFFFFFFFFFFFFFF, 0, 0x000000005F800000, 1),
        (0, 1, 1, 0xFFFFFFFFFFFFFFFF, 1, 0x000000005F7FFFFF, 1),
    ]

    def process():
        for is_f64, int64, unsigned, value, rm, expected, flags in cases:
            yield dut.is_f64.eq(is_f64)
            yield dut.int64.eq(int64)
            yield dut.unsigned.eq(unsigned)
            yield dut.value.eq(value)
            yield dut.rm.eq(rm)
            yield Settle()
            result = yield dut.result
            actual_flags = yield dut.flags
            context = (is_f64, int64, unsigned, hex(value), rm,
                       hex(result), hex(actual_flags))
            assert result == expected, context
            assert actual_flags == flags, context
            assert (yield dut.rm_valid) == 1, context

        for rm in (5, 6, 7):
            yield dut.rm.eq(rm)
            yield Settle()
            assert (yield dut.rm_valid) == 0

    sim.add_process(process)
    sim.run()
