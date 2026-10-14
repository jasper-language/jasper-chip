from itertools import product

from amaranth.sim import Settle, Simulator

from rtl.dependency_stall_control import DependencyStallControl


def test_all_dependency_stall_input_combinations():
    dut = DependencyStallControl()
    sim = Simulator(dut)

    def proc():
        for rs1, rs2, waw, include_waw, suppress, fp_store in product(
                (0, 1), repeat=6):
            yield dut.rs1_hazard.eq(rs1)
            yield dut.rs2_hazard.eq(rs2)
            yield dut.waw_hazard.eq(waw)
            yield dut.include_waw.eq(include_waw)
            yield dut.suppress_integer.eq(suppress)
            yield dut.fp_store_hazard.eq(fp_store)
            yield Settle()
            integer = bool(rs1 or rs2 or (include_waw and waw))
            expected = bool((integer and not suppress) or fp_store)
            assert bool((yield dut.stall)) == expected

    sim.add_process(proc)
    sim.run()
