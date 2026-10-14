"""Executable V widening integer sum reduction closure."""

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


def widening_reduction(vd, vs2, vs1, signed, vm=1):
    funct6 = 0x31 if signed else 0x30
    return ((funct6 << 26) | ((vm & 1) << 25) |
            ((vs2 & 0x1F) << 20) | ((vs1 & 0x1F) << 15) |
            ((vd & 0x1F) << 7) | OP_V)


class _VWideningReductionBench(Elaboratable):
    def __init__(self, extensions):
        program = [
            vsetivli(17, 1, vtype=0x10),
            lui(1, 0x03030), enc_i(OP_IMM, 1, 0, 1, -255),
            vmv_s_x(2, 1),
            vsetivli(17, 1, vtype=0x08),
            enc_i(OP_IMM, 1, 0, 0, 0x100), vmv_s_x(3, 1),
            vsetivli(17, 4),
            *([nop()] * 3),
            widening_reduction(4, 2, 3, signed=False),
            widening_reduction(5, 2, 3, signed=True),
            enc_i(OP_IMM, 1, 0, 0, 0x0D), vmv_s_x(0, 1),
            widening_reduction(6, 2, 3, signed=False, vm=0),
            widening_reduction(7, 2, 3, signed=True, vm=0),
            vsetivli(17, 0),
            widening_reduction(8, 2, 3, signed=False),
            widening_reduction(9, 2, 3, signed=True),
            vsetivli(17, 1, vtype=0x08),
            *([nop()] * 3),
            vmv_x_s(20, 4), vmv_x_s(21, 5),
            vmv_x_s(22, 6), vmv_x_s(23, 7),
            vmv_x_s(24, 8), vmv_x_s(25, 9),
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
    dut = _VWideningReductionBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    result = {}

    def process():
        for _ in range(900):
            yield Tick()
        for reg in range(20, 26):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            result[reg] = yield dut.core.dbg_reg_rdata

    sim.add_process(process)
    sim.run()
    return result


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_widening_reduction_signed_unsigned_mask_and_zero_vl(extensions):
    assert run(extensions) == {
        20: 0x0205, 21: 0x0105,
        22: 0x0106, 23: 0x0106,
        24: 0, 25: 0,
    }


def test_widening_reduction_disabled_without_v():
    assert all(value == 0 for value in run("RV32I+GC").values())
