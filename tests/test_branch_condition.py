import pytest
from amaranth.sim import Settle, Simulator

from rtl.branch_condition import BranchCondition


def _signed(value, xlen):
    sign = 1 << (xlen - 1)
    return value - (1 << xlen) if value & sign else value


@pytest.mark.parametrize("xlen", [32, 64])
def test_all_branch_conditions_and_boundaries(xlen):
    dut = BranchCondition(xlen)
    sim = Simulator(dut)
    mask = (1 << xlen) - 1
    values = (0, 1, 2, mask, 1 << (xlen - 1), (1 << (xlen - 1)) - 1)

    def expected(funct3, lhs, rhs):
        if funct3 == 0b000:
            return lhs == rhs
        if funct3 == 0b001:
            return lhs != rhs
        if funct3 == 0b100:
            return _signed(lhs, xlen) < _signed(rhs, xlen)
        if funct3 == 0b101:
            return _signed(lhs, xlen) >= _signed(rhs, xlen)
        if funct3 == 0b110:
            return lhs < rhs
        if funct3 == 0b111:
            return lhs >= rhs
        return False

    def proc():
        for funct3 in range(8):
            yield dut.funct3.eq(funct3)
            for lhs in values:
                yield dut.lhs.eq(lhs)
                for rhs in values:
                    yield dut.rhs.eq(rhs)
                    yield Settle()
                    assert bool((yield dut.taken)) == expected(funct3, lhs, rhs)

    sim.add_process(proc)
    sim.run()
