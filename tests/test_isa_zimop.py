import pytest
from amaranth.hdl import Fragment
from amaranth.sim import Settle, Simulator

from rtl.isa import SYSTEM
from rtl.isa_zimop import Zimop
from rtl.rv12_core import RV12Core, normalize_extension_spec


def mop_r_fields(index):
    funct7 = (1 << 6) | (((index >> 4) & 1) << 5) | \
        (((index >> 3) & 1) << 2) | (((index >> 2) & 1) << 1)
    rs2 = 0b11100 | (index & 0b11)
    return funct7, rs2


def mop_rr_funct7(index):
    return (1 << 6) | (((index >> 2) & 1) << 5) | \
        (((index >> 1) & 1) << 2) | ((index & 1) << 1) | 1


def test_all_32_mop_r_and_8_mop_rr_encodings_write_zero():
    dut = Zimop(xlen=32)
    sim = Simulator(dut)

    def process():
        yield dut.valid.eq(1)
        yield dut.opcode.eq(SYSTEM)
        yield dut.funct3.eq(0b100)
        yield dut.ex1_a.eq(0x12345678)
        yield dut.ex1_b.eq(0x89ABCDEF)
        for index in range(32):
            funct7, rs2 = mop_r_fields(index)
            yield dut.funct7.eq(funct7)
            yield dut.rs2.eq(rs2)
            yield Settle()
            assert (yield dut.matched) == 1
            assert (yield dut.wb_en) == 1
            assert (yield dut.wb_data) == 0
        for index in range(8):
            yield dut.funct7.eq(mop_rr_funct7(index))
            yield dut.rs2.eq((index * 5 + 3) & 31)
            yield Settle()
            assert (yield dut.matched) == 1
            assert (yield dut.wb_en) == 1
            assert (yield dut.wb_data) == 0

    sim.add_process(process)
    sim.run()


@pytest.mark.parametrize("spec", ["RV32I+GC+ZIMOP", "RV32I+GC+*"])
def test_zimop_is_retained_and_core_elaborates(spec):
    assert "ZIMOP" in normalize_extension_spec(spec)
    core = RV12Core(xlen=32, extensions=spec)
    assert core.enable_zimop
    Fragment.get(core, platform=None)


@pytest.mark.parametrize("funct7,rs2,funct3", [
    (0b0000000, 0b11100, 0b100),
    (0b1010000, 0b11100, 0b100),
    (0b1001000, 0b11100, 0b100),
    (0b1000000, 0b11011, 0b100),
    (0b1000000, 0b11100, 0b011),
])
def test_zimop_rejects_nonstandard_fixed_field_boundaries(funct7, rs2, funct3):
    dut = Zimop(xlen=32)
    sim = Simulator(dut)

    def process():
        yield dut.valid.eq(1)
        yield dut.opcode.eq(SYSTEM)
        yield dut.funct7.eq(funct7)
        yield dut.rs2.eq(rs2)
        yield dut.funct3.eq(funct3)
        yield Settle()
        assert (yield dut.matched) == 0
        assert (yield dut.wb_en) == 0

    sim.add_process(process)
    sim.run()
