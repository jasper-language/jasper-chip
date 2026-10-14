"""Executable V floating merge closure."""

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


def vfmerge(vd, vs2, fs1):
    return vop(0x17, 0b101, vd, vs2, fs1, vm=0)


def vmv_s_x(vd, rs1):
    return vop(0x10, 0b110, vd, 0, rs1)


def csrrwi(csr, value):
    return ((csr & 0xFFF) << 20) | ((value & 0x1F) << 15) | (0b101 << 12) | SYSTEM


def csrrs(rd, csr):
    return ((csr & 0xFFF) << 20) | (0b010 << 12) | ((rd & 0x1F) << 7) | SYSTEM


class _VFloatMergeBench(Elaboratable):
    def __init__(self, extensions):
        program = [
            enc_i(LOAD_FP, 1, 0b010, 0, 0), *([nop()] * 4),
            enc_i(LOAD_FP, 2, 0b010, 0, 4), *([nop()] * 4),
            enc_i(LOAD_FP, 3, 0b011, 0, 8), *([nop()] * 4),
            enc_i(LOAD_FP, 4, 0b011, 0, 16), *([nop()] * 4),
            enc_i(LOAD_FP, 5, 0b011, 0, 24), *([nop()] * 6),
            csrrwi(0x001, 0x1F), vsetivli(17, 4),
            vfmv_v_f(1, 1),
            enc_i(OP_IMM, 3, 0, 0, 5), vmv_s_x(0, 3),
            vfmerge(4, 1, 2),
            vfmerge(5, 1, 3),
            vfmv_v_f(8, 1), vfmerge(8, 8, 2),
            enc_i(OP_IMM, 3, 0, 0, 15), vmv_s_x(0, 3),
            vfmv_v_f(6, 1), csrrwi(0x008, 2), vfmerge(6, 1, 2),
            vsetivli(17, 2, vta=1), vfmerge(7, 1, 2),
            vsetivli(17, 8, vlmul=1), vfmv_v_f(18, 1),
            enc_i(OP_IMM, 3, 0, 0, 0xAA), vmv_s_x(0, 3),
            vfmerge(26, 18, 2),
            vsetivli(17, 2, vsew=3), vfmv_v_f(18, 4),
            enc_i(OP_IMM, 3, 0, 0, 1), vmv_s_x(0, 3),
            vfmerge(20, 18, 5),
            csrrs(20, 0x001),
            0x0000006F,
        ]
        if extensions == "RV32I+F+V":
            program = [
                enc_i(LOAD_FP, 1, 0b010, 0, 0), *([nop()] * 6),
                vsetivli(17, 2, vsew=3),
                enc_i(OP_IMM, 3, 0, 0, 3), vmv_s_x(0, 3),
                vfmerge(20, 0, 1),
                0x0000006F,
            ]
        program += [nop()] * (224 - len(program))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=len(program), init=program)
        self.dmem = SimpleDMem(words=16, init=[
            0x3F800000, 0xC0000000,
            0xBF800000, 0x00000000,
            0x00000000, 0x40080000,
            0x00000000, 0xC0100000,
        ] + [0] * 8)

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
    dut = _VFloatMergeBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    result = {}

    def process():
        for _ in range(1500):
            yield Tick()
        for reg in (4, 5, 6, 7, 8, 20, 26, 27):
            yield dut.core.dbg_vreg_addr.eq(reg)
            yield Tick()
            result[reg] = yield dut.core.dbg_vreg_rdata
        yield dut.core.dbg_reg_addr.eq(20)
        yield Tick()
        result["fflags"] = yield dut.core.dbg_reg_rdata

    sim.add_process(process)
    sim.run()
    return result


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_v_float_merge_mask_nan_box_restart_tail_overlap_and_groups(extensions):
    result = run(extensions)
    pos_one = (0x3F800000).to_bytes(4, "little")
    neg_two = (0xC0000000).to_bytes(4, "little")
    canonical_nan = (0x7FC00000).to_bytes(4, "little")
    selected = int.from_bytes(neg_two + pos_one + neg_two + pos_one, "little")
    assert result[4] == selected
    assert result[5] == int.from_bytes(
        canonical_nan + pos_one + canonical_nan + pos_one, "little")
    assert result[8] == selected
    assert result[6] == int.from_bytes(pos_one * 2 + neg_two * 2, "little")
    assert result[7] == int.from_bytes(neg_two * 2 + b"\xff" * 8, "little")
    assert result[26] == int.from_bytes(pos_one + neg_two + pos_one + neg_two, "little")
    assert result[27] == int.from_bytes(pos_one + neg_two + pos_one + neg_two, "little")
    neg_four = (0xC010000000000000).to_bytes(8, "little")
    pos_three = (0x4008000000000000).to_bytes(8, "little")
    assert result[20] == int.from_bytes(neg_four + pos_three, "little")
    assert result["fflags"] == 0x1F


def test_v_float_merge_disabled_without_v():
    result = run("RV32I+GC")
    assert all(value == 0 for key, value in result.items() if key != "fflags")
    assert result["fflags"] == 0x1F


def test_v_float_merge_sew64_requires_d():
    assert run("RV32I+F+V")[20] == 0
