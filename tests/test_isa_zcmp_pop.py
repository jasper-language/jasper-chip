"""Executable RV32 Zcmp cm.pop, cm.popret, and cm.popretz closure."""

import pytest
from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.isa import OP_IMM, enc_i
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


EXTENSIONS = ("RV32I+GC+ZCMP", "RV32I+GC+*+ZCMP")
C_NOP = 0x0001
REGS = (1, 8, 9, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27)


def cm_stack(kind, rlist, spimm):
    return ((0b101 << 13) | ((0b11000 + (kind << 1)) << 8) |
            ((rlist & 0xF) << 4) | ((spimm & 3) << 2) | 0b10)


class _ZcmpPopBench(Elaboratable):
    def __init__(self, extensions, kind, rlist, spimm, sp, memory):
        program = [
            enc_i(OP_IMM, 2, 0, 0, sp),
            enc_i(OP_IMM, 10, 0, 0, 55),
            cm_stack(kind, rlist, spimm) | (C_NOP << 16),
            enc_i(OP_IMM, 30, 0, 0, 66),
            0x0000006F,
            enc_i(OP_IMM, 0, 0, 0, 0),
            enc_i(OP_IMM, 0, 0, 0, 0),
            enc_i(OP_IMM, 0, 0, 0, 0),
            enc_i(OP_IMM, 31, 0, 0, 77),
            0x0000006F,
        ]
        program += [enc_i(OP_IMM, 0, 0, 0, 0)] * (48 - len(program))
        dmem = [0] * 256
        for address, value in memory.items():
            dmem[address >> 2] = value
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=len(program), init=program)
        self.dmem = SimpleDMem(words=len(dmem), init=dmem)

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


def run_pop(extensions, kind, rlist, spimm, sp, memory):
    dut = _ZcmpPopBench(extensions, kind, rlist, spimm, sp, memory)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    result = {}

    def process():
        for _ in range(280):
            yield Tick()
        for reg in (1, 2, 8, 9, 10, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 30, 31):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            result[reg] = yield dut.core.dbg_reg_rdata

    sim.add_process(process)
    sim.run()
    return result


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_zcmp_cm_pop_restores_registers_then_commits_sp(extensions):
    memory = {0x1F0: 0x20, 0x1F4: 108, 0x1F8: 109, 0x1FC: 118}
    result = run_pop(extensions, 1, 7, 3, 0x1C0, memory)
    assert [result[reg] for reg in (1, 8, 9, 18)] == [0x20, 108, 109, 118]
    assert result[2] == 0x200
    assert result[10] == 55
    assert result[30] == 66


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_zcmp_cm_popret_restores_max_list_and_returns_to_loaded_ra(extensions):
    memory = {0x1CC + index * 4: value for index, value in enumerate((0x20,) + tuple(range(108, 120)))}
    result = run_pop(extensions, 3, 15, 3, 0x190, memory)
    assert [result[reg] for reg in REGS] == [0x20] + list(range(108, 120))
    assert result[2] == 0x200
    assert result[30] == 0
    assert result[31] == 77


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_zcmp_cm_popretz_zeroes_a0_and_returns(extensions):
    memory = {0x1F0: 0x20, 0x1F4: 108, 0x1F8: 109, 0x1FC: 118}
    result = run_pop(extensions, 2, 7, 3, 0x1C0, memory)
    assert [result[reg] for reg in (1, 8, 9, 18)] == [0x20, 108, 109, 118]
    assert result[2] == 0x200
    assert result[10] == 0
    assert result[30] == 0
    assert result[31] == 77


@pytest.mark.parametrize("extensions", EXTENSIONS)
@pytest.mark.parametrize("kind", (1, 2, 3))
def test_zcmp_pop_family_rejects_reserved_rlist(extensions, kind):
    result = run_pop(extensions, kind, 3, 0, 0x200, {})
    assert result[2] == 0x200
    assert result[10] == 55
    assert all(result[reg] == 0 for reg in (1, 8, 9, 18, 31))
    assert result[30] == 66
