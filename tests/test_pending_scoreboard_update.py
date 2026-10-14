from itertools import product

from amaranth.sim import Settle, Simulator

from rtl.pending_scoreboard_update import PendingScoreboardUpdate


def test_each_set_and_clear_port_all_registers():
    dut = PendingScoreboardUpdate(set_ports=2, clear_ports=4)
    sim = Simulator(dut)

    def proc():
        for port in range(2):
            for register in range(32):
                yield dut.current_mask.eq(0)
                for index in range(2):
                    yield dut.set_valid[index].eq(index == port)
                    yield dut.set_rd[index].eq(register)
                for index in range(4):
                    yield dut.clear_valid[index].eq(0)
                yield Settle()
                assert (yield dut.set_mask) == 1 << register
                assert (yield dut.next_mask) == 1 << register

        full = (1 << 32) - 1
        for port in range(4):
            for register in range(32):
                yield dut.current_mask.eq(full)
                for index in range(2):
                    yield dut.set_valid[index].eq(0)
                for index in range(4):
                    yield dut.clear_valid[index].eq(index == port)
                    yield dut.clear_rd[index].eq(register)
                yield Settle()
                assert (yield dut.clear_mask) == 1 << register
                assert (yield dut.next_mask) == full ^ (1 << register)

    sim.add_process(proc)
    sim.run()


def test_all_port_valid_combinations_and_clear_priority():
    dut = PendingScoreboardUpdate(set_ports=2, clear_ports=4)
    sim = Simulator(dut)
    set_registers = (5, 9)
    clear_registers = (5, 13, 17, 9)
    current = (1 << 13) | (1 << 21)

    def proc():
        yield dut.current_mask.eq(current)
        for port, register in enumerate(set_registers):
            yield dut.set_rd[port].eq(register)
        for port, register in enumerate(clear_registers):
            yield dut.clear_rd[port].eq(register)
        for valids in product((0, 1), repeat=6):
            expected_set = 0
            expected_clear = 0
            for port in range(2):
                yield dut.set_valid[port].eq(valids[port])
                if valids[port]:
                    expected_set |= 1 << set_registers[port]
            for port in range(4):
                yield dut.clear_valid[port].eq(valids[port + 2])
                if valids[port + 2]:
                    expected_clear |= 1 << clear_registers[port]
            yield Settle()
            assert (yield dut.set_mask) == expected_set
            assert (yield dut.clear_mask) == expected_clear
            assert (yield dut.next_mask) == (
                (current | expected_set) & ~expected_clear
            )

    sim.add_process(proc)
    sim.run()
