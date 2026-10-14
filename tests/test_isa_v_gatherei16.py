"""Executable V 16-bit indexed element gather closure."""

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


def vrgatherei16(vd, vs2, vs1, vm=1):
    return ((0x0E << 26) | ((vm & 1) << 25) | ((vs2 & 0x1F) << 20) |
            ((vs1 & 0x1F) << 15) | (0b000 << 12) |
            ((vd & 0x1F) << 7) | OP_V)


def csrrwi(csr, zimm):
    return (((csr & 0xFFF) << 20) | ((zimm & 0x1F) << 15) |
            (0b101 << 12) | 0x73)


class _VGatherEI16Bench(Elaboratable):
    def __init__(self, extensions):
        program = [
            vsetivli(17, 1, vtype=0x10),
            lui(1, 0x2C211), enc_i(OP_IMM, 1, 0, 1, 0x60B),
            vmv_s_x(2, 1),
            lui(1, 0x00070), enc_i(OP_IMM, 1, 0, 1, 3),
            vmv_s_x(4, 1),
            lui(1, 0x09091), enc_i(OP_IMM, 1, 0, 1, -0x6F7),
            vmv_s_x(6, 1), vmv_s_x(7, 1), vmv_s_x(8, 1),
            vsetivli(17, 2),
            enc_i(OP_IMM, 1, 0, 0, 2), vmv_s_x(0, 1),
            *([nop()] * 3),
            vrgatherei16(6, 2, 4),
            csrrwi(0x008, 1),
            vrgatherei16(7, 2, 4),
            vrgatherei16(8, 2, 4, vm=0),
            vsetivli(17, 1, vtype=0x10),
            *([nop()] * 3),
            vmv_x_s(20, 6), vmv_x_s(21, 7), vmv_x_s(22, 8),
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
    dut = _VGatherEI16Bench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    result = {}

    def process():
        for _ in range(900):
            yield Tick()
        for reg in range(20, 23):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            result[reg] = yield dut.core.dbg_reg_rdata

    sim.add_process(process)
    sim.run()
    return result


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_vrgatherei16_emul_bounds_mask_and_vstart(extensions):
    assert run(extensions) == {
        20: 0x0909002C,
        21: 0x09090009,
        22: 0x09090009,
    }


def test_vrgatherei16_disabled_without_v():
    assert all(value == 0 for value in run("RV32I+GC").values())
