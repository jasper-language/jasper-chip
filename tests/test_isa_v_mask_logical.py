"""Executable V mask-register logical instruction closure."""

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


def mask_logical(vd, vs2, vs1, funct6, vm=1):
    return (((funct6 & 0x3F) << 26) | ((vm & 1) << 25) |
            ((vs2 & 0x1F) << 20) | ((vs1 & 0x1F) << 15) |
            (0b010 << 12) | ((vd & 0x1F) << 7) | OP_V)


def csrrwi(csr, zimm):
    return (((csr & 0xFFF) << 20) | ((zimm & 0x1F) << 15) |
            (0b101 << 12) | 0x73)


class _VMaskLogicalBench(Elaboratable):
    def __init__(self, extensions):
        program = [
            vsetivli(17, 8),
            enc_i(OP_IMM, 1, 0, 0, 0xB4), vmv_s_x(2, 1),
            enc_i(OP_IMM, 1, 0, 0, 0x5A), vmv_s_x(3, 1),
            *([nop()] * 3),
        ]
        for offset, funct6 in enumerate(range(0x18, 0x20)):
            program.append(mask_logical(4 + offset, 2, 3, funct6))
        program += [
            *([nop()] * 3),
            *[vmv_x_s(20 + offset, 4 + offset) for offset in range(8)],
            enc_i(OP_IMM, 1, 0, 0, 0x0F), vmv_s_x(13, 1),
            csrrwi(0x008, 4),
            mask_logical(13, 2, 3, 0x19),
            *([nop()] * 3), vmv_x_s(28, 13),
            mask_logical(14, 2, 3, 0x1B),
            *([nop()] * 3), vmv_x_s(29, 14),
            vsetivli(17, 0),
            enc_i(OP_IMM, 1, 0, 0, 0), vmv_s_x(15, 1),
            mask_logical(15, 2, 3, 0x1A),
            *([nop()] * 3), vmv_x_s(30, 15),
            vsetivli(17, 8),
            enc_i(OP_IMM, 1, 0, 0, 0x33), vmv_s_x(16, 1),
            mask_logical(16, 2, 3, 0x19, vm=0),
            *([nop()] * 3), vmv_x_s(31, 16),
            0x0000006F,
        ]
        program += [nop()] * (128 - len(program))
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
    dut = _VMaskLogicalBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    result = {}

    def process():
        for _ in range(1100):
            yield Tick()
        for reg in range(20, 32):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            result[reg] = yield dut.core.dbg_reg_rdata

    sim.add_process(process)
    sim.run()
    return result


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_mask_logical_truth_table_vstart_tail_and_reserved_vm(extensions):
    assert run(extensions) == {
        20: 0xFFFFFFA4, 21: 0x10, 22: 0xFFFFFFFE, 23: 0xFFFFFFEE,
        24: 0xFFFFFFB5, 25: 0xFFFFFFEF, 26: 0x01, 27: 0x11,
        28: 0x1F, 29: 0xFFFFFFEE, 30: 0xFFFFFFFF, 31: 0x33,
    }


def test_mask_logical_disabled_without_v():
    assert all(value == 0 for value in run("RV32I+GC").values())
