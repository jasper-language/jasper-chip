"""RV32 Zihintntl four-hint execution closure."""

import pytest

from amaranth import Elaboratable, Module
from amaranth.sim import Settle, Simulator, Tick

from rtl.isa import OP, OP_IMM, enc_i, enc_r
from rtl.isa_zihintntl import Zihintntl
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


def nop():
    return enc_i(OP_IMM, 0, 0b000, 0, 0)


def ntl_hint(rs2):
    return enc_r(OP, 0, 0b000, 0, rs2, 0)


class _ZihintntlBench(Elaboratable):
    def __init__(self, extensions):
        program = [
            enc_i(OP_IMM, 1, 0b000, 0, 1),
            ntl_hint(2),  # NTL.P1
            ntl_hint(3),  # NTL.PALL
            ntl_hint(4),  # NTL.S1
            ntl_hint(5),  # NTL.ALL
            enc_i(OP_IMM, 6, 0b000, 1, 5),
            nop(),
        ]
        program += [nop()] * (128 - len(program))

        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=128, init=program)
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


@pytest.mark.parametrize("extensions", ["RV32I+GC+ZIHINTNTL", "RV32I+GC+*"])
def test_all_zihintntl_hints_retire_without_side_effects(extensions):
    dut = _ZihintntlBench(extensions)
    if "ZIHINTNTL" in extensions:
        assert "ZIHINTNTL" in dut.core.extensions

    sim = Simulator(dut)
    sim.add_clock(1e-6)
    results = {}

    def process():
        for _ in range(140):
            yield Tick()
        for register in (0, 1, 6):
            yield dut.core.dbg_reg_addr.eq(register)
            yield Tick()
            results[register] = yield dut.core.dbg_reg_rdata

    sim.add_process(process)
    sim.run()

    assert results == {0: 0, 1: 1, 6: 6}


def test_zihintntl_decoder_accepts_exactly_four_rs2_encodings():
    dut = Zihintntl(xlen=32)
    sim = Simulator(dut)

    def process():
        yield dut.valid.eq(1)
        yield dut.opcode.eq(OP)
        yield dut.funct7.eq(0)
        yield dut.funct3.eq(0)
        yield dut.rd.eq(0)
        yield dut.rs1.eq(0)

        for rs2 in (2, 3, 4, 5):
            yield dut.rs2.eq(rs2)
            yield Settle()
            assert (yield dut.matched) == 1
            assert (yield dut.wb_en) == 0

        for rs2 in (1, 6):
            yield dut.rs2.eq(rs2)
            yield Settle()
            assert (yield dut.matched) == 0

    sim.add_process(process)
    sim.run()
