"""Executable RV32 Zcmp cm.push multi-store closure."""

import pytest
from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.isa import OP_IMM, enc_i
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


EXTENSIONS = ("RV32I+GC+ZCMP", "RV32I+GC+*+ZCMP")
C_NOP = 0x0001


def cm_push(rlist, spimm):
    return ((0b101 << 13) | (0b11000 << 8) | ((rlist & 0xF) << 4) |
            ((spimm & 3) << 2) | 0b10)


class _ZcmpPushBench(Elaboratable):
    def __init__(self, extensions, rlist, spimm, values):
        program = [enc_i(OP_IMM, 2, 0, 0, 0x200)]
        program += [enc_i(OP_IMM, reg, 0, 0, value) for reg, value in values.items()]
        program += [cm_push(rlist, spimm) | (C_NOP << 16), 0x0000006F]
        program += [enc_i(OP_IMM, 0, 0, 0, 0)] * (48 - len(program))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=len(program), init=program)
        self.dmem = SimpleDMem(words=256, init=[0] * 256)

    def elaborate(self, platform):
        m = Module()
        m.submodules.core = c = self.core
        m.submodules.imem = im = self.imem
        m.submodules.dmem = dm = self.dmem
        m.d.comb += [
            im.addr.eq(c.imem_addr), c.imem_rdata.eq(im.rdata),
            dm.req_valid.eq(c.dmem_valid), dm.req_we.eq(c.dmem_we),
            dm.req_addr.eq(c.dmem_addr), dm.req_wdata.eq(c.dmem_wdata),
            c.dmem_rdata.eq(dm.rsp_rdata), c.gc_enq_ready.eq(1),
            c.gc_rsp_valid.eq(0), c.gc_rsp_tag.eq(0), c.gc_rsp_rd.eq(0),
            c.gc_rsp_data.eq(0), c.wb_enq_ready.eq(1), c.mv_cmd_ready.eq(1),
            c.mv_rsp_valid.eq(0), c.mv_rsp_tag.eq(0), c.mv_rsp_rd.eq(0),
            c.mv_rsp_data.eq(0),
        ]
        return m


def run_push(extensions, rlist, spimm, values):
    dut = _ZcmpPushBench(extensions, rlist, spimm, values)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    writes = []
    result = {}

    def process():
        for _ in range(240):
            if (yield dut.core.dmem_valid) and (yield dut.core.dmem_we):
                writes.append(((yield dut.core.dmem_addr), (yield dut.core.dmem_wdata)))
            yield Tick()
        yield dut.core.dbg_reg_addr.eq(2)
        yield Tick()
        result[2] = yield dut.core.dbg_reg_rdata

    sim.add_process(process)
    sim.run()
    return result[2], writes


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_zcmp_cm_push_rlist7_stores_in_standard_order_then_commits_sp(extensions):
    sp, writes = run_push(extensions, 7, 3, {1: 101, 8: 108, 9: 109, 18: 118})
    assert writes == [(0x1FC, 118), (0x1F8, 109), (0x1F4, 108), (0x1F0, 101)]
    assert sp == 0x1C0


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_zcmp_cm_push_rlist15_covers_s10_s11_and_max_adjustment(extensions):
    regs = (1, 8, 9, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27)
    sp, writes = run_push(extensions, 15, 3, {reg: reg for reg in regs})
    assert writes == [
        (0x1FC - index * 4, reg)
        for index, reg in enumerate((27, 26, 25, 24, 23, 22, 21, 20, 19, 18, 9, 8, 1))
    ]
    assert sp == 0x190


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_zcmp_cm_push_rejects_reserved_rlist(extensions):
    sp, writes = run_push(extensions, 3, 0, {1: 101})
    assert writes == []
    assert sp == 0x200
