import pytest
from amaranth.hdl import Fragment
from amaranth.sim import Settle, Simulator

from rtl.isa import OP_IMM
from rtl.isa_zksh import Zksh
from rtl.rv12_core import RV12Core, normalize_extension_spec

MASK32 = 0xFFFFFFFF


def rol32(value, amount):
    return ((value << amount) | (value >> (32 - amount))) & MASK32


@pytest.mark.parametrize("value", [0x00000000, 0x12345678, 0xFFFFFFFF, 0x80000001])
def test_sm3p0_and_sm3p1_execute_standard_semantics(value):
    dut = Zksh(xlen=32)
    sim = Simulator(dut)
    expected = {
        8: value ^ rol32(value, 9) ^ rol32(value, 17),
        9: value ^ rol32(value, 15) ^ rol32(value, 23),
    }

    def process():
        yield dut.valid.eq(1)
        yield dut.opcode.eq(OP_IMM)
        yield dut.funct7.eq(0b0001000)
        yield dut.funct3.eq(0b001)
        yield dut.ex1_a.eq(value)
        for selector in (8, 9):
            yield dut.rs2.eq(selector)
            yield Settle()
            assert (yield dut.matched) == 1
            assert (yield dut.wb_en) == 1
            assert (yield dut.wb_data) == (expected[selector] & MASK32)
            assert (yield dut.alu_out) == (expected[selector] & MASK32)

    sim.add_process(process)
    sim.run()


@pytest.mark.parametrize("spec", ["RV32I+GC+ZKSH", "RV32I+GC+*"])
def test_zksh_is_retained_and_core_elaborates(spec):
    assert "ZKSH" in normalize_extension_spec(spec)
    core = RV12Core(xlen=32, extensions=spec)
    assert core.enable_zksh
    Fragment.get(core, platform=None)


def test_zksh_rejects_neighboring_and_wrong_format_encodings():
    dut = Zksh(xlen=32)
    sim = Simulator(dut)

    def process():
        yield dut.valid.eq(1)
        yield dut.opcode.eq(OP_IMM)
        yield dut.funct7.eq(0b0001000)
        yield dut.funct3.eq(0b001)
        for selector in (7, 10):
            yield dut.rs2.eq(selector)
            yield Settle()
            assert (yield dut.matched) == 0
        yield dut.rs2.eq(8)
        yield dut.funct3.eq(0b000)
        yield Settle()
        assert (yield dut.matched) == 0

    sim.add_process(process)
    sim.run()
