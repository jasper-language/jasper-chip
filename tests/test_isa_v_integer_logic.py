"""Executable V integer bitwise logic family closure."""

import pytest
from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.isa import OP_IMM, OP_V, enc_i
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


EXTENSIONS = ("RV32I+GC+V", "RV32I+GC+*")


def nop():
    return enc_i(OP_IMM, 0, 0, 0, 0)


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


def vlogic(funct6, funct3, vd, vs2, operand, vm=1):
    return ((funct6 << 26) | ((vm & 1) << 25) | ((vs2 & 0x1F) << 20) |
            ((operand & 0x1F) << 15) | (funct3 << 12) | ((vd & 0x1F) << 7) | OP_V)


class _VIntegerLogicBench(Elaboratable):
    def __init__(self, extensions):
        program = [
            vsetivli(10, 4, vsew=0),
            vmv_v_i(1, 15),
            enc_i(OP_IMM, 1, 0, 0, 0x55), vmv_v_x(2, 1),
            *([nop()] * 3),
            vlogic(0x09, 0b000, 3, 1, 2),
            vlogic(0x0A, 0b000, 4, 1, 2),
            vlogic(0x0B, 0b000, 5, 1, 2),
            vlogic(0x09, 0b011, 6, 1, -1),
            vlogic(0x0A, 0b011, 7, 1, -16),
            vlogic(0x0B, 0b100, 8, 1, 1),
            enc_i(OP_IMM, 2, 0, 0, 5), vmv_s_x(0, 2),
            vmv_v_i(9, 9),
            *([nop()] * 3),
            vlogic(0x09, 0b000, 9, 1, 2, vm=0),
            vsetivli(10, 4, vsew=0, vma=1), vmv_v_i(10, 9),
            vlogic(0x09, 0b000, 10, 1, 2, vm=0),
            vsetivli(10, 2, vsew=0, vta=1),
            vlogic(0x0B, 0b000, 11, 1, 2),
            vsetivli(10, 10, vsew=1, vlmul=1),
            enc_i(OP_IMM, 3, 0, 0, 0x123), vmv_v_x(16, 3), vmv_v_i(18, -1),
            *([nop()] * 3),
            vlogic(0x0B, 0b000, 20, 16, 18),
            vsetivli(10, 2, vsew=2, vlmul=7),
            vmv_v_i(24, -1),
            vlogic(0x09, 0b011, 25, 24, 15),
            0x0000006F,
        ]
        program += [nop()] * (160 - len(program))
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
    dut = _VIntegerLogicBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    result = {}

    def process():
        for _ in range(700):
            yield Tick()
        for reg in (3, 4, 5, 6, 7, 8, 9, 10, 11, 20, 21, 25):
            yield dut.core.dbg_vreg_addr.eq(reg)
            yield Tick()
            result[reg] = yield dut.core.dbg_vreg_rdata

    sim.add_process(process)
    sim.run()
    return result


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_v_integer_logic_mask_tail_and_groups(extensions):
    result = run(extensions)
    assert result[3] & 0xFFFFFFFF == 0x05050505
    assert result[4] & 0xFFFFFFFF == 0x5F5F5F5F
    assert result[5] & 0xFFFFFFFF == 0x5A5A5A5A
    assert result[6] & 0xFFFFFFFF == 0x0F0F0F0F
    assert result[7] & 0xFFFFFFFF == 0xFFFFFFFF
    assert result[8] & 0xFFFFFFFF == 0x5A5A5A5A
    assert result[9] & 0xFFFFFFFF == 0x09050905
    assert result[10] & 0xFFFFFFFF == 0xFF05FF05
    assert result[11] == int.from_bytes(b"\x5a\x5a" + b"\xff" * 14, "little")
    assert result[20] == int.from_bytes(b"\xdc\xfe" * 8, "little")
    assert result[21] == int.from_bytes(b"\xdc\xfe" * 2 + b"\x00" * 12, "little")
    assert result[25] == 0x0000000F0000000F


def test_v_integer_logic_disabled_without_v():
    result = run("RV32I+GC")
    assert all(value == 0 for value in result.values())
