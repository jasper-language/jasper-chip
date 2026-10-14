"""Executable V floating slide-one family closure."""

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


def vfslide1(vd, vs2, fs1, down=False, vm=1):
    return vop(0x0F if down else 0x0E, 0b101, vd, vs2, fs1, vm)


def vmv_s_x(vd, rs1):
    return vop(0x10, 0b110, vd, 0, rs1)


def csrrwi(csr, value):
    return ((csr & 0xFFF) << 20) | ((value & 0x1F) << 15) | (0b101 << 12) | SYSTEM


def csrrs(rd, csr):
    return ((csr & 0xFFF) << 20) | (0b010 << 12) | ((rd & 0x1F) << 7) | SYSTEM


class _VFloatSlide1Bench(Elaboratable):
    def __init__(self, extensions):
        program = [
            enc_i(LOAD_FP, 1, 0b010, 0, 0), *([nop()] * 4),
            enc_i(LOAD_FP, 2, 0b010, 0, 4), *([nop()] * 4),
            enc_i(LOAD_FP, 3, 0b010, 0, 8), *([nop()] * 4),
            enc_i(LOAD_FP, 4, 0b011, 0, 12), *([nop()] * 4),
            enc_i(LOAD_FP, 5, 0b011, 0, 20), *([nop()] * 4),
            enc_i(LOAD_FP, 6, 0b011, 0, 28), *([nop()] * 4),
            enc_i(LOAD_FP, 7, 0b011, 0, 36), *([nop()] * 6),
            csrrwi(0x001, 0x1F), vsetivli(17, 4),
            vfmv_v_f(2, 1),
            enc_i(OP_IMM, 3, 0, 0, 0xA), vmv_s_x(0, 3), vfmerge(2, 2, 2),
            vfslide1(4, 2, 3), vfslide1(5, 2, 3, down=True),
            vfmv_v_f(6, 1), vfmv_v_f(7, 1),
            enc_i(OP_IMM, 3, 0, 0, 5), vmv_s_x(0, 3),
            vfslide1(6, 2, 3, vm=0), vfslide1(7, 2, 3, down=True, vm=0),
            enc_i(OP_IMM, 3, 0, 0, 15), vmv_s_x(0, 3),
            vfslide1(8, 2, 4), vfslide1(9, 2, 4, down=True),
            vfmv_v_f(10, 1), csrrwi(0x008, 2), vfslide1(10, 2, 3),
            vsetivli(17, 2, vta=1), vfslide1(11, 2, 3),
            vsetivli(17, 4), vfmv_v_f(12, 1),
            enc_i(OP_IMM, 3, 0, 0, 0xA), vmv_s_x(0, 3), vfmerge(12, 12, 2),
            vfslide1(12, 12, 3, down=True),
            vsetivli(17, 8, vlmul=1), vfmv_v_f(18, 1),
            enc_i(OP_IMM, 3, 0, 0, 0xAA), vmv_s_x(0, 3), vfmerge(18, 18, 2),
            enc_i(OP_IMM, 3, 0, 0, 0xFF), vmv_s_x(0, 3),
            vfslide1(26, 18, 3), vfslide1(28, 18, 3, down=True),
            vsetivli(17, 2, vsew=3), vfmv_v_f(18, 5),
            enc_i(OP_IMM, 3, 0, 0, 2), vmv_s_x(0, 3), vfmerge(18, 18, 6),
            enc_i(OP_IMM, 3, 0, 0, 3), vmv_s_x(0, 3),
            vfslide1(20, 18, 7), vfslide1(22, 18, 7, down=True),
            csrrs(20, 0x001),
            0x0000006F,
        ]
        if extensions == "RV32I+F+V":
            program = [
                enc_i(LOAD_FP, 1, 0b010, 0, 0), *([nop()] * 6),
                vsetivli(17, 2, vsew=3), vfslide1(20, 0, 1),
                0x0000006F,
            ]
        program += [nop()] * (256 - len(program))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=len(program), init=program)
        self.dmem = SimpleDMem(words=16, init=[
            0x3F800000, 0xC0000000, 0x40400000,
            0xBF800000, 0x00000000,
            0x00000000, 0x40080000,
            0x00000000, 0xC0100000,
            0x00000000, 0x40140000,
        ] + [0] * 5)

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
    dut = _VFloatSlide1Bench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    result = {}

    def process():
        for _ in range(1800):
            yield Tick()
        for reg in (4, 5, 6, 7, 8, 9, 10, 11, 12,
                    20, 22, 26, 27, 28, 29):
            yield dut.core.dbg_vreg_addr.eq(reg)
            yield Tick()
            result[reg] = yield dut.core.dbg_vreg_rdata
        yield dut.core.dbg_reg_addr.eq(20)
        yield Tick()
        result["fflags"] = yield dut.core.dbg_reg_rdata

    sim.add_process(process)
    sim.run()
    return result


def packed32(*values):
    return int.from_bytes(b"".join(value.to_bytes(4, "little") for value in values), "little")


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_v_float_slide1_mask_nan_box_restart_tail_overlap_and_groups(extensions):
    result = run(extensions)
    p1, n2, p3, qn = 0x3F800000, 0xC0000000, 0x40400000, 0x7FC00000
    assert result[4] == packed32(p3, p1, n2, p1)
    assert result[5] == packed32(n2, p1, n2, p3)
    assert result[6] == packed32(p3, p1, n2, p1)
    assert result[7] == packed32(n2, p1, n2, p1)
    assert result[8] == packed32(qn, p1, n2, p1)
    assert result[9] == packed32(n2, p1, n2, qn)
    assert result[10] == packed32(p1, p1, n2, p1)
    assert result[11] == int.from_bytes(packed32(p3, p1).to_bytes(8, "little") + b"\xff" * 8,
                                         "little")
    assert result[12] == packed32(n2, p1, n2, p3)
    assert result[26] == packed32(p3, p1, n2, p1)
    assert result[27] == packed32(n2, p1, n2, p1)
    assert result[28] == packed32(n2, p1, n2, p1)
    assert result[29] == packed32(n2, p1, n2, p3)
    p5d = (0x4014000000000000).to_bytes(8, "little")
    p3d = (0x4008000000000000).to_bytes(8, "little")
    n4d = (0xC010000000000000).to_bytes(8, "little")
    assert result[20] == int.from_bytes(p5d + p3d, "little")
    assert result[22] == int.from_bytes(n4d + p5d, "little")
    assert result["fflags"] == 0x1F


def test_v_float_slide1_disabled_without_v():
    result = run("RV32I+GC")
    assert all(value == 0 for key, value in result.items() if key != "fflags")
    assert result["fflags"] == 0x1F


def test_v_float_slide1_sew64_requires_d():
    assert run("RV32I+F+V")[20] == 0
