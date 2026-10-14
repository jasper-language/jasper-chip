from itertools import product

from amaranth.sim import Settle, Simulator

from rtl.pending_mask_control import PendingMaskControl


def test_each_clear_port_and_all_register_indices():
    dut = PendingMaskControl(clear_ports=3)
    sim = Simulator(dut)
    full = (1 << 32) - 1

    def proc():
        yield dut.pending_mask.eq(full)
        for port in range(3):
            for register in range(32):
                for index in range(3):
                    yield dut.clear_valid[index].eq(index == port)
                    yield dut.clear_rd[index].eq(register if index == port else 0)
                yield Settle()
                assert (yield dut.clear_mask) == 1 << register
                assert (yield dut.visible_mask) == full ^ (1 << register)

    sim.add_process(proc)
    sim.run()


def test_all_valid_combinations_overlap_and_independent_clears():
    dut = PendingMaskControl(clear_ports=3)
    sim = Simulator(dut)
    pending = (1 << 1) | (1 << 7) | (1 << 31)
    registers = (1, 7, 31)

    def proc():
        yield dut.pending_mask.eq(pending)
        for port, register in enumerate(registers):
            yield dut.clear_rd[port].eq(register)
        for valids in product((0, 1), repeat=3):
            expected_clear = 0
            for port, valid in enumerate(valids):
                yield dut.clear_valid[port].eq(valid)
                if valid:
                    expected_clear |= 1 << registers[port]
            yield Settle()
            assert (yield dut.clear_mask) == expected_clear
            assert (yield dut.visible_mask) == pending & ~expected_clear

        for port in range(3):
            yield dut.clear_rd[port].eq(13)
            yield dut.clear_valid[port].eq(1)
        yield dut.pending_mask.eq(1 << 13)
        yield Settle()
        assert (yield dut.clear_mask) == 1 << 13
        assert (yield dut.visible_mask) == 0

    sim.add_process(proc)
    sim.run()
