from amaranth.sim import Settle, Simulator

from rtl.qfadd_unit import QFAddUnit
from rtl.qfdiv_unit import QFDivUnit
from rtl.qffma_unit import QFFMAUnit
from rtl.qfmul_unit import QFMulUnit
from rtl.qfsqrt_unit import QFSqrtUnit


Q_ONE = 0x3FFF << 112
Q_TWO = 0x4000 << 112
Q_THREE = (0x4000 << 112) | (1 << 111)
Q_FOUR = 0x4001 << 112
Q_TEN = (0x4002 << 112) | (1 << 110)
Q_INF = 0x7FFF << 112
Q_NINF = (1 << 127) | Q_INF
Q_SNAN = Q_INF | 1
Q_QNAN = Q_INF | (1 << 111)


def run_binary(unit_type, cases):
    dut = unit_type()
    sim = Simulator(dut)

    def process():
        for a, b, rm, expected, flags in cases:
            yield dut.a.eq(a)
            yield dut.b.eq(b)
            yield dut.rm.eq(rm)
            yield Settle()
            assert (yield dut.result) == expected
            assert (yield dut.flags) == flags

    sim.add_process(process)
    sim.run()


def test_q_add_subtract_all_rounding_modes_and_specials():
    for subtract, expected in ((0, Q_THREE), (1, Q_ONE)):
        dut = QFAddUnit()
        sim = Simulator(dut)

        def process():
            for rm in range(5):
                yield dut.a.eq(Q_TWO)
                yield dut.b.eq(Q_ONE)
                yield dut.subtract.eq(subtract)
                yield dut.rm.eq(rm)
                yield Settle()
                assert (yield dut.result) == expected
                assert (yield dut.flags) == 0
            yield dut.a.eq(Q_INF)
            yield dut.b.eq(Q_NINF if not subtract else Q_INF)
            yield dut.rm.eq(0)
            yield Settle()
            assert (yield dut.result) == Q_QNAN
            assert (yield dut.flags) == 0b10000

        sim.add_process(process)
        sim.run()


def test_q_multiply_all_rounding_modes_and_invalid():
    cases = [(Q_TWO, Q_TWO, rm, Q_FOUR, 0) for rm in range(5)]
    cases.append((0, Q_INF, 0, Q_QNAN, 0b10000))
    cases.append((Q_SNAN, Q_ONE, 0, Q_QNAN, 0b10000))
    run_binary(QFMulUnit, cases)


def test_q_divide_all_rounding_modes_and_divide_by_zero():
    cases = [(Q_FOUR, Q_TWO, rm, Q_TWO, 0) for rm in range(5)]
    cases.append((Q_ONE, 0, 0, Q_INF, 0b01000))
    cases.append((0, 0, 0, Q_QNAN, 0b10000))
    run_binary(QFDivUnit, cases)


def test_q_sqrt_all_rounding_modes_and_specials():
    dut = QFSqrtUnit()
    sim = Simulator(dut)

    def process():
        for rm in range(5):
            yield dut.a.eq(Q_FOUR)
            yield dut.rm.eq(rm)
            yield Settle()
            assert (yield dut.result) == Q_TWO
            assert (yield dut.flags) == 0
        yield dut.a.eq((1 << 127) | Q_ONE)
        yield dut.rm.eq(0)
        yield Settle()
        assert (yield dut.result) == Q_QNAN
        assert (yield dut.flags) == 0b10000
        yield dut.a.eq(Q_SNAN)
        yield Settle()
        assert (yield dut.result) == Q_QNAN
        assert (yield dut.flags) == 0b10000

    sim.add_process(process)
    sim.run()


def test_q_fma_four_sign_variants_all_rounding_modes():
    variants = (
        (0, 0, Q_TEN),       # 2 * 3 + 4
        (0, 1, Q_TWO),       # 2 * 3 - 4
        (1, 0, (1 << 127) | Q_TWO),   # -(2 * 3) + 4
        (1, 1, (1 << 127) | Q_TEN),   # -(2 * 3) - 4
    )
    dut = QFFMAUnit()
    sim = Simulator(dut)

    def process():
        for negate_product, negate_addend, expected in variants:
            for rm in range(5):
                yield dut.a.eq(Q_TWO)
                yield dut.b.eq(Q_THREE)
                yield dut.c.eq(Q_FOUR)
                yield dut.negate_product.eq(negate_product)
                yield dut.negate_addend.eq(negate_addend)
                yield dut.rm.eq(rm)
                yield Settle()
                assert (yield dut.result) == expected
                assert (yield dut.flags) == 0
        yield dut.a.eq(0)
        yield dut.b.eq(Q_INF)
        yield dut.c.eq(Q_ONE)
        yield dut.negate_product.eq(0)
        yield dut.negate_addend.eq(0)
        yield dut.rm.eq(0)
        yield Settle()
        assert (yield dut.result) == Q_QNAN
        assert (yield dut.flags) == 0b10000

    sim.add_process(process)
    sim.run()
