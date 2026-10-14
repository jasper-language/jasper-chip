"""RV32 Zicond standard-encoding execution closure."""

import pytest

from amaranth import Elaboratable, Module
from amaranth.sim import Settle, Simulator, Tick

from rtl.isa import OP, OP_IMM, enc_i, enc_r
from rtl.isa_zicond import Zicond
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


def nop():
    return enc_i(OP_IMM, 0, 0b000, 0, 0)


class _ZicondBench(Elaboratable):
    def __init__(self, extensions):
        program = [
            enc_i(OP_IMM, 1, 0b000, 0, 0x55),
            enc_i(OP_IMM, 2, 0b000, 0, 0),
            enc_i(OP_IMM, 3, 0b000, 0, 7),
            nop(),
            enc_r(OP, 4, 0b101, 1, 2, 0b0000111),  # CZERO.EQZ, zero
            enc_r(OP, 5, 0b101, 1, 3, 0b0000111),  # CZERO.EQZ, keep
            enc_r(OP, 6, 0b111, 1, 2, 0b0000111),  # CZERO.NEZ, keep
            enc_r(OP, 7, 0b111, 1, 3, 0b0000111),  # CZERO.NEZ, zero
            nop(),
        ]
        program += [nop()] * (192 - len(program))

        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=192, init=program)
        self.dmem = SimpleDMem(words=16)

    def elaborate(self, platform):
        m = Module()
        m.submodules.core = core = self.core
        m.submodules.imem = imem = self.imem
        m.submodules.dmem = dmem = self.dmem
        m.d.comb += [
            imem.addr.eq(core.imem_addr), core.imem_rdata.eq(imem.rdata),
            dmem.req_valid.eq(core.dmem_valid), dmem.req_we.eq(core.dmem_we),
            dmem.req_addr.eq(core.dmem_addr), dmem.req_wdata.eq(core.dmem_wdata),
            core.dmem_rdata.eq(dmem.rsp_rdata), core.gc_enq_ready.eq(1),
            core.gc_rsp_valid.eq(0), core.gc_rsp_tag.eq(0), core.gc_rsp_rd.eq(0),
            core.gc_rsp_data.eq(0), core.wb_enq_ready.eq(1), core.mv_cmd_ready.eq(1),
            core.mv_rsp_valid.eq(0), core.mv_rsp_tag.eq(0), core.mv_rsp_rd.eq(0),
            core.mv_rsp_data.eq(0),
        ]
        return m


@pytest.mark.parametrize("extensions", ["RV32I+GC+ZICOND", "RV32I+GC+*"])
def test_zicond_complete_truth_matrix_uses_standard_encodings(extensions):
    dut = _ZicondBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    results = {}

    def process():
        for _ in range(180):
            yield Tick()
        for register in range(4, 8):
            yield dut.core.dbg_reg_addr.eq(register)
            yield Tick()
            results[register] = yield dut.core.dbg_reg_rdata

    sim.add_process(process)
    sim.run()
    assert results == {4: 0, 5: 0x55, 6: 0x55, 7: 0}


def test_zicond_module_rejects_legacy_nonstandard_funct3_values():
    dut = Zicond(xlen=32)
    sim = Simulator(dut)

    def process():
        yield dut.valid.eq(1)
        yield dut.opcode.eq(OP)
        yield dut.funct7.eq(0b0000111)
        yield dut.ex1_a.eq(0x55)
        yield dut.ex1_b.eq(0)
        for funct3 in (0b000, 0b001):
            yield dut.funct3.eq(funct3)
            yield Settle()
            assert (yield dut.matched) == 0
            assert (yield dut.wb_en) == 0

    sim.add_process(process)
    sim.run()
