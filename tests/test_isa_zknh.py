import pytest
from amaranth.hdl import Fragment
from amaranth.sim import Settle, Simulator

from rtl.isa_zknh import OP, OP_IMM, Zknh
from rtl.rv12_core import RV12Core, normalize_extension_spec


MASK32 = 0xFFFFFFFF


def ror32(value, amount):
    return ((value >> amount) | (value << (32 - amount))) & MASK32


def test_rv32_zknh_all_ten_standard_instructions_execute():
    dut = Zknh(xlen=32)
    sim = Simulator(dut)
    a = 0x12345678
    b = 0x9ABCDEF0
    cases = [
        (OP_IMM, 0b0001000, 0b001, 0, ror32(a, 2) ^ ror32(a, 13) ^ ror32(a, 22)),
        (OP_IMM, 0b0001000, 0b001, 1, ror32(a, 6) ^ ror32(a, 11) ^ ror32(a, 25)),
        (OP_IMM, 0b0001000, 0b001, 2, ror32(a, 7) ^ ror32(a, 18) ^ (a >> 3)),
        (OP_IMM, 0b0001000, 0b001, 3, ror32(a, 17) ^ ror32(a, 19) ^ (a >> 10)),
        (OP, 0b0101000, 0b000, 0, (a << 25) ^ (a << 30) ^ (a >> 28) ^ (b >> 7) ^ (b >> 2) ^ (b << 4)),
        (OP, 0b0101001, 0b000, 0, (a << 23) ^ (a >> 14) ^ (a >> 18) ^ (b >> 9) ^ (b << 18) ^ (b << 14)),
        (OP, 0b0101010, 0b000, 0, (a >> 1) ^ (a >> 7) ^ (a >> 8) ^ (b << 31) ^ (b << 25) ^ (b << 24)),
        (OP, 0b0101110, 0b000, 0, (a >> 1) ^ (a >> 7) ^ (a >> 8) ^ (b << 31) ^ (b << 24)),
        (OP, 0b0101011, 0b000, 0, (a << 3) ^ (a >> 6) ^ (a >> 19) ^ (b >> 29) ^ (b << 26) ^ (b << 13)),
        (OP, 0b0101111, 0b000, 0, (a << 3) ^ (a >> 6) ^ (a >> 19) ^ (b >> 29) ^ (b << 13)),
    ]

    def process():
        yield dut.valid.eq(1)
        yield dut.rs1v.eq(a)
        yield dut.rs2v.eq(b)
        for opcode, funct7, funct3, rs2, expected in cases:
            yield dut.opcode.eq(opcode)
            yield dut.funct7.eq(funct7)
            yield dut.funct3.eq(funct3)
            yield dut.rs2.eq(rs2)
            yield Settle()
            assert (yield dut.matched) == 1
            assert (yield dut.wb_en) == 1
            assert (yield dut.wb_data) == (expected & MASK32)
            assert (yield dut.alu_out) == (expected & MASK32)

    sim.add_process(process)
    sim.run()


@pytest.mark.parametrize("spec", ["RV32I+GC+ZKNH", "RV32I+GC+*"])
def test_zknh_is_retained_by_explicit_and_star_extension_specs(spec):
    assert "ZKNH" in normalize_extension_spec(spec)
    core = RV12Core(xlen=32, extensions=spec)
    assert core.enable_zknh
    Fragment.get(core, platform=None)


def test_zknh_rejects_nonstandard_selector_and_opcode_boundaries():
    dut = Zknh(xlen=32)
    sim = Simulator(dut)

    def process():
        yield dut.valid.eq(1)
        yield dut.opcode.eq(OP_IMM)
        yield dut.funct7.eq(0b0001000)
        yield dut.funct3.eq(0b001)
        yield dut.rs2.eq(4)
        yield Settle()
        assert (yield dut.matched) == 0
        assert (yield dut.wb_en) == 0

        yield dut.opcode.eq(OP)
        yield dut.funct7.eq(0b0101100)
        yield dut.funct3.eq(0b000)
        yield dut.rs2.eq(0)
        yield Settle()
        assert (yield dut.matched) == 0
        assert (yield dut.wb_en) == 0

    sim.add_process(process)
    sim.run()
