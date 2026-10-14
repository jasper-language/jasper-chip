from itertools import product

from amaranth.sim import Settle, Simulator

from rtl.base_rd_write_control import BaseRDWriteControl
from rtl.isa import AMO, AUIPC, JALR, LUI, OP, OP_32, OP_IMM, OP_IMM_32


def test_all_opcodes_and_control_combinations():
    dut = BaseRDWriteControl()
    sim = Simulator(dut)
    writing_opcodes = {OP_IMM, OP_IMM_32, OP, OP_32, LUI, AUIPC, JALR}

    def proc():
        for opcode in range(128):
            yield dut.opcode.eq(opcode)
            for integer_load, is_jal, enable_a in product((0, 1), repeat=3):
                yield dut.integer_load.eq(integer_load)
                yield dut.is_jal.eq(is_jal)
                yield dut.enable_a.eq(enable_a)
                yield Settle()
                expected = (
                    opcode in writing_opcodes or integer_load or is_jal or
                    (enable_a and opcode == AMO)
                )
                assert bool((yield dut.writes_rd)) == expected

    sim.add_process(proc)
    sim.run()
