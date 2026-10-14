from itertools import product

from amaranth.sim import Settle, Simulator

from rtl.is_advance_control import ISAdvanceControl


def test_is_advance_control_all_input_combinations():
    dut = ISAdvanceControl()
    sim = Simulator(dut)

    def proc():
        for redirect, stall_front, is_valid, stall_dep_id2 in product(
                (0, 1), repeat=4):
            yield dut.redirect.eq(redirect)
            yield dut.stall_front.eq(stall_front)
            yield dut.is_valid.eq(is_valid)
            yield dut.stall_dep_id2.eq(stall_dep_id2)
            yield Settle()

            expected_clear = bool(
                redirect or (stall_front and is_valid) or stall_dep_id2)
            expected_fill = not expected_clear
            expected_consume = bool(
                stall_front and not is_valid and
                not redirect and not stall_dep_id2)

            assert bool((yield dut.clear_is)) == expected_clear
            assert bool((yield dut.fill_is)) == expected_fill
            assert bool((yield dut.consume_id2)) == expected_consume

    sim.add_process(proc)
    sim.run()
