"""Executable V fixed-point scaling right-shift closure."""

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


def vshift(funct6, funct3, vd, vs2, operand, vm=1):
    return ((funct6 << 26) | ((vm & 1) << 25) | ((vs2 & 0x1F) << 20) |
            ((operand & 0x1F) << 15) | (funct3 << 12) | ((vd & 0x1F) << 7) | OP_V)


def csrwi(csr, value):
    return ((csr & 0xFFF) << 20) | ((value & 0x1F) << 15) | (0b101 << 12) | SYSTEM


class _VScalingShiftBench(Elaboratable):
    def __init__(self, extensions):
        program = [
            vsetivli(15, 4),
            vmv_v_i(1, 1), vmv_v_i(2, 1),
            *([nop()] * 3),
            csrwi(0x00A, 0), vshift(0x2A, 0b000, 3, 1, 2),
            csrwi(0x00A, 1), vshift(0x2A, 0b000, 4, 1, 2),
            csrwi(0x00A, 2), vshift(0x2A, 0b000, 5, 1, 2),
            csrwi(0x00A, 3), vshift(0x2A, 0b000, 6, 1, 2),
            vmv_v_i(7, -3),
            *([nop()] * 3),
            csrwi(0x00A, 0), vshift(0x2B, 0b011, 8, 7, 1),
            csrwi(0x00A, 1), vshift(0x2B, 0b011, 9, 7, 1),
            csrwi(0x00A, 2), vshift(0x2B, 0b011, 10, 7, 1),
            csrwi(0x00A, 3), vshift(0x2B, 0b011, 11, 7, 1),
            vmv_v_i(12, 3), enc_i(OP_IMM, 2, 0, 0, 1),
            *([nop()] * 3),
            csrwi(0x00A, 1), vshift(0x2A, 0b100, 13, 12, 2),
            vmv_s_x(0, 0), vmv_v_i(14, 7),
            *([nop()] * 3),
            vshift(0x2A, 0b000, 14, 1, 2, vm=0),
            vsetivli(15, 10, vsew=1, vlmul=1),
            vmv_v_i(16, 3),
            *([nop()] * 3),
            vshift(0x2A, 0b100, 20, 16, 2),
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
    dut = _VScalingShiftBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    result = {}

    def process():
        for _ in range(960):
            yield Tick()
        for reg in (3, 4, 5, 6, 8, 9, 10, 11, 13, 14, 20, 21):
            yield dut.core.dbg_vreg_addr.eq(reg)
            yield Tick()
            result[reg] = yield dut.core.dbg_vreg_rdata

    sim.add_process(process)
    sim.run()
    return result


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_v_scaling_shift_rounding_signed_mask_and_groups(extensions):
    result = run(extensions)
    assert result[3] == 0x01010101
    assert result[4] == 0
    assert result[5] == 0
    assert result[6] == 0x01010101
    assert result[8] == 0xFFFFFFFF
    assert result[9] == 0xFEFEFEFE
    assert result[10] == 0xFEFEFEFE
    assert result[11] == 0xFFFFFFFF
    assert result[13] == 0x02020202
    assert result[14] == 0x07070707
    assert result[20] == int.from_bytes(bytes([2, 0] * 8), "little")
    assert result[21] == 0x00020002


def test_v_scaling_shift_disabled_without_v():
    result = run("RV32I+GC")
    assert all(value == 0 for value in result.values())
