"""Complete RV32 Zcb compressed-instruction expansion matrix."""

from amaranth.sim import Settle, Simulator

from rtl.isa import LOAD, OP, OP_IMM, STORE, enc_i, enc_r
from rtl.isa_c_expand import CExpander
from rtl.rv12_core import RV12Core


def enc_s(funct3, rs1, rs2, imm=0):
    imm &= 0xFFF
    return ((imm >> 5) << 25) | (rs2 << 20) | (rs1 << 15) | (funct3 << 12) | ((imm & 0x1F) << 7) | STORE


def q0(funct2, bit6=0):
    return (0b100 << 13) | (funct2 << 10) | (2 << 7) | (bit6 << 6) | (1 << 2) | 0b00


def q1(op5, subop):
    return (0b100 << 13) | (1 << 12) | (0b11 << 10) | (2 << 7) | (op5 << 5) | (subop << 2) | 0b01


def test_rv32_zcb_all_standard_encodings_expand():
    dut = CExpander(xlen=32)
    sim = Simulator(dut)
    cases = [
        (q0(0b00), enc_i(LOAD, 9, 0b100, 10, 0)),
        (q0(0b01), enc_i(LOAD, 9, 0b101, 10, 0)),
        (q0(0b01, 1), enc_i(LOAD, 9, 0b001, 10, 0)),
        (q0(0b10), enc_s(0b000, 10, 9)),
        (q0(0b11), enc_s(0b001, 10, 9)),
        (q1(0b10, 1), enc_r(OP, 10, 0b000, 10, 9, 0b0000001)),
        (q1(0b11, 0b000), enc_i(OP_IMM, 10, 0b111, 10, 0x0FF)),
        (q1(0b11, 0b001), enc_i(OP_IMM, 10, 0b001, 10, 0x604)),
        (q1(0b11, 0b010), enc_r(OP, 10, 0b100, 10, 0, 0b0000100)),
        (q1(0b11, 0b011), enc_i(OP_IMM, 10, 0b001, 10, 0x605)),
        (q1(0b11, 0b101), enc_i(OP_IMM, 10, 0b100, 10, -1)),
    ]

    def process():
        yield dut.valid.eq(1)
        for compressed, expanded in cases:
            yield dut.insn16.eq(compressed)
            yield Settle()
            assert (yield dut.illegal) == 0
            assert (yield dut.is_compressed) == 1
            assert (yield dut.insn32) == expanded

    sim.add_process(process)
    sim.run()


def test_zcb_explicit_and_star_configurations_enable_compressed_execution():
    explicit = RV12Core(core_id=0, xlen=32, extensions="RV32I+GC+ZCB")
    star = RV12Core(core_id=0, xlen=32, extensions="RV32I+GC+*")
    assert "C" in explicit.extensions
    assert "C" in star.extensions
