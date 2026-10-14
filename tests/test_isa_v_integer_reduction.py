"""Executable V single-width integer reduction closure."""

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


def reduction(vd, vs2, vs1, funct6, vm=1):
    return (((funct6 & 0x3F) << 26) | ((vm & 1) << 25) |
            ((vs2 & 0x1F) << 20) | ((vs1 & 0x1F) << 15) |
            (0b010 << 12) | ((vd & 0x1F) << 7) | OP_V)


class _VIntegerReductionBench(Elaboratable):
    def __init__(self, extensions):
        program = [
            vsetivli(17, 1, vtype=0x10),
            lui(1, 0x03030), enc_i(OP_IMM, 1, 0, 1, -255),
            vmv_s_x(2, 1),
            enc_i(OP_IMM, 1, 0, 0, 5), vmv_s_x(3, 1),
            vsetivli(17, 4),
            *([nop()] * 3),
        ]
        for offset, funct6 in enumerate(range(8)):
            program.append(reduction(4 + offset, 2, 3, funct6))
        program += [
            *([nop()] * 3),
            *[vmv_x_s(20 + offset, 4 + offset) for offset in range(8)],
            enc_i(OP_IMM, 1, 0, 0, 0x0D), vmv_s_x(0, 1),
            reduction(12, 2, 3, 0x00, vm=0),
            *([nop()] * 3), vmv_x_s(28, 12),
            vsetivli(17, 0),
            reduction(13, 2, 3, 0x00),
            *([nop()] * 3), vmv_x_s(29, 13),
            0x0000006F,
        ]
        program += [nop()] * (120 - len(program))
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
    dut = _VIntegerReductionBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    result = {}

    def process():
        for _ in range(1050):
            yield Tick()
        for reg in range(20, 30):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            result[reg] = yield dut.core.dbg_reg_rdata

    sim.add_process(process)
    sim.run()
    return result


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_integer_reductions_signed_unsigned_mask_and_zero_vl(extensions):
    assert run(extensions) == {
        20: 10, 21: 0, 22: 0xFFFFFFFF, 23: 0xFFFFFFFA,
        24: 1, 25: 0xFFFFFFFF, 26: 0xFFFFFFFF, 27: 5,
        28: 11, 29: 0,
    }


def test_integer_reductions_disabled_without_v():
    assert all(value == 0 for value in run("RV32I+GC").values())
