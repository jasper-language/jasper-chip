from itertools import product

from amaranth.sim import Settle, Simulator

from rtl.base_rs1_usage_control import BaseRS1UsageControl


def test_all_base_rs1_usage_combinations():
    dut = BaseRS1UsageControl()
    sim = Simulator(dut)

    def proc():
        for valid, is_jal, is_fence in product((0, 1), repeat=3):
            yield dut.valid.eq(valid)
            yield dut.is_jal.eq(is_jal)
            yield dut.is_fence.eq(is_fence)
            yield Settle()
            assert bool((yield dut.uses_rs1)) == bool(
                valid and not is_jal and not is_fence
            )

    sim.add_process(proc)
    sim.run()
