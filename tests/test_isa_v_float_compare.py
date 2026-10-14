"""Executable V floating comparison family closure."""

import pytest
from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.isa import LOAD_FP, OP_IMM, OP_V, SYSTEM, enc_i
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


EXTENSIONS = ("RV32I+GC+V", "RV32I+GC+*")
ALL_ONES = (1 << 128) - 1


def nop():
    return enc_i(OP_IMM, 0, 0, 0, 0)


def vsetivli(rd, avl, vsew=2, vlmul=0):
    vtype = ((vsew & 7) << 3) | (vlmul & 7)
    return ((0b11 << 30) | (vtype << 20) | ((avl & 0x1F) << 15) |
            (0b111 << 12) | ((rd & 0x1F) << 7) | OP_V)


def vop(funct6, funct3, vd, vs2, operand, vm=1):
    return ((funct6 << 26) | ((vm & 1) << 25) | ((vs2 & 0x1F) << 20) |
            ((operand & 0x1F) << 15) | (funct3 << 12) | ((vd & 0x1F) << 7) | OP_V)


def vfmv_v_f(vd, fs1):
    return vop(0x17, 0b101, vd, 0, fs1)


def vmv_s_x(vd, rs1):
    return vop(0x10, 0b110, vd, 0, rs1)


def csrrwi(csr, value):
    return ((csr & 0xFFF) << 20) | ((value & 0x1F) << 15) | (0b101 << 12) | SYSTEM


def csrrs(rd, csr):
    return ((csr & 0xFFF) << 20) | (0b010 << 12) | ((rd & 0x1F) << 7) | SYSTEM


class _VFloatCompareBench(Elaboratable):
    def __init__(self, extensions):
        program = [
            enc_i(LOAD_FP, 1, 0b010, 0, 0), *([nop()] * 4),
            enc_i(LOAD_FP, 2, 0b010, 0, 4), *([nop()] * 4),
            enc_i(LOAD_FP, 3, 0b010, 0, 8), *([nop()] * 4),
            enc_i(LOAD_FP, 4, 0b010, 0, 12), *([nop()] * 4),
            enc_i(LOAD_FP, 5, 0b011, 0, 16), *([nop()] * 4),
            enc_i(LOAD_FP, 6, 0b011, 0, 24), *([nop()] * 4),
            enc_i(LOAD_FP, 7, 0b011, 0, 32), *([nop()] * 4),
            enc_i(LOAD_FP, 8, 0b011, 0, 40), *([nop()] * 4),
            enc_i(LOAD_FP, 9, 0b011, 0, 48), *([nop()] * 6),
            csrrwi(0x001, 0), vsetivli(17, 4),
            vfmv_v_f(1, 1), vfmv_v_f(2, 2),
            vop(0x18, 0b001, 4, 1, 1),
            vop(0x1C, 0b001, 5, 1, 1),
            vop(0x1B, 0b001, 6, 2, 1),
            vop(0x19, 0b001, 7, 1, 1),
            vop(0x1D, 0b101, 8, 1, 2),
            vop(0x1F, 0b101, 9, 1, 1),
            vop(0x18, 0b101, 10, 1, 3),
            vop(0x1C, 0b101, 11, 1, 3), csrrs(20, 0x001),
            csrrwi(0x001, 0), vop(0x1B, 0b101, 12, 1, 3), csrrs(21, 0x001),
            csrrwi(0x001, 0), vop(0x18, 0b101, 13, 1, 4), csrrs(22, 0x001),
            csrrwi(0x001, 0), vop(0x1C, 0b101, 14, 1, 5), csrrs(23, 0x001),
            vop(0x18, 0b001, 15, 1, 1),
            enc_i(OP_IMM, 3, 0, 0, 0), vmv_s_x(0, 3),
            csrrwi(0x001, 0), vop(0x1B, 0b101, 15, 1, 3, vm=0), csrrs(24, 0x001),
            vop(0x1C, 0b001, 16, 1, 1), csrrwi(0x008, 2),
            vop(0x18, 0b001, 16, 1, 1),
            vsetivli(17, 8, vlmul=1),
            vfmv_v_f(18, 1), vfmv_v_f(20, 2),
            vop(0x1B, 0b001, 26, 20, 18),
            csrrwi(0x001, 0), vsetivli(17, 2, vsew=3),
            vfmv_v_f(18, 6), vfmv_v_f(20, 7),
            vop(0x1B, 0b001, 22, 20, 18),
            vop(0x18, 0b101, 23, 18, 8), csrrs(25, 0x001),
            csrrwi(0x001, 0), vop(0x18, 0b101, 24, 18, 9), csrrs(26, 0x001),
            0x0000006F,
        ]
        if extensions == "RV32I+F+V":
            program = [
                enc_i(LOAD_FP, 1, 0b010, 0, 0), *([nop()] * 6),
                vsetivli(17, 2, vsew=3),
                vop(0x18, 0b101, 20, 0, 1),
                0x0000006F,
            ]
        program += [nop()] * (256 - len(program))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=len(program), init=program)
        self.dmem = SimpleDMem(words=16, init=[
            0x3F800000, 0xC0000000, 0x7FC12345, 0x7F812345,
            0xBF800000, 0x00000000,
            0x00000000, 0x40080000,
            0x00000000, 0xC0100000,
            0x00000001, 0x7FF80000,
            0x00000001, 0x7FF00000,
        ] + [0] * 2)

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
    dut = _VFloatCompareBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    result = {}

    def process():
        for _ in range(1800):
            yield Tick()
        for reg in (4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
                    16, 20, 22, 23, 24, 26):
            yield dut.core.dbg_vreg_addr.eq(reg)
            yield Tick()
            result[reg] = yield dut.core.dbg_vreg_rdata
        for reg in range(20, 27):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield dut.core.dbg_reg_rdata

    sim.add_process(process)
    sim.run()
    return result


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_v_float_compare_nan_mask_restart_and_groups(extensions):
    result = run(extensions)
    low4_zero = ALL_ONES ^ 0xF
    assert result[4] == ALL_ONES
    assert result[5] == low4_zero
    assert result[6] == ALL_ONES
    assert result[7] == ALL_ONES
    assert result[8] == ALL_ONES
    assert result[9] == ALL_ONES
    assert result[10] == low4_zero
    assert result[11] == ALL_ONES
    assert result[12] == low4_zero
    assert result[13] == low4_zero
    assert result[14] == ALL_ONES
    assert result[15] == ALL_ONES
    assert result[16] == (ALL_ONES ^ 0x3)
    assert result[26] == ALL_ONES
    assert result[22] == ALL_ONES
    assert result[23] == (ALL_ONES ^ 0x3)
    assert result[24] == (ALL_ONES ^ 0x3)
    assert result["x20"] == 0
    assert result["x21"] == 0x10
    assert result["x22"] == 0x10
    assert result["x23"] == 0
    assert result["x24"] == 0
    assert result["x25"] == 0
    assert result["x26"] == 0x10


def test_v_float_compare_disabled_without_v():
    assert all(value == 0 for value in run("RV32I+GC").values())


def test_v_float_compare_sew64_requires_d():
    assert run("RV32I+F+V")[20] == 0
