import pytest
from amaranth.hdl import Fragment
from amaranth.sim import Settle, Simulator

from rtl.isa_c_expand import CExpander
from rtl.rv12_core import RV12Core, normalize_extension_spec

NOP = 0x00000013


def encode_c_mop(number):
    return (0b011 << 13) | (number << 7) | 0b01


def test_all_eight_zcmop_encodings_expand_to_nop():
    dut = CExpander(xlen=32, enable_zcmop=True)
    sim = Simulator(dut)

    def process():
        yield dut.valid.eq(1)
        for number in range(1, 16, 2):
            yield dut.insn16.eq(encode_c_mop(number))
            yield Settle()
            assert (yield dut.is_compressed) == 1
            assert (yield dut.illegal) == 0
            assert (yield dut.insn32) == NOP

    sim.add_process(process)
    sim.run()


def test_zcmop_code_points_remain_illegal_when_extension_is_disabled():
    dut = CExpander(xlen=32, enable_zcmop=False)
    sim = Simulator(dut)

    def process():
        yield dut.valid.eq(1)
        for number in range(1, 16, 2):
            yield dut.insn16.eq(encode_c_mop(number))
            yield Settle()
            assert (yield dut.illegal) == 1

    sim.add_process(process)
    sim.run()


@pytest.mark.parametrize("spec", ["RV32I+GC+ZCMOP", "RV32I+GC+*"])
def test_zcmop_is_retained_and_core_elaborates(spec):
    assert "ZCMOP" in normalize_extension_spec(spec)
    core = RV12Core(xlen=32, extensions=spec)
    assert core.enable_zcmop
    Fragment.get(core, platform=None)


@pytest.mark.parametrize("insn", [
    encode_c_mop(2),
    encode_c_mop(14),
    encode_c_mop(1) | (1 << 12),
    encode_c_mop(1) | (1 << 2),
    encode_c_mop(1) ^ 0b11,
])
def test_zcmop_rejects_nonstandard_reserved_space_neighbors(insn):
    dut = CExpander(xlen=32, enable_zcmop=True)
    sim = Simulator(dut)

    def process():
        yield dut.valid.eq(1)
        yield dut.insn16.eq(insn)
        yield Settle()
        assert (yield dut.insn32) != NOP or (yield dut.illegal) == 1

    sim.add_process(process)
    sim.run()
