from amaranth.sim import Simulator, Settle

from rtl.vfadd_unit import VFAddUnit


def test_vfadd_ieee_cases():
    dut = VFAddUnit()
    sim = Simulator(dut)
    cases = [
        (0, 0x3F800000, 0x40000000, 0, 0x40400000, 0),
        (0, 0x3F800000, 0xBF800000, 0, 0x00000000, 0),
        (0, 0x00000000, 0x80000000, 2, 0x80000000, 0),
        (0, 0x7F800000, 0xFF800000, 0, 0x7FC00000, 0x10),
        (0, 0x7F812345, 0x3F800000, 0, 0x7FC00000, 0x10),
        (0, 0x7FC12345, 0x3F800000, 0, 0x7FC00000, 0),
        (0, 0x3F800000, 0x00000001, 0, 0x3F800000, 0x01),
        (0, 0x3F800000, 0x00000001, 3, 0x3F800001, 0x01),
        (0, 0x7F7FFFFF, 0x7F7FFFFF, 0, 0x7F800000, 0x05),
        (0, 0x7F7FFFFF, 0x7F7FFFFF, 1, 0x7F7FFFFF, 0x05),
        (1, 0x3FF0000000000000, 0x4000000000000000, 0,
         0x4008000000000000, 0),
        (1, 0x7FF0000000000000, 0xFFF0000000000000, 0,
         0x7FF8000000000000, 0x10),
    ]

    def proc():
        for is_f64, a, b, rm, expected, flags in cases:
            yield dut.is_f64.eq(is_f64)
            yield dut.a.eq(a)
            yield dut.b.eq(b)
            yield dut.rm.eq(rm)
            yield Settle()
            assert (yield dut.result) == expected
            assert (yield dut.flags) == flags

    sim.add_process(proc)
    sim.run()


def test_vfadd_ieee_f64_rounding_nan_zero_subnormal_and_overflow():
    dut = VFAddUnit()
    sim = Simulator(dut)
    one = 0x3FF0000000000000
    next_one = 0x3FF0000000000001
    neg_one = 0xBFF0000000000000
    next_neg_one = 0xBFF0000000000001
    half_ulp = 0x3CA0000000000000
    neg_half_ulp = 0xBCA0000000000000
    max_finite = 0x7FEFFFFFFFFFFFFF
    neg_max_finite = 0xFFEFFFFFFFFFFFFF
    cases = [
        # Exact subnormal arithmetic must not raise UF or NX.
        (0x0000000000000001, 0x0000000000000001, 0,
         0x0000000000000002, 0),
        (0x0010000000000000, 0x800FFFFFFFFFFFFF, 0,
         0x0000000000000001, 0),
        # Exact cancellation and opposite signed zero follow RDN sign rules.
        (one, neg_one, 0, 0x0000000000000000, 0),
        (one, neg_one, 2, 0x8000000000000000, 0),
        (0x0000000000000000, 0x8000000000000000, 0,
         0x0000000000000000, 0),
        (0x0000000000000000, 0x8000000000000000, 2,
         0x8000000000000000, 0),
        # A half-ULP tie distinguishes all five standard rounding modes.
        (one, half_ulp, 0, one, 0x01),
        (one, half_ulp, 1, one, 0x01),
        (one, half_ulp, 2, one, 0x01),
        (one, half_ulp, 3, next_one, 0x01),
        (one, half_ulp, 4, next_one, 0x01),
        (neg_one, neg_half_ulp, 0, neg_one, 0x01),
        (neg_one, neg_half_ulp, 1, neg_one, 0x01),
        (neg_one, neg_half_ulp, 2, next_neg_one, 0x01),
        (neg_one, neg_half_ulp, 3, neg_one, 0x01),
        (neg_one, neg_half_ulp, 4, next_neg_one, 0x01),
        # Quiet NaNs remain quiet; signaling NaNs and inf-inf raise NV.
        (0x7FF8000000001234, one, 0, 0x7FF8000000000000, 0),
        (0x7FF0000000001234, one, 0, 0x7FF8000000000000, 0x10),
        (0x7FF0000000000000, 0xFFF0000000000000, 0,
         0x7FF8000000000000, 0x10),
        # Overflow result selection depends on direction and sign; OF implies NX.
        (max_finite, max_finite, 0, 0x7FF0000000000000, 0x05),
        (max_finite, max_finite, 1, max_finite, 0x05),
        (max_finite, max_finite, 2, max_finite, 0x05),
        (max_finite, max_finite, 3, 0x7FF0000000000000, 0x05),
        (neg_max_finite, neg_max_finite, 0, 0xFFF0000000000000, 0x05),
        (neg_max_finite, neg_max_finite, 2, 0xFFF0000000000000, 0x05),
        (neg_max_finite, neg_max_finite, 3, neg_max_finite, 0x05),
    ]

    def proc():
        yield dut.is_f64.eq(1)
        for a, b, rm, expected, flags in cases:
            yield dut.a.eq(a)
            yield dut.b.eq(b)
            yield dut.rm.eq(rm)
            yield Settle()
            assert (yield dut.result) == expected
            assert (yield dut.flags) == flags

    sim.add_process(proc)
    sim.run()
