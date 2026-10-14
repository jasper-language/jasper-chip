"""Executable V integer divide and remainder closure."""

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


def vdivrem(funct6, funct3, vd, vs2, operand, vm=1):
    return ((funct6 << 26) | ((vm & 1) << 25) | ((vs2 & 0x1F) << 20) |
            ((operand & 0x1F) << 15) | (funct3 << 12) | ((vd & 0x1F) << 7) | OP_V)


class _VDivRemBench(Elaboratable):
    def __init__(self, extensions):
        program = [
            vsetivli(17, 4),
            vmv_v_i(1, 7), vmv_v_i(2, 2),
            *([nop()] * 3),
            vdivrem(0x20, 0b010, 3, 1, 2),
            vdivrem(0x22, 0b010, 4, 1, 2),
            vmv_v_i(5, -7), enc_i(OP_IMM, 2, 0, 0, 2),
            *([nop()] * 3),
            vdivrem(0x21, 0b110, 6, 5, 2),
            vdivrem(0x23, 0b110, 7, 5, 2),
            vmv_v_i(8, 0),
            *([nop()] * 3),
            vdivrem(0x20, 0b010, 9, 1, 8),
            vdivrem(0x22, 0b010, 10, 1, 8),
            vdivrem(0x21, 0b010, 11, 5, 8),
            vdivrem(0x23, 0b010, 12, 5, 8),
            enc_i(OP_IMM, 1, 0, 0, -128), vmv_v_x(13, 1),
            vmv_v_i(14, -1),
            *([nop()] * 3),
            vdivrem(0x21, 0b010, 15, 13, 14),
            vdivrem(0x23, 0b010, 16, 13, 14),
            vmv_s_x(0, 0), vmv_v_i(18, 5),
            *([nop()] * 3),
            vdivrem(0x20, 0b010, 18, 1, 2, vm=0),
            vsetivli(17, 10, vsew=1, vlmul=1),
            enc_i(OP_IMM, 1, 0, 0, 100), vmv_v_x(20, 1),
            enc_i(OP_IMM, 2, 0, 0, 3),
            *([nop()] * 3),
            vdivrem(0x20, 0b110, 22, 20, 2),
            vdivrem(0x22, 0b110, 24, 20, 2),
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
    dut = _VDivRemBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    result = {}

    def process():
        for _ in range(1000):
            yield Tick()
        for reg in (3, 4, 6, 7, 9, 10, 11, 12, 15, 16, 18, 22, 23, 24, 25):
            yield dut.core.dbg_vreg_addr.eq(reg)
            yield Tick()
            result[reg] = yield dut.core.dbg_vreg_rdata

    sim.add_process(process)
    sim.run()
    return result


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_v_divrem_signed_zero_overflow_mask_and_groups(extensions):
    result = run(extensions)
    assert result[3] == 0x03030303
    assert result[4] == 0x01010101
    assert result[6] == 0xFDFDFDFD
    assert result[7] == 0xFFFFFFFF
    assert result[9] == 0xFFFFFFFF
    assert result[10] == 0x07070707
    assert result[11] == 0xFFFFFFFF
    assert result[12] == 0xF9F9F9F9
    assert result[15] == 0x80808080
    assert result[16] == 0
    assert result[18] == 0x05050505
    assert result[22] == int.from_bytes(bytes([33, 0] * 8), "little")
    assert result[23] == 0x00210021
    assert result[24] == int.from_bytes(bytes([1, 0] * 8), "little")
    assert result[25] == 0x00010001


def test_v_divrem_disabled_without_v():
    result = run("RV32I+GC")
    assert all(value == 0 for value in result.values())
