import pytest
from amaranth.sim import Settle, Simulator

from rtl.isa_c_expand import CExpander

OP_IMM = 0x13
LUI = 0x37


def enc_i(rd, rs1, immediate):
    return ((immediate & 0xFFF) << 20) | (rs1 << 15) | (rd << 7) | OP_IMM


def enc_u(rd, immediate20):
    return ((immediate20 & 0xFFFFF) << 12) | (rd << 7) | LUI


@pytest.mark.parametrize("compressed,expanded", [
    (0x0024, enc_i(9, 2, 4)),          # C.ADDI4SPN x9,sp,4
    (0x1FFC, enc_i(15, 2, 1020)),      # C.ADDI4SPN x15,sp,1020
    (0x6141, enc_i(2, 2, 16)),         # C.ADDI16SP sp,16
    (0x717D, enc_i(2, 2, -16)),        # C.ADDI16SP sp,-16
    (0x6185, enc_u(3, 1)),             # C.LUI x3,1
    (0x71FD, enc_u(3, -1)),            # C.LUI x3,-1
])
def test_zca_stack_and_lui_immediates_expand_completely(compressed, expanded):
    dut = CExpander(xlen=32)
    sim = Simulator(dut)

    def process():
        yield dut.valid.eq(1)
        yield dut.insn16.eq(compressed)
        yield Settle()
        assert (yield dut.is_compressed) == 1
        assert (yield dut.illegal) == 0
        assert (yield dut.insn32) == expanded

    sim.add_process(process)
    sim.run()


def test_all_c_addi_zero_immediate_code_points_are_legal_hints():
    dut = CExpander(xlen=32)
    sim = Simulator(dut)

    def process():
        yield dut.valid.eq(1)
        for rd in range(1, 32):
            yield dut.insn16.eq((rd << 7) | 0b01)
            yield Settle()
            assert (yield dut.illegal) == 0
            assert (yield dut.insn32) == enc_i(rd, rd, 0)

    sim.add_process(process)
    sim.run()


def test_c_nop_nonzero_immediate_hint_is_legal():
    dut = CExpander(xlen=32)
    sim = Simulator(dut)

    def process():
        yield dut.valid.eq(1)
        yield dut.insn16.eq((1 << 2) | 0b01)
        yield Settle()
        assert (yield dut.illegal) == 0
        assert (yield dut.insn32) == enc_i(0, 0, 1)

    sim.add_process(process)
    sim.run()


@pytest.mark.parametrize("compressed", [
    0x0000,  # C.ADDI4SPN with zero immediate
    0x6101,  # C.ADDI16SP with zero immediate
    0x6081,  # Reserved C.LUI x1,0 (Zcmop disabled)
    0x6005,  # Reserved C.LUI x0,1
])
def test_zca_reserved_zero_immediate_encodings_remain_illegal(compressed):
    dut = CExpander(xlen=32, enable_zcmop=False)
    sim = Simulator(dut)

    def process():
        yield dut.valid.eq(1)
        yield dut.insn16.eq(compressed)
        yield Settle()
        assert (yield dut.illegal) == 1

    sim.add_process(process)
    sim.run()
