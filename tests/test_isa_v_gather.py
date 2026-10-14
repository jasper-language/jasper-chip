"""Executable V indexed element gather closure."""

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


def vrgather(vd, vs2, index, form, vm=1):
    funct3 = {"vv": 0b000, "vx": 0b100, "vi": 0b011}[form]
    return ((0x0C << 26) | ((vm & 1) << 25) | ((vs2 & 0x1F) << 20) |
            ((index & 0x1F) << 15) | (funct3 << 12) |
            ((vd & 0x1F) << 7) | OP_V)


def csrrwi(csr, zimm):
    return (((csr & 0xFFF) << 20) | ((zimm & 0x1F) << 15) |
            (0b101 << 12) | 0x73)


class _VGatherBench(Elaboratable):
    def __init__(self, extensions):
        program = [
            vsetivli(17, 1, vtype=0x10),
            lui(1, 0x2C211), enc_i(OP_IMM, 1, 0, 1, 0x60B),
            vmv_s_x(2, 1),
            lui(1, 0x01070), enc_i(OP_IMM, 1, 0, 1, 3),
            vmv_s_x(3, 1),
            lui(1, 0x09091), enc_i(OP_IMM, 1, 0, 1, -0x6F7),
            vmv_s_x(4, 1), vmv_s_x(5, 1), vmv_s_x(6, 1),
            vmv_s_x(7, 1), vmv_s_x(8, 1),
            vsetivli(17, 4),
            enc_i(OP_IMM, 9, 0, 0, 1),
            enc_i(OP_IMM, 1, 0, 0, 5), vmv_s_x(0, 1),
            *([nop()] * 3),
            vrgather(4, 2, 3, "vv"),
            vrgather(5, 2, 9, "vx"),
            vrgather(6, 2, 2, "vi"),
            vrgather(7, 2, 3, "vv", vm=0),
            csrrwi(0x008, 2),
            vrgather(8, 2, 3, "vv"),
            vsetivli(17, 1, vtype=0x10),
            *([nop()] * 3),
            *[vmv_x_s(20 + offset, 4 + offset) for offset in range(5)],
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
    dut = _VGatherBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    result = {}

    def process():
        for _ in range(950):
            yield Tick()
        for reg in range(20, 25):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            result[reg] = yield dut.core.dbg_reg_rdata

    sim.add_process(process)
    sim.run()
    return result


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_vrgather_forms_bounds_mask_and_vstart(extensions):
    assert run(extensions) == {
        20: 0x16000B2C,
        21: 0x16161616,
        22: 0x21212121,
        23: 0x0900092C,
        24: 0x16000909,
    }


def test_vrgather_disabled_without_v():
    assert all(value == 0 for value in run("RV32I+GC").values())
