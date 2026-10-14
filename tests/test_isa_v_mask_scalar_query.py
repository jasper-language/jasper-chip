"""Executable V mask population-count and find-first closure."""

import pytest
from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.isa import OP_IMM, OP_V, enc_i
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


EXTENSIONS = ("RV32I+GC+V", "RV32I+GC+*")


def nop():
    return enc_i(OP_IMM, 0, 0, 0, 0)


def vsetivli(rd, avl):
    return ((0b11 << 30) | ((avl & 0x1F) << 15) | (0b111 << 12) |
            ((rd & 0x1F) << 7) | OP_V)


def vmv_s_x(vd, rs1):
    return ((0x10 << 26) | (1 << 25) | ((rs1 & 0x1F) << 15) |
            (0b110 << 12) | ((vd & 0x1F) << 7) | OP_V)


def mask_query(rd, vs2, selector, vm=1):
    return ((0x10 << 26) | ((vm & 1) << 25) | ((vs2 & 0x1F) << 20) |
            ((selector & 0x1F) << 15) | (0b010 << 12) |
            ((rd & 0x1F) << 7) | OP_V)


class _VMaskScalarQueryBench(Elaboratable):
    def __init__(self, extensions):
        program = [
            vsetivli(17, 8),
            enc_i(OP_IMM, 1, 0, 0, 0xB4), vmv_s_x(2, 1),
            *([nop()] * 3),
            mask_query(20, 2, 0b10000),
            mask_query(21, 2, 0b10001),
            enc_i(OP_IMM, 1, 0, 0, 0x50), vmv_s_x(0, 1),
            *([nop()] * 3),
            mask_query(22, 2, 0b10000, vm=0),
            mask_query(23, 2, 0b10001, vm=0),
            mask_query(24, 3, 0b10000),
            mask_query(25, 3, 0b10001),
            vsetivli(17, 0),
            mask_query(26, 2, 0b10000),
            mask_query(27, 2, 0b10001),
            0x0000006F,
        ]
        program += [nop()] * (96 - len(program))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=len(program), init=program)
        self.dmem = SimpleDMem(words=16, init=[0] * 16)

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


def run(extensions):
    dut = _VMaskScalarQueryBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    result = {}

    def process():
        for _ in range(700):
            yield Tick()
        for reg in range(20, 28):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            result[reg] = yield dut.core.dbg_reg_rdata

    sim.add_process(process)
    sim.run()
    return result


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_vcpop_vfirst_mask_empty_and_zero_vl(extensions):
    result = run(extensions)
    assert result == {
        20: 4, 21: 2,
        22: 1, 23: 4,
        24: 0, 25: 0xFFFFFFFF,
        26: 0, 27: 0xFFFFFFFF,
    }


def test_vcpop_vfirst_disabled_without_v():
    assert all(value == 0 for value in run("RV32I+GC").values())
