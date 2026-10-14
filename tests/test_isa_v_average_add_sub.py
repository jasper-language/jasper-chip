"""Executable V fixed-point averaging add/subtract closure."""

import pytest
from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.isa import OP_IMM, OP_V, SYSTEM, enc_i
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


EXTENSIONS = ("RV32I+GC+V", "RV32I+GC+*")


def nop():
    return enc_i(OP_IMM, 0, 0, 0, 0)


def vsetivli(rd, avl, vsew=0, vlmul=0):
    value = ((vsew & 7) << 3) | (vlmul & 7)
    return ((0b11 << 30) | (value << 20) | ((avl & 0x1F) << 15) |
            (0b111 << 12) | ((rd & 0x1F) << 7) | OP_V)


def vmv_s_x(vd, rs1):
    return ((0x10 << 26) | (1 << 25) | ((rs1 & 0x1F) << 15) |
            (0b110 << 12) | ((vd & 0x1F) << 7) | OP_V)


def vmv_v_i(vd, imm):
    return ((0x17 << 26) | (1 << 25) | ((imm & 0x1F) << 15) |
            (0b011 << 12) | ((vd & 0x1F) << 7) | OP_V)


def vmv_v_x(vd, rs1):
    return ((0x17 << 26) | (1 << 25) | ((rs1 & 0x1F) << 15) |
            (0b100 << 12) | ((vd & 0x1F) << 7) | OP_V)


def vavg(funct6, funct3, vd, vs2, operand, vm=1):
    return ((funct6 << 26) | ((vm & 1) << 25) | ((vs2 & 0x1F) << 20) |
            ((operand & 0x1F) << 15) | (funct3 << 12) | ((vd & 0x1F) << 7) | OP_V)


def csrwi(csr, value):
    return ((csr & 0xFFF) << 20) | ((value & 0x1F) << 15) | (0b101 << 12) | SYSTEM


class _VAverageBench(Elaboratable):
    def __init__(self, extensions):
        program = [
            vsetivli(13, 4),
            enc_i(OP_IMM, 1, 0, 0, 0), vmv_v_x(1, 1),
            enc_i(OP_IMM, 2, 0, 0, 1), vmv_v_x(2, 2),
            *([nop()] * 3),
            csrwi(0x00A, 0), vavg(0x08, 0b010, 3, 1, 2),
            csrwi(0x00A, 1), vavg(0x08, 0b010, 4, 1, 2),
            csrwi(0x00A, 2), vavg(0x08, 0b010, 5, 1, 2),
            csrwi(0x00A, 3), vavg(0x08, 0b010, 6, 1, 2),
            enc_i(OP_IMM, 1, 0, 0, -3), vmv_v_x(7, 1),
            enc_i(OP_IMM, 2, 0, 0, 0),
            *([nop()] * 3),
            csrwi(0x00A, 0), vavg(0x09, 0b110, 8, 7, 2),
            csrwi(0x00A, 0), vavg(0x0A, 0b010, 9, 1, 2),
            csrwi(0x00A, 2), vavg(0x0A, 0b010, 10, 1, 2),
            enc_i(OP_IMM, 1, 0, 0, 127), vmv_v_x(11, 1),
            enc_i(OP_IMM, 2, 0, 0, -128), vmv_v_x(12, 2),
            *([nop()] * 3),
            csrwi(0x00A, 0), vavg(0x0B, 0b010, 13, 11, 12),
            csrwi(0x00A, 2), vavg(0x0B, 0b010, 14, 11, 12),
            vmv_s_x(0, 0), vmv_v_i(15, 7),
            *([nop()] * 3),
            vavg(0x08, 0b010, 15, 1, 2, vm=0),
            vsetivli(13, 10, vsew=1, vlmul=1),
            vmv_v_i(16, -1), vmv_v_i(18, -1),
            *([nop()] * 3),
            csrwi(0x00A, 1), vavg(0x08, 0b010, 20, 16, 18),
            0x0000006F,
        ]
        program += [nop()] * (192 - len(program))
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
    dut = _VAverageBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    result = {}

    def process():
        for _ in range(960):
            yield Tick()
        for reg in (3, 4, 5, 6, 8, 9, 10, 13, 14, 15, 20, 21):
            yield dut.core.dbg_vreg_addr.eq(reg)
            yield Tick()
            result[reg] = yield dut.core.dbg_vreg_rdata

    sim.add_process(process)
    sim.run()
    return result


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_v_average_all_rounding_modes_signed_unsigned_mask_and_groups(extensions):
    result = run(extensions)
    assert result[3] == 0x01010101
    assert result[4] == 0
    assert result[5] == 0
    assert result[6] == 0x01010101
    assert result[8] == 0xFFFFFFFF
    assert result[9] == 0
    assert result[10] == 0xFFFFFFFF
    assert result[13] == 0x80808080
    assert result[14] == 0x7F7F7F7F
    assert result[15] == 0x07070707
    assert result[20] == (1 << 128) - 1
    assert result[21] & 0xFFFFFFFF == 0xFFFFFFFF


def test_v_average_disabled_without_v():
    result = run("RV32I+GC")
    assert all(value == 0 for value in result.values())
