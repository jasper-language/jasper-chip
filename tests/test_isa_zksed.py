import pytest
from amaranth.hdl import Fragment
from amaranth.sim import Settle, Simulator

from rtl.isa import OP
from rtl.isa_zksed import Zksed
from rtl.rv12_core import RV12Core, normalize_extension_spec
from rtl.sm4 import SM4_SBOX

MASK32 = 0xFFFFFFFF


def rol32(value, amount):
    return ((value << amount) | (value >> ((32 - amount) & 31))) & MASK32


def reference(rs1, rs2, funct5, bs):
    x = SM4_SBOX[(rs2 >> (8 * bs)) & 0xFF]
    if funct5 == 0b11000:
        y = x ^ (x << 8) ^ (x << 2) ^ (x << 18) ^ \
            ((x & 0x3F) << 26) ^ ((x & 0xC0) << 10)
    else:
        y = x ^ ((x & 0x07) << 29) ^ ((x & 0xFE) << 7) ^ \
            ((x & 0x01) << 23) ^ ((x & 0xF8) << 13)
    return (rs1 ^ rol32(y & MASK32, 8 * bs)) & MASK32


@pytest.mark.parametrize("funct5", [0b11000, 0b11010])
def test_sm4ed_and_sm4ks_all_byte_selectors(funct5):
    dut = Zksed(xlen=32)
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
            expected = reference(rs1, rs2, funct5, bs)
            assert (yield dut.matched) == 1
            assert (yield dut.wb_en) == 1
            assert (yield dut.wb_data) == expected
            assert (yield dut.alu_out) == expected

    sim.add_process(process)
    sim.run()


@pytest.mark.parametrize("spec", ["RV32I+GC+ZKSED", "RV32I+GC+*"])
def test_zksed_is_retained_and_core_elaborates(spec):
    assert "ZKSED" in normalize_extension_spec(spec)
    core = RV12Core(xlen=32, extensions=spec)
    assert core.enable_zksed
    Fragment.get(core, platform=None)


def test_zksed_rejects_unallocated_funct5_and_wrong_funct3():
    dut = Zksed(xlen=32)
    sim = Simulator(dut)

    def process():
        yield dut.valid.eq(1)
        yield dut.opcode.eq(OP)
        yield dut.funct3.eq(0)
        yield dut.funct7.eq(0b11001)
        yield Settle()
        assert (yield dut.matched) == 0
        yield dut.funct7.eq(0b11000)
        yield dut.funct3.eq(1)
        yield Settle()
        assert (yield dut.matched) == 0

    sim.add_process(process)
    sim.run()
