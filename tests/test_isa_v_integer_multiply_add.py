"""Executable V single-width integer multiply-add closure."""

import pytest
from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.isa import OP_IMM, OP_V, enc_i
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


def vmadd(funct6, funct3, vd, vs2, operand, vm=1):
    return ((funct6 << 26) | ((vm & 1) << 25) | ((vs2 & 0x1F) << 20) |
            ((operand & 0x1F) << 15) | (funct3 << 12) | ((vd & 0x1F) << 7) | OP_V)


class _VIntegerMultiplyAddBench(Elaboratable):
    def __init__(self, extensions):
        program = [
            vsetivli(17, 4),
            vmv_v_i(1, 3), vmv_v_i(2, 4),
            vmv_v_i(3, 5), vmv_v_i(4, 5),
            vmv_v_i(5, 5), vmv_v_i(6, 5),
            *([nop()] * 3),
            vmadd(0x2D, 0b010, 3, 2, 1),
            vmadd(0x2F, 0b010, 4, 2, 1),
            vmadd(0x29, 0b010, 5, 2, 1),
            vmadd(0x2B, 0b010, 6, 2, 1),
            enc_i(OP_IMM, 1, 0, 0, -2),
            vmv_v_i(7, 5), vmv_v_i(8, 5),
            *([nop()] * 3),
            vmadd(0x2D, 0b110, 7, 2, 1),
            vmadd(0x29, 0b110, 8, 2, 1),
            vmv_s_x(0, 0), vmv_v_i(9, 7),
            *([nop()] * 3),
            vmadd(0x2D, 0b010, 9, 2, 1, vm=0),
            vsetivli(17, 10, vsew=1, vlmul=1),
            enc_i(OP_IMM, 1, 0, 0, 1000), vmv_v_x(16, 1), vmv_v_x(18, 1),
            enc_i(OP_IMM, 2, 0, 0, 200), vmv_v_x(20, 2),
            enc_i(OP_IMM, 1, 0, 0, -3),
            *([nop()] * 3),
            vmadd(0x2D, 0b110, 16, 20, 1),
            vmadd(0x29, 0b110, 18, 20, 1),
            vsetivli(17, 2, vsew=2, vlmul=7),
            vmv_v_i(24, -2), vmv_v_i(25, 7),
            enc_i(OP_IMM, 1, 0, 0, -3),
            *([nop()] * 3),
            vmadd(0x2D, 0b110, 24, 25, 1),
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
    dut = _VIntegerMultiplyAddBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    result = {}

    def process():
        for _ in range(1000):
            yield Tick()
        for reg in (3, 4, 5, 6, 7, 8, 9, 16, 17, 18, 19, 24):
            yield dut.core.dbg_vreg_addr.eq(reg)
            yield Tick()
            result[reg] = yield dut.core.dbg_vreg_rdata

    sim.add_process(process)
    sim.run()
    return result


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_v_integer_multiply_add_destructive_forms_mask_and_groups(extensions):
    result = run(extensions)
    assert result[3] == 0x11111111
    assert result[4] == 0xF9F9F9F9
    assert result[5] == 0x13131313
    assert result[6] == 0xF5F5F5F5
    assert result[7] == 0xFDFDFDFD
    assert result[8] == 0xFAFAFAFA
    assert result[9] == 0x07070707
    assert result[16] == int.from_bytes(bytes([0x90, 0x01] * 8), "little")
    assert result[17] == 0x01900190
    assert result[18] == int.from_bytes(bytes([0x10, 0xF5] * 8), "little")
    assert result[19] == 0xF510F510
    assert result[24] == 0xFFFFFFE9FFFFFFE9


def test_v_integer_multiply_add_disabled_without_v():
    result = run("RV32I+GC")
    assert all(value == 0 for value in result.values())
