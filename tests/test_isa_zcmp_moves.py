"""Executable Zcmp atomic double-register move closure."""

import pytest
from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.isa import OP, OP_IMM, enc_i, enc_r
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


EXTENSIONS = ("RV32I+GC+ZCMP", "RV32I+GC+*+ZCMP")
C_NOP = 0x0001


def cmmv(r1s, r2s, to_a):
    funct2 = 0b11 if to_a else 0b01
    return ((0b101011 << 10) | ((r1s & 7) << 7) |
            (funct2 << 5) | ((r2s & 7) << 2) | 0b10)


class _ZcmpMoveBench(Elaboratable):
    def __init__(self, extensions, insn16, setup, sum_regs):
        program = [enc_i(OP_IMM, rd, 0, 0, value) for rd, value in setup]
        program += [insn16 | (C_NOP << 16)]
        program += [enc_r(OP, 12, 0, sum_regs[0], sum_regs[1], 0)]
        program += [0x0000006F]
        program += [enc_i(OP_IMM, 0, 0, 0, 0)] * (32 - len(program))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=len(program), init=program)
        self.dmem = SimpleDMem(words=4, init=[0] * 4)

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


def run_case(extensions, insn16, setup, sum_regs, observed):
    dut = _ZcmpMoveBench(extensions, insn16, setup, sum_regs)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    result = {}

    def process():
        for _ in range(150):
            yield Tick()
        for reg in observed:
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            result[reg] = yield dut.core.dbg_reg_rdata

    sim.add_process(process)
    sim.run()
    return result


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_zcmp_cm_mvsa01_atomically_moves_a0_a1_to_s_registers(extensions):
    regs = run_case(extensions, cmmv(0, 2, False), ((10, 11), (11, 22)),
                    (8, 18), (8, 18, 12))
    assert regs == {8: 11, 18: 22, 12: 33}


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_zcmp_cm_mva01s_atomically_moves_s_registers_to_a0_a1(extensions):
    regs = run_case(extensions, cmmv(1, 3, True), ((9, 44), (19, 55)),
                    (10, 11), (10, 11, 12))
    assert regs == {10: 44, 11: 55, 12: 99}


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_zcmp_cm_mvsa01_rejects_duplicate_destinations(extensions):
    regs = run_case(extensions, cmmv(0, 0, False), ((8, 77), (10, 1), (11, 2)),
                    (8, 8), (8, 12))
    assert regs == {8: 77, 12: 154}
