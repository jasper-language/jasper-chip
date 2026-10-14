import pytest
from amaranth.hdl import Fragment
from amaranth.sim import Settle, Simulator

from rtl.isa import SYSTEM
from rtl.isa_zawrs import Zawrs
from rtl.rv12_core import RV12Core, normalize_extension_spec


@pytest.mark.parametrize("immediate", [0x00D, 0x01D])
def test_wrs_nto_and_wrs_sto_match_and_resume_without_side_effects(immediate):
    dut = Zawrs(xlen=32)
    sim = Simulator(dut)

    def process():
        yield dut.valid.eq(1)
        yield dut.opcode.eq(SYSTEM)
        yield dut.funct3.eq(0)
        yield dut.rd.eq(0)
        yield dut.rs1.eq(0)
        yield dut.imm.eq(immediate)
        yield Settle()
        assert (yield dut.matched) == 1
        assert (yield dut.wb_en) == 0
        assert (yield dut.trap) == 0
        assert (yield dut.redirect) == 0
        assert (yield dut.is_load) == 0
        assert (yield dut.is_store) == 0

    sim.add_process(process)
    sim.run()


@pytest.mark.parametrize("spec", ["RV32I+GC+ZAWRS", "RV32I+GC+*"])
def test_zawrs_is_retained_and_core_elaborates(spec):
    assert "ZAWRS" in normalize_extension_spec(spec)
    core = RV12Core(xlen=32, extensions=spec)
    assert core.enable_zawrs
    Fragment.get(core, platform=None)


@pytest.mark.parametrize("field,value", [
    ("imm", 0x00C), ("imm", 0x00E), ("funct3", 1), ("rd", 1), ("rs1", 1),
])
def test_zawrs_rejects_neighboring_or_nonzero_reserved_fields(field, value):
    dut = Zawrs(xlen=32)
    sim = Simulator(dut)

    def process():
        yield dut.valid.eq(1)
        yield dut.opcode.eq(SYSTEM)
        yield dut.funct3.eq(0)
        yield dut.rd.eq(0)
        yield dut.rs1.eq(0)
        yield dut.imm.eq(0x00D)
        yield getattr(dut, field).eq(value)
        yield Settle()
        assert (yield dut.matched) == 0

    sim.add_process(process)
    sim.run()
