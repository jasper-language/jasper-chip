import pytest
from amaranth.hdl import Fragment
from amaranth.sim import Settle, Simulator

from rtl.aes32 import AES_INV_SBOX, AES_SBOX
from rtl.isa import OP
from rtl.isa_zknd import Zknd
from rtl.isa_zkne import Zkne
from rtl.rv12_core import RV12Core, normalize_extension_spec

MASK32 = 0xFFFFFFFF


def xtime(value):
    return ((value << 1) ^ (0x1B if value & 0x80 else 0)) & 0xFF


def rol32(value, amount):
    return ((value << amount) | (value >> ((32 - amount) & 31))) & MASK32


def reference(rs1, rs2, funct5, bs):
    inverse = funct5 in (0b10101, 0b10111)
    mix = funct5 in (0b10011, 0b10111)
    x = (AES_INV_SBOX if inverse else AES_SBOX)[(rs2 >> (8 * bs)) & 0xFF]
    if mix:
        x2 = xtime(x)
        if inverse:
            x4, x8 = xtime(x2), xtime(xtime(x2))
            word = ((x2 ^ x4 ^ x8) | ((x ^ x8) << 8) |
                    ((x ^ x4 ^ x8) << 16) | ((x ^ x2 ^ x8) << 24))
        else:
            word = x2 | (x << 8) | (x << 16) | ((x ^ x2) << 24)
    else:
        word = x
    return rs1 ^ rol32(word, 8 * bs)


@pytest.mark.parametrize("dut_type,funct5", [
    (Zkne, 0b10001), (Zkne, 0b10011),
    (Zknd, 0b10101), (Zknd, 0b10111),
])
def test_all_rv32_aes_instructions_and_byte_selectors(dut_type, funct5):
    dut = dut_type(xlen=32)
    sim = Simulator(dut)
    rs1, rs2 = 0x10203040, 0x89ABCDEF

    def process():
        yield dut.valid.eq(1)
        yield dut.opcode.eq(OP)
        yield dut.funct3.eq(0)
        yield dut.ex1_a.eq(rs1)
        yield dut.ex1_b.eq(rs2)
        for bs in range(4):
            yield dut.funct7.eq((bs << 5) | funct5)
            yield Settle()
            expected = reference(rs1, rs2, funct5, bs) & MASK32
            assert (yield dut.matched) == 1
            assert (yield dut.wb_en) == 1
            assert (yield dut.wb_data) == expected
            assert (yield dut.alu_out) == expected

    sim.add_process(process)
    sim.run()


@pytest.mark.parametrize("spec,token,attribute", [
    ("RV32I+GC+ZKNE", "ZKNE", "enable_zkne"),
    ("RV32I+GC+ZKND", "ZKND", "enable_zknd"),
    ("RV32I+GC+*", "ZKNE", "enable_zkne"),
    ("RV32I+GC+*", "ZKND", "enable_zknd"),
])
def test_aes_extensions_are_retained_and_core_elaborates(spec, token, attribute):
    assert token in normalize_extension_spec(spec)
    core = RV12Core(xlen=32, extensions=spec)
    assert getattr(core, attribute)
    Fragment.get(core, platform=None)


def test_aes_decoders_reject_wrong_funct3_and_unallocated_funct5():
    for dut in (Zkne(xlen=32), Zknd(xlen=32)):
        sim = Simulator(dut)

        def process():
            yield dut.valid.eq(1)
            yield dut.opcode.eq(OP)
            yield dut.funct3.eq(1)
            yield dut.funct7.eq(0b10001)
            yield Settle()
            assert (yield dut.matched) == 0
            yield dut.funct3.eq(0)
            yield dut.funct7.eq(0b10000)
            yield Settle()
            assert (yield dut.matched) == 0

        sim.add_process(process)
        sim.run()
