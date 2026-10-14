import pytest
from amaranth.sim import Settle, Simulator

from rtl.jump_control import JumpControl


@pytest.mark.parametrize("xlen", [32, 64])
def test_jal_and_jalr_link_target_boundaries(xlen):
    dut = JumpControl(xlen)
    sim = Simulator(dut)
    mask = (1 << xlen) - 1
    values = (0, 1, 2, 3, mask, mask - 1, 1 << (xlen - 1))
    immediates = (0, 1, 2, mask, mask - 1, 1 << (xlen - 1))

    def proc():
        for compressed in (0, 1):
            yield dut.compressed.eq(compressed)
            for jalr in (0, 1):
                yield dut.jalr.eq(jalr)
                for pc in values:
                    yield dut.pc.eq(pc)
                    for base in values:
                        yield dut.base.eq(base)
                        for imm in immediates:
                            yield dut.imm.eq(imm)
                            yield Settle()
                            assert (yield dut.link) == (
                                pc + (2 if compressed else 4)
                            ) & mask
                            expected = ((base + imm) & mask) & ~1 if jalr else (
                                pc + imm
                            ) & mask
                            assert (yield dut.target) == expected

    sim.add_process(proc)
    sim.run()
