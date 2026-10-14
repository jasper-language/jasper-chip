"""RV32 Ztso FENCE.TSO execution closure."""

import pytest

from amaranth import Elaboratable, Module
from amaranth.sim import Settle, Simulator, Tick

from rtl.isa import MISC_MEM, OP_IMM, enc_i
from rtl.isa_ztso import Ztso
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


FENCE_TSO = 0x8330000F


def nop():
    return enc_i(OP_IMM, 0, 0b000, 0, 0)


class _ZtsoBench(Elaboratable):
    def __init__(self, extensions):
        program = [
            enc_i(OP_IMM, 1, 0b000, 0, 11),
            FENCE_TSO,
            enc_i(OP_IMM, 2, 0b000, 1, 7),
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


@pytest.mark.parametrize("extensions", ["RV32I+GC+ZTSO", "RV32I+GC+*"])
def test_fence_tso_retires_in_program_order(extensions):
    dut = _ZtsoBench(extensions)
    if "ZTSO" in extensions:
        assert "ZTSO" in dut.core.extensions

    sim = Simulator(dut)
    sim.add_clock(1e-6)
    results = {}

    def process():
        for _ in range(120):
            yield Tick()
        for register in (1, 2):
            yield dut.core.dbg_reg_addr.eq(register)
            yield Tick()
            results[register] = yield dut.core.dbg_reg_rdata

    sim.add_process(process)
    sim.run()

    assert results == {1: 11, 2: 18}


def test_ztso_decoder_matches_only_fence_tso_encoding():
    dut = Ztso(xlen=32)
    sim = Simulator(dut)

    def process():
        yield dut.valid.eq(1)
        yield dut.opcode.eq(MISC_MEM)
        yield dut.funct3.eq(0)
        yield dut.rd.eq(0)
        yield dut.rs1.eq(0)
        yield dut.imm.eq(0x833)
        yield Settle()
        assert (yield dut.matched) == 1
        assert (yield dut.is_fence) == 1

        yield dut.imm.eq(0x0FF)
        yield Settle()
        assert (yield dut.matched) == 0
        assert (yield dut.is_fence) == 0

    sim.add_process(process)
    sim.run()
