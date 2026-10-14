"""Executable V floating minimum/maximum family closure."""

import pytest
from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.isa import LOAD_FP, OP_IMM, OP_V, SYSTEM, enc_i
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


EXTENSIONS = ("RV32I+GC+V", "RV32I+GC+*")


def nop():
    return enc_i(OP_IMM, 0, 0, 0, 0)


def vsetivli(rd, avl, vsew=2, vlmul=0, vta=0):
    vtype = ((vta & 1) << 6) | ((vsew & 7) << 3) | (vlmul & 7)
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


class _VFloatMinMaxBench(Elaboratable):
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
            enc_i(LOAD_FP, 9, 0b011, 0, 48), *([nop()] * 4),
            enc_i(LOAD_FP, 10, 0b010, 0, 56), *([nop()] * 4),
            enc_i(LOAD_FP, 11, 0b010, 0, 60), *([nop()] * 6),
            csrrwi(0x001, 0), vsetivli(17, 4),
            vfmv_v_f(1, 1), vfmv_v_f(2, 2),
            vop(0x04, 0b001, 4, 1, 2),
            vop(0x06, 0b001, 5, 1, 2),
            vop(0x04, 0b101, 6, 1, 3),
            vop(0x06, 0b101, 7, 1, 4), csrrs(20, 0x001),
            csrrwi(0x001, 0), vop(0x04, 0b101, 8, 1, 5), csrrs(21, 0x001),
            vfmv_v_f(9, 3), vop(0x04, 0b101, 10, 9, 3),
            vfmv_v_f(11, 10),
            vop(0x04, 0b101, 12, 11, 11),
            vop(0x06, 0b101, 13, 11, 11),
            enc_i(OP_IMM, 3, 0, 0, 0), vmv_s_x(0, 3),
            csrrwi(0x001, 0), vfmv_v_f(14, 1),
            vop(0x06, 0b101, 14, 1, 4, vm=0), csrrs(22, 0x001),
            vfmv_v_f(15, 1), csrrwi(0x008, 2),
            vop(0x04, 0b001, 15, 1, 2),
            vsetivli(17, 2, vta=1), vop(0x04, 0b001, 16, 1, 2),
            vsetivli(17, 8, vlmul=1),
            vfmv_v_f(18, 1), vfmv_v_f(20, 2),
            vop(0x04, 0b001, 26, 18, 20),
            csrrwi(0x001, 0), vsetivli(17, 2, vsew=3),
            vfmv_v_f(18, 6), vfmv_v_f(20, 7),
            vop(0x04, 0b001, 22, 18, 20),
            vop(0x06, 0b001, 24, 18, 20),
            vop(0x04, 0b101, 28, 18, 8),
            vop(0x06, 0b101, 30, 18, 9), csrrs(23, 0x001),
            0x0000006F,
        ]
        if extensions == "RV32I+F+V":
            program = [
                enc_i(LOAD_FP, 1, 0b010, 0, 0), *([nop()] * 6),
                vsetivli(17, 2, vsew=3),
                vop(0x04, 0b101, 20, 0, 1),
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
            0x00000000, 0x80000000,
        ])

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
    dut = _VFloatMinMaxBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    result = {}

    def process():
        for _ in range(1800):
            yield Tick()
        for reg in (4, 5, 6, 7, 8, 10, 12, 13, 14, 15, 16,
                    20, 22, 24, 26, 27, 28, 30):
            yield dut.core.dbg_vreg_addr.eq(reg)
            yield Tick()
            result[reg] = yield dut.core.dbg_vreg_rdata
        for reg in (20, 21, 22, 23):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield dut.core.dbg_reg_rdata

    sim.add_process(process)
    sim.run()
    return result


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_v_float_minmax_nan_zero_mask_restart_tail_and_groups(extensions):
    result = run(extensions)
    pos_one = (0x3F800000).to_bytes(4, "little")
    neg_two = (0xC0000000).to_bytes(4, "little")
    assert result[4] == int.from_bytes(neg_two * 4, "little")
    assert result[5] == int.from_bytes(pos_one * 4, "little")
    assert result[6] == int.from_bytes(pos_one * 4, "little")
    assert result[7] == int.from_bytes(pos_one * 4, "little")
    assert result[8] == int.from_bytes(pos_one * 4, "little")
    assert result[10] == int.from_bytes((0x7FC00000).to_bytes(4, "little") * 4, "little")
    assert result[12] == int.from_bytes((0x80000000).to_bytes(4, "little") * 4, "little")
    assert result[13] == 0
    assert result[14] == int.from_bytes(pos_one * 4, "little")
    assert result[15] == int.from_bytes(pos_one * 2 + neg_two * 2, "little")
    assert result[16] == int.from_bytes(neg_two * 2 + b"\xff" * 8, "little")
    assert result[26] == int.from_bytes(neg_two * 4, "little")
    assert result[27] == int.from_bytes(neg_two * 4, "little")
    pos_three = (0x4008000000000000).to_bytes(8, "little")
    neg_four = (0xC010000000000000).to_bytes(8, "little")
    assert result[22] == int.from_bytes(neg_four * 2, "little")
    assert result[24] == int.from_bytes(pos_three * 2, "little")
    assert result[28] == int.from_bytes(pos_three * 2, "little")
    assert result[30] == int.from_bytes(pos_three * 2, "little")
    assert result["x20"] == 0x10
    assert result["x21"] == 0
    assert result["x22"] == 0
    assert result["x23"] == 0x10


def test_v_float_minmax_disabled_without_v():
    assert all(value == 0 for value in run("RV32I+GC").values())


def test_v_float_minmax_sew64_requires_d():
    assert run("RV32I+F+V")[20] == 0
