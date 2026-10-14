"""Executable V set-before/including/only-first mask closure."""

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


def vmv_x_s(rd, vs2):
    return ((0x10 << 26) | (1 << 25) | ((vs2 & 0x1F) << 20) |
            (0b010 << 12) | ((rd & 0x1F) << 7) | OP_V)


def mask_prefix(vd, vs2, selector, vm=1):
    return ((0x14 << 26) | ((vm & 1) << 25) |
            ((vs2 & 0x1F) << 20) | ((selector & 0x1F) << 15) |
            (0b010 << 12) | ((vd & 0x1F) << 7) | OP_V)


class _VMaskPrefixBench(Elaboratable):
    def __init__(self, extensions):
        program = [
            vsetivli(17, 8),
            enc_i(OP_IMM, 1, 0, 0, 0xB4), vmv_s_x(2, 1),
            enc_i(OP_IMM, 1, 0, 0, 0), vmv_s_x(3, 1),
            *([nop()] * 3),
            mask_prefix(4, 2, 0b00001),
            mask_prefix(5, 2, 0b00011),
            mask_prefix(6, 2, 0b00010),
            mask_prefix(7, 3, 0b00001),
            mask_prefix(8, 3, 0b00011),
            mask_prefix(9, 3, 0b00010),
            *([nop()] * 3),
            vmv_x_s(20, 4), vmv_x_s(21, 5), vmv_x_s(22, 6),
            vmv_x_s(23, 7), vmv_x_s(24, 8), vmv_x_s(25, 9),
            enc_i(OP_IMM, 1, 0, 0, 0xF8), vmv_s_x(0, 1),
            enc_i(OP_IMM, 1, 0, 0, 0x55),
            vmv_s_x(10, 1), vmv_s_x(11, 1), vmv_s_x(12, 1),
            *([nop()] * 3),
            mask_prefix(10, 2, 0b00001, vm=0),
            mask_prefix(11, 2, 0b00011, vm=0),
            mask_prefix(12, 2, 0b00010, vm=0),
            *([nop()] * 3),
            vmv_x_s(26, 10), vmv_x_s(27, 11), vmv_x_s(28, 12),
            0x0000006F,
        ]
        program += [nop()] * (112 - len(program))
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
    dut = _VMaskPrefixBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    result = {}

    def process():
        for _ in range(950):
            yield Tick()
        for reg in range(20, 29):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            result[reg] = yield dut.core.dbg_reg_rdata

    sim.add_process(process)
    sim.run()
    return result


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_mask_prefix_first_empty_and_masked_inactive(extensions):
    assert run(extensions) == {
        20: 0x03, 21: 0x07, 22: 0x04,
        23: 0xFFFFFFFF, 24: 0xFFFFFFFF, 25: 0,
        26: 0x0D, 27: 0x1D, 28: 0x15,
    }


def test_mask_prefix_disabled_without_v():
    assert all(value == 0 for value in run("RV32I+GC").values())
