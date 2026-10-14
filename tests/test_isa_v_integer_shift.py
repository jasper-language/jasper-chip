"""Executable V integer logical and arithmetic shift closure."""

import pytest
from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.isa import OP_IMM, OP_V, enc_i
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


EXTENSIONS = ("RV32I+GC+V", "RV32I+GC+*")
LUI = 0x37


def nop():
    return enc_i(OP_IMM, 0, 0, 0, 0)


def lui(rd, imm20):
    return ((imm20 & 0xFFFFF) << 12) | ((rd & 0x1F) << 7) | LUI


def vsetivli(rd, avl, vsew=0, vlmul=0, vta=0, vma=0):
    value = ((vma & 1) << 7) | ((vta & 1) << 6) | ((vsew & 7) << 3) | (vlmul & 7)
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


def vshift(funct6, funct3, vd, vs2, operand, vm=1):
    return ((funct6 << 26) | ((vm & 1) << 25) | ((vs2 & 0x1F) << 20) |
            ((operand & 0x1F) << 15) | (funct3 << 12) | ((vd & 0x1F) << 7) | OP_V)


class _VIntegerShiftBench(Elaboratable):
    def __init__(self, extensions):
        program = [
            vsetivli(10, 4, vsew=0),
            enc_i(OP_IMM, 1, 0, 0, -127), vmv_v_x(1, 1), vmv_v_i(2, 1),
            *([nop()] * 3),
            vshift(0x25, 0b000, 3, 1, 2),
            vshift(0x28, 0b000, 4, 1, 2),
            vshift(0x29, 0b000, 5, 1, 2),
            vshift(0x25, 0b011, 6, 1, 7),
            enc_i(OP_IMM, 3, 0, 0, 9),
            vshift(0x28, 0b100, 7, 1, 3),
            enc_i(OP_IMM, 4, 0, 0, 5), vmv_s_x(0, 4), vmv_v_i(8, 9),
            *([nop()] * 3),
            vshift(0x28, 0b000, 8, 1, 2, vm=0),
            vsetivli(10, 4, vsew=0, vma=1), vmv_v_i(9, 9),
            vshift(0x28, 0b000, 9, 1, 2, vm=0),
            vsetivli(10, 2, vsew=0, vta=1),
            vshift(0x29, 0b000, 10, 1, 2),
            vsetivli(10, 10, vsew=1, vlmul=1),
            lui(5, 8), enc_i(OP_IMM, 5, 0, 5, 1), vmv_v_x(16, 5),
            enc_i(OP_IMM, 6, 0, 0, 17), vmv_v_x(18, 6),
            *([nop()] * 3),
            vshift(0x25, 0b000, 20, 16, 18),
            vshift(0x28, 0b000, 22, 16, 18),
            vsetivli(10, 2, vsew=2, vlmul=7),
            lui(7, 0x80000), vmv_v_x(24, 7),
            vshift(0x28, 0b011, 25, 24, 31),
            vshift(0x29, 0b011, 26, 24, 31),
            0x0000006F,
        ]
        program += [nop()] * (176 - len(program))
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
    dut = _VIntegerShiftBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    result = {}

    def process():
        for _ in range(780):
            yield Tick()
        for reg in (3, 4, 5, 6, 7, 8, 9, 10, 20, 21, 22, 23, 25, 26):
            yield dut.core.dbg_vreg_addr.eq(reg)
            yield Tick()
            result[reg] = yield dut.core.dbg_vreg_rdata

    sim.add_process(process)
    sim.run()
    return result


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_v_integer_shift_masked_amount_sign_mask_tail_groups(extensions):
    result = run(extensions)
    assert result[3] & 0xFFFFFFFF == 0x02020202
    assert result[4] & 0xFFFFFFFF == 0x40404040
    assert result[5] & 0xFFFFFFFF == 0xC0C0C0C0
    assert result[6] & 0xFFFFFFFF == 0x80808080
    assert result[7] & 0xFFFFFFFF == 0x40404040
    assert result[8] & 0xFFFFFFFF == 0x09400940
    assert result[9] & 0xFFFFFFFF == 0xFF40FF40
    assert result[10] == int.from_bytes(b"\xc0\xc0" + b"\xff" * 14, "little")
    assert result[20] == int.from_bytes(b"\x02\x00" * 8, "little")
    assert result[21] == int.from_bytes(b"\x02\x00" * 2 + b"\x00" * 12, "little")
    assert result[22] == int.from_bytes(b"\x00\x40" * 8, "little")
    assert result[23] == int.from_bytes(b"\x00\x40" * 2 + b"\x00" * 12, "little")
    assert result[25] == 0x0000000100000001
    assert result[26] == (1 << 64) - 1


def test_v_integer_shift_disabled_without_v():
    result = run("RV32I+GC")
    assert all(value == 0 for value in result.values())
