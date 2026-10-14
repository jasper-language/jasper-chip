"""Executable V integer slide-up and slide-down closure."""

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


def slide(vd, vs2, offset, down, immediate=False, vm=1):
    funct6 = 0x0F if down else 0x0E
    funct3 = 0b011 if immediate else 0b100
    return ((funct6 << 26) | ((vm & 1) << 25) |
            ((vs2 & 0x1F) << 20) | ((offset & 0x1F) << 15) |
            (funct3 << 12) | ((vd & 0x1F) << 7) | OP_V)


def csrrwi(csr, zimm):
    return (((csr & 0xFFF) << 20) | ((zimm & 0x1F) << 15) |
            (0b101 << 12) | 0x73)


class _VSlideBench(Elaboratable):
    def __init__(self, extensions):
        program = [
            vsetivli(17, 1, vtype=0x10),
            lui(1, 0x04030), enc_i(OP_IMM, 1, 0, 1, 0x201),
            vmv_s_x(2, 1),
            lui(1, 0x09091), enc_i(OP_IMM, 1, 0, 1, -0x6F7),
            vmv_s_x(4, 1), vmv_s_x(6, 1), vmv_s_x(8, 1),
            vmv_s_x(9, 1),
            vsetivli(17, 4),
            enc_i(OP_IMM, 1, 0, 0, 1),
            *([nop()] * 3),
            slide(4, 2, 1, down=False),
            slide(5, 2, 1, down=True),
            slide(6, 2, 2, down=False, immediate=True),
            slide(7, 2, 2, down=True, immediate=True),
            enc_i(OP_IMM, 18, 0, 0, 0x05), vmv_s_x(0, 18),
            *([nop()] * 3),
            slide(8, 2, 1, down=False, vm=0),
            csrrwi(0x008, 2),
            slide(9, 2, 1, down=True),
            slide(10, 2, 1, down=True),
            vsetivli(17, 1, vtype=0x10),
            *([nop()] * 3),
            *[vmv_x_s(20 + offset, 4 + offset) for offset in range(7)],
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
    dut = _VSlideBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    result = {}

    def process():
        for _ in range(950):
            yield Tick()
        for reg in range(20, 27):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            result[reg] = yield dut.core.dbg_reg_rdata

    sim.add_process(process)
    sim.run()
    return result


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_slides_offsets_mask_vstart_and_zero_fill(extensions):
    assert run(extensions) == {
        20: 0x03020109, 21: 0x00040302,
        22: 0x02010909, 23: 0x00000403,
        24: 0x09020909, 25: 0x00040909,
        26: 0x00040302,
    }


def test_slides_disabled_without_v():
    assert all(value == 0 for value in run("RV32I+GC").values())
