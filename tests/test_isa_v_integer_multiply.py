"""Executable V single-width integer multiply closure."""

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


def vmul(funct6, funct3, vd, vs2, operand, vm=1):
    return ((funct6 << 26) | ((vm & 1) << 25) | ((vs2 & 0x1F) << 20) |
            ((operand & 0x1F) << 15) | (funct3 << 12) | ((vd & 0x1F) << 7) | OP_V)


class _VIntegerMultiplyBench(Elaboratable):
    def __init__(self, extensions):
        program = [
            vsetivli(17, 4),
            vmv_v_i(1, -7), vmv_v_i(2, 9),
            enc_i(OP_IMM, 1, 0, 0, 240), vmv_v_x(3, 1), vmv_v_i(4, 2),
            enc_i(OP_IMM, 1, 0, 0, -128), vmv_v_x(5, 1),
            *([nop()] * 3),
            vmul(0x25, 0b010, 6, 1, 2),
            vmul(0x24, 0b010, 7, 3, 4),
            vmul(0x27, 0b010, 8, 5, 4),
            vmul(0x26, 0b010, 9, 5, 3),
            enc_i(OP_IMM, 2, 0, 0, 3),
            *([nop()] * 3),
            vmul(0x25, 0b110, 10, 2, 2),
            vmv_s_x(0, 0), vmv_v_i(11, 5),
            *([nop()] * 3),
            vmul(0x25, 0b010, 11, 1, 2, vm=0),
            vsetivli(17, 10, vsew=1, vlmul=1),
            enc_i(OP_IMM, 1, 0, 0, -300), vmv_v_x(16, 1),
            enc_i(OP_IMM, 2, 0, 0, 200),
            *([nop()] * 3),
            vmul(0x25, 0b110, 18, 16, 2),
            vmul(0x27, 0b110, 20, 16, 2),
            vsetivli(17, 2, vsew=2, vlmul=7),
            vmv_v_i(24, -2), enc_i(OP_IMM, 2, 0, 0, 3),
            *([nop()] * 3),
            vmul(0x27, 0b110, 25, 24, 2),
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
    dut = _VIntegerMultiplyBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    result = {}

    def process():
        for _ in range(1000):
            yield Tick()
        for reg in (6, 7, 8, 9, 10, 11, 18, 19, 20, 21, 25):
            yield dut.core.dbg_vreg_addr.eq(reg)
            yield Tick()
            result[reg] = yield dut.core.dbg_vreg_rdata

    sim.add_process(process)
    sim.run()
    return result


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_v_integer_multiply_low_high_signed_mask_and_groups(extensions):
    result = run(extensions)
    assert result[6] == 0xC1C1C1C1
    assert result[7] == 0x01010101
    assert result[8] == 0xFFFFFFFF
    assert result[9] == 0x88888888
    assert result[10] == 0x1B1B1B1B
    assert result[11] == 0x05050505
    assert result[18] == int.from_bytes(bytes([0xA0, 0x15] * 8), "little")
    assert result[19] == 0x15A015A0
    assert result[20] == (1 << 128) - 1
    assert result[21] == 0xFFFFFFFF
    assert result[25] == 0xFFFFFFFFFFFFFFFF


def test_v_integer_multiply_disabled_without_v():
    result = run("RV32I+GC")
    assert all(value == 0 for value in result.values())
