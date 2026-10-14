import pytest
from amaranth.sim import Settle, Simulator

from rtl.isa_c_expand import CExpander


def encode_cj(funct3, offset):
    value = offset & 0xFFF
    insn = (funct3 << 13) | 0b01
    insn |= ((value >> 11) & 1) << 12
    insn |= ((value >> 4) & 1) << 11
    insn |= ((value >> 8) & 0x3) << 9
    insn |= ((value >> 10) & 1) << 8
    insn |= ((value >> 6) & 1) << 7
    insn |= ((value >> 7) & 1) << 6
    insn |= ((value >> 1) & 0x7) << 3
    insn |= ((value >> 5) & 1) << 2
    return insn


def encode_cb(funct3, rs1_prime, offset):
    value = offset & 0x1FF
    insn = (funct3 << 13) | (rs1_prime << 7) | 0b01
    insn |= ((value >> 8) & 1) << 12
    insn |= ((value >> 3) & 0x3) << 10
    insn |= ((value >> 6) & 0x3) << 5
    insn |= ((value >> 1) & 0x3) << 3
    insn |= ((value >> 5) & 1) << 2
    return insn


def enc_jal(rd, offset):
    value = offset & 0x1FFFFF
    return (((value >> 20) & 1) << 31) | (((value >> 1) & 0x3FF) << 21) | \
        (((value >> 11) & 1) << 20) | (((value >> 12) & 0xFF) << 12) | \
        (rd << 7) | 0x6F


def enc_branch(funct3, rs1, offset):
    value = offset & 0x1FFF
    return (((value >> 12) & 1) << 31) | (((value >> 5) & 0x3F) << 25) | \
        (rs1 << 15) | (funct3 << 12) | (((value >> 1) & 0xF) << 8) | \
        (((value >> 11) & 1) << 7) | 0x63


@pytest.mark.parametrize("funct3,rd,offset", [
    (0b101, 0, -2048), (0b101, 0, -2), (0b101, 0, 2046),
    (0b001, 1, -2048), (0b001, 1, -2), (0b001, 1, 2046),
])
def test_c_j_and_c_jal_full_signed_offset_range(funct3, rd, offset):
    dut = CExpander(xlen=32)
    sim = Simulator(dut)

    def process():
        yield dut.valid.eq(1)
        yield dut.insn16.eq(encode_cj(funct3, offset))
        yield Settle()
        assert (yield dut.illegal) == 0
        assert (yield dut.insn32) == enc_jal(rd, offset)

    sim.add_process(process)
    sim.run()


@pytest.mark.parametrize("funct3,base_funct3,offset", [
    (0b110, 0b000, -256), (0b110, 0b000, 254),
    (0b111, 0b001, -256), (0b111, 0b001, 254),
])
def test_c_beqz_and_c_bnez_full_signed_offset_range(funct3, base_funct3, offset):
    dut = CExpander(xlen=32)
    sim = Simulator(dut)

    def process():
        yield dut.valid.eq(1)
        yield dut.insn16.eq(encode_cb(funct3, 3, offset))
        yield Settle()
        assert (yield dut.illegal) == 0
        assert (yield dut.insn32) == enc_branch(base_funct3, 11, offset)

    sim.add_process(process)
    sim.run()


@pytest.mark.parametrize("compressed,expanded", [
    (0x8006, 0x00100033),  # C.MV x0,x1 hint
    (0x9006, 0x00100033),  # C.ADD x0,x1 hint
    (0x4005, 0x00100013),  # C.LI x0,1 hint
    (0x0006, 0x00101013),  # C.SLLI x0,1 hint
])
def test_zca_rd_x0_hint_code_points_are_legal(compressed, expanded):
    dut = CExpander(xlen=32)
    sim = Simulator(dut)

    def process():
        yield dut.valid.eq(1)
        yield dut.insn16.eq(compressed)
        yield Settle()
        assert (yield dut.illegal) == 0
        assert (yield dut.insn32) == expanded

    sim.add_process(process)
    sim.run()


def test_c_jr_x0_remains_illegal_reserved_encoding():
    dut = CExpander(xlen=32)
    sim = Simulator(dut)

    def process():
        yield dut.valid.eq(1)
        yield dut.insn16.eq(0x8002)
        yield Settle()
        assert (yield dut.illegal) == 1

    sim.add_process(process)
    sim.run()
