"""RV32 Zmmul four-instruction execution closure."""

import pytest

from amaranth import Elaboratable, Module
from amaranth.sim import Settle, Simulator, Tick

from rtl.isa import OP, OP_IMM, enc_i, enc_r
from rtl.isa_zmmul import Zmmul
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


def nop():
    return enc_i(OP_IMM, 0, 0b000, 0, 0)


class _ZmmulBench(Elaboratable):
    def __init__(self, extensions):
        program = [
            enc_i(OP_IMM, 1, 0b000, 0, -2),
            enc_i(OP_IMM, 2, 0b000, 0, 3),
            nop(),
            enc_r(OP, 3, 0b000, 1, 2, 0b0000001),  # MUL
            enc_r(OP, 4, 0b001, 1, 2, 0b0000001),  # MULH
            enc_r(OP, 5, 0b010, 1, 2, 0b0000001),  # MULHSU
            enc_r(OP, 6, 0b011, 1, 2, 0b0000001),  # MULHU
            nop(),
        ]
        program += [nop()] * (256 - len(program))

        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=256, init=program)
        self.dmem = SimpleDMem(words=16)

    def elaborate(self, platform):
        m = Module()
        m.submodules.core = core = self.core
        m.submodules.imem = imem = self.imem
        m.submodules.dmem = dmem = self.dmem
        m.d.comb += [
            imem.addr.eq(core.imem_addr),
            core.imem_rdata.eq(imem.rdata),
            dmem.req_valid.eq(core.dmem_valid),
            dmem.req_we.eq(core.dmem_we),
            dmem.req_addr.eq(core.dmem_addr),
            dmem.req_wdata.eq(core.dmem_wdata),
            core.dmem_rdata.eq(dmem.rsp_rdata),
            core.gc_enq_ready.eq(1),
            core.gc_rsp_valid.eq(0),
            core.gc_rsp_tag.eq(0),
            core.gc_rsp_rd.eq(0),
            core.gc_rsp_data.eq(0),
            core.wb_enq_ready.eq(1),
            core.mv_cmd_ready.eq(1),
            core.mv_rsp_valid.eq(0),
            core.mv_rsp_tag.eq(0),
            core.mv_rsp_rd.eq(0),
            core.mv_rsp_data.eq(0),
        ]
        return m


@pytest.mark.parametrize("extensions", ["RV32I+GC+ZMMUL", "RV32I+GC+*"])
def test_zmmul_standard_multiply_family_executes(extensions):
    dut = _ZmmulBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    results = {}

    def process():
        for _ in range(180):
            yield Tick()
        for register in range(3, 7):
            yield dut.core.dbg_reg_addr.eq(register)
            yield Tick()
            results[register] = yield dut.core.dbg_reg_rdata

    sim.add_process(process)
    sim.run()

    assert results == {
        3: 0xFFFFFFFA,
        4: 0xFFFFFFFF,
        5: 0xFFFFFFFF,
        6: 0x00000002,
    }


def test_zmmul_module_excludes_division_family():
    dut = Zmmul(xlen=32)
    sim = Simulator(dut)

    def process():
        yield dut.valid.eq(1)
        yield dut.opcode.eq(OP)
        yield dut.funct7.eq(0b0000001)
        yield dut.funct3.eq(0b100)  # DIV
        yield dut.ex1_a.eq(12)
        yield dut.ex1_b.eq(3)
        yield Settle()
        assert (yield dut.matched) == 0
        assert (yield dut.wb_en) == 0

    sim.add_process(process)
    sim.run()
