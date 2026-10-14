"""Executable V stable element compression closure."""

import pytest
from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.isa import OP_IMM, OP_V, enc_i
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


EXTENSIONS = ("RV32I+GC+V", "RV32I+GC+*")


def nop():
    return enc_i(OP_IMM, 0, 0, 0, 0)


def lui(rd, imm20):
    return ((imm20 & 0xFFFFF) << 12) | ((rd & 0x1F) << 7) | 0x37


def vsetivli(rd, avl, vtype=0):
    return ((0b11 << 30) | ((vtype & 0x3FF) << 20) |
            ((avl & 0x1F) << 15) | (0b111 << 12) |
            ((rd & 0x1F) << 7) | OP_V)


def vmv_s_x(vd, rs1):
    return ((0x10 << 26) | (1 << 25) | ((rs1 & 0x1F) << 15) |
            (0b110 << 12) | ((vd & 0x1F) << 7) | OP_V)


def vmv_x_s(rd, vs2):
    return ((0x10 << 26) | (1 << 25) | ((vs2 & 0x1F) << 20) |
            (0b010 << 12) | ((rd & 0x1F) << 7) | OP_V)


def vcompress(vd, vs2, mask):
    return ((0x17 << 26) | (1 << 25) | ((vs2 & 0x1F) << 20) |
            ((mask & 0x1F) << 15) | (0b010 << 12) |
            ((vd & 0x1F) << 7) | OP_V)


class _VCompressBench(Elaboratable):
    def __init__(self, extensions):
        program = [
            vsetivli(17, 1, vtype=0x10),
            lui(1, 0x2C211), enc_i(OP_IMM, 1, 0, 1, 0x60B),
            vmv_s_x(2, 1),
            lui(1, 0x09091), enc_i(OP_IMM, 1, 0, 1, -0x6F7),
            vmv_s_x(4, 1), vmv_s_x(5, 1), vmv_s_x(6, 1),
            vsetivli(17, 4),
            enc_i(OP_IMM, 1, 0, 0, 0x0A), vmv_s_x(1, 1),
            *([nop()] * 3),
            vcompress(4, 2, 1),
            vsetivli(17, 4, vtype=0x40),
            vcompress(5, 2, 1),
            vsetivli(17, 4),
            enc_i(OP_IMM, 1, 0, 0, 0x0F), vmv_s_x(1, 1),
            *([nop()] * 3),
            vcompress(6, 2, 1),
            vsetivli(17, 1, vtype=0x10),
            *([nop()] * 3),
            vmv_x_s(20, 4), vmv_x_s(21, 5), vmv_x_s(22, 6),
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
    dut = _VCompressBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    result = {}

    def process():
        for _ in range(850):
            yield Tick()
        for reg in range(20, 23):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            result[reg] = yield dut.core.dbg_reg_rdata

    sim.add_process(process)
    sim.run()
    return result


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_vcompress_stable_order_tail_policy_and_full_selection(extensions):
    assert run(extensions) == {
        20: 0x09092C16,
        21: 0xFFFF2C16,
        22: 0x2C21160B,
    }


def test_vcompress_disabled_without_v():
    assert all(value == 0 for value in run("RV32I+GC").values())
