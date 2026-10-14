"""Executable V integer add/subtract family closure."""

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


def varith(funct6, funct3, vd, vs2, operand, vm=1):
    return ((funct6 << 26) | ((vm & 1) << 25) | ((vs2 & 0x1F) << 20) |
            ((operand & 0x1F) << 15) | (funct3 << 12) | ((vd & 0x1F) << 7) | OP_V)


class _VIntegerArithBench(Elaboratable):
    def __init__(self, extensions):
        program = [
            vsetivli(10, 4, vsew=0),
            vmv_v_i(1, 5), vmv_v_i(2, 3),
            *([nop()] * 3),
            varith(0x00, 0b000, 3, 1, 2),
            varith(0x02, 0b000, 4, 1, 2),
            varith(0x00, 0b011, 5, 1, -1),
            enc_i(OP_IMM, 6, 0, 0, 2),
            varith(0x00, 0b100, 6, 1, 6),
            varith(0x03, 0b011, 7, 1, 10),
            varith(0x03, 0b100, 8, 1, 6),
            enc_i(OP_IMM, 2, 0, 0, 5), vmv_s_x(0, 2),
            vmv_v_i(10, 9),
            *([nop()] * 3),
            varith(0x00, 0b000, 10, 1, 2, vm=0),
            vsetivli(10, 4, vsew=0, vma=1), vmv_v_i(11, 9),
            varith(0x00, 0b000, 11, 1, 2, vm=0),
            vsetivli(10, 2, vsew=0, vta=1),
            varith(0x00, 0b000, 12, 1, 2),
            vsetivli(10, 10, vsew=1, vlmul=1),
            vmv_v_i(16, -1), vmv_v_i(18, 2),
            *([nop()] * 3),
            varith(0x00, 0b000, 20, 16, 18),
            vsetivli(10, 2, vsew=2, vlmul=7),
            vmv_v_i(24, -1), vmv_v_i(25, 2),
            *([nop()] * 3),
            varith(0x00, 0b000, 26, 24, 25),
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
    dut = _VIntegerArithBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    result = {}

    def process():
        for _ in range(700):
            yield Tick()
        for reg in (3, 4, 5, 6, 7, 8, 10, 11, 12, 20, 21, 26):
            yield dut.core.dbg_vreg_addr.eq(reg)
            yield Tick()
            result[reg] = yield dut.core.dbg_vreg_rdata

    sim.add_process(process)
    sim.run()
    return result


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_v_integer_add_sub_mask_tail_and_groups(extensions):
    result = run(extensions)
    assert result[3] & 0xFFFFFFFF == 0x08080808
    assert result[4] & 0xFFFFFFFF == 0x02020202
    assert result[5] & 0xFFFFFFFF == 0x04040404
    assert result[6] & 0xFFFFFFFF == 0x07070707
    assert result[7] & 0xFFFFFFFF == 0x05050505
    assert result[8] & 0xFFFFFFFF == 0xFDFDFDFD
    assert result[10] & 0xFFFFFFFF == 0x09080908
    assert result[11] & 0xFFFFFFFF == 0xFF08FF08
    assert result[12] == int.from_bytes(b"\x08\x08" + b"\xff" * 14, "little")
    assert result[20] == int.from_bytes(b"\x01\x00" * 8, "little")
    assert result[21] == int.from_bytes(b"\x01\x00" * 2 + b"\x00" * 12, "little")
    assert result[26] == 0x0000000100000001


def test_v_integer_add_sub_disabled_without_v():
    result = run("RV32I+GC")
    assert all(value == 0 for value in result.values())
