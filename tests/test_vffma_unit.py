from amaranth.sim import Settle, Simulator

from rtl.vffma_unit import VFFMAUnit


def test_vffma_binary32_binary64_widening_and_specials():
    dut = VFFMAUnit()
    sim = Simulator(dut)
    cases = []
    variants32 = (
        (0, 0, 0x41200000),
        (0, 1, 0x40000000),
        (1, 0, 0xC0000000),
        (1, 1, 0xC1200000),
    )
    variants64 = (
        (0, 0, 0x4024000000000000),
        (0, 1, 0x4000000000000000),
        (1, 0, 0xC000000000000000),
        (1, 1, 0xC024000000000000),
    )
    for negate_product, negate_addend, expected in variants32:
        for rm in range(5):
            cases.append((0x40000000, 0x40400000, 0x40800000,
                          0, 0, negate_product, negate_addend, rm,
                          expected, 0))
    for negate_product, negate_addend, expected in variants64:
        for rm in range(5):
            cases.append((0x4000000000000000, 0x4008000000000000,
                          0x4010000000000000, 1, 0,
                          negate_product, negate_addend, rm, expected, 0))
    for rm in range(5):
        cases.append((0x40000000, 0x40400000, 0x4010000000000000,
                      0, 1, 0, 0, rm, 0x4024000000000000, 0))
    cases += [
        (0, 0x7F800000, 0x3F800000, 0, 0, 0, 0, 0,
         0x7FC00000, 0b10000),
        (0x7F800001, 0x3F800000, 0, 0, 0, 0, 0, 0,
         0x7FC00000, 0b10000),
    ]

    def process():
        for (a, b, c, is_f64, widen, negate_product, negate_addend,
             rm, expected, expected_flags) in cases:
            yield dut.a.eq(a)
            yield dut.b.eq(b)
            yield dut.c.eq(c)
            yield dut.is_f64.eq(is_f64)
            yield dut.widen.eq(widen)
            yield dut.widen_addend.eq(0)
            yield dut.negate_product.eq(negate_product)
            yield dut.negate_addend.eq(negate_addend)
            yield dut.rm.eq(rm)
            yield Settle()
            mask = (1 << (64 if is_f64 or widen else 32)) - 1
            assert (yield dut.result) & mask == expected
            assert (yield dut.flags) == expected_flags

    sim.add_process(process)
    sim.run()
