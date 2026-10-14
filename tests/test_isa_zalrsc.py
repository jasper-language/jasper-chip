"""RV32 Zalrsc load-reserved/store-conditional execution closure."""

import pytest

from amaranth import Elaboratable, Module
from amaranth.sim import Settle, Simulator, Tick

from rtl.isa import AMO, LOAD, OP_IMM, enc_i
from rtl.isa_zalrsc import Zalrsc
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


def nop():
    return enc_i(OP_IMM, 0, 0b000, 0, 0)


def enc_amo(funct5, rd, rs1, rs2, aq=0, rl=0):
    return (
        ((funct5 & 0x1F) << 27)
        | ((aq & 1) << 26)
        | ((rl & 1) << 25)
        | ((rs2 & 0x1F) << 20)
        | ((rs1 & 0x1F) << 15)
        | (0b010 << 12)
        | ((rd & 0x1F) << 7)
        | AMO
    )


class _ZalrscBench(Elaboratable):
    def __init__(self, extensions):
        program = [
            enc_i(OP_IMM, 1, 0b000, 0, 0),
            enc_i(OP_IMM, 2, 0b000, 0, 42),
            nop(),
            enc_amo(0b00010, 3, 1, 0, aq=1),  # LR.W x3,(x1)
            nop(),
            enc_amo(0b00011, 4, 1, 2, rl=1),  # SC.W x4,x2,(x1)
            nop(),
            enc_i(LOAD, 5, 0b010, 1, 0),       # LW x5,0(x1)
            nop(),
        ]
        program += [nop()] * (256 - len(program))

        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=256, init=program)
        self.dmem = SimpleDMem(words=16, init=[7] + [0] * 15)

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


@pytest.mark.parametrize("extensions", ["RV32I+GC+ZALRSC", "RV32I+GC+*"])
def test_zalrsc_reservation_and_conditional_store_execute(extensions):
    dut = _ZalrscBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    results = {}

    def process():
        for _ in range(220):
            yield Tick()
        for register in (3, 4, 5):
            yield dut.core.dbg_reg_addr.eq(register)
            yield Tick()
            results[register] = yield dut.core.dbg_reg_rdata

    sim.add_process(process)
    sim.run()

    assert results == {3: 7, 4: 0, 5: 42}


def test_zalrsc_decoder_excludes_amo_arithmetic():
    dut = Zalrsc(xlen=32)
    sim = Simulator(dut)

    def process():
        yield dut.valid.eq(1)
        yield dut.opcode.eq(AMO)
        yield dut.funct7.eq(0b0000000)  # AMOADD.W, aq=0, rl=0
        yield dut.funct3.eq(0b010)
        yield dut.rs2.eq(2)
        yield Settle()
        assert (yield dut.matched) == 0
        assert (yield dut.is_load) == 0
        assert (yield dut.is_store) == 0

    sim.add_process(process)
    sim.run()
