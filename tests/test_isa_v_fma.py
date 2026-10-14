"""Executable V fused and widening floating-point family closure."""

import struct

import pytest
from amaranth import Elaboratable, Module

from rtl.isa import LOAD_FP, OP_IMM, OP_V, enc_i
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core
from sim.v_batch import run_v_program


def nop():
    return enc_i(OP_IMM, 0, 0, 0, 0)


def vsetivli(avl, vsew=2, vlmul=0):
    vtype = ((vsew & 7) << 3) | (vlmul & 7)
    return ((0b11 << 30) | (vtype << 20) | ((avl & 0x1F) << 15) |
            (0b111 << 12) | (17 << 7) | OP_V)


def vop(funct6, vd, vs2, vs1, funct3=0b001, vm=1):
    return ((funct6 << 26) | ((vm & 1) << 25) | ((vs2 & 0x1F) << 20) |
            ((vs1 & 0x1F) << 15) | (funct3 << 12) |
            ((vd & 0x1F) << 7) | OP_V)


def vfmv_v_f(vd, fs1):
    return vop(0x17, vd, 0, fs1, funct3=0b101)


class _Bench(Elaboratable):
    def __init__(self, extensions):
        program = [
            enc_i(LOAD_FP, 1, 0b010, 0, 0), *([nop()] * 4),
            enc_i(LOAD_FP, 2, 0b010, 0, 4), *([nop()] * 4),
            enc_i(LOAD_FP, 3, 0b010, 0, 8), *([nop()] * 6),
            vsetivli(4),
            vfmv_v_f(1, 1), vfmv_v_f(2, 2),
            vfmv_v_f(4, 1), vfmv_v_f(5, 1),
            vfmv_v_f(6, 1), vfmv_v_f(7, 1),
            vfmv_v_f(8, 3), vfmv_v_f(9, 3),
            vfmv_v_f(10, 3), vfmv_v_f(11, 3),
            vop(0x28, 4, 2, 1), vop(0x29, 5, 2, 1),
            vop(0x2A, 6, 2, 1), vop(0x2B, 7, 2, 1),
            vop(0x2C, 8, 2, 1), vop(0x2D, 9, 2, 1),
            vop(0x2E, 10, 2, 1), vop(0x2F, 11, 2, 1),
            vop(0x38, 12, 2, 1),
            vop(0x30, 14, 2, 1),
            vop(0x32, 16, 2, 1),
            vop(0x34, 18, 14, 1),
            vop(0x36, 20, 14, 1),
            vop(0x30, 22, 2, 1), vop(0x3C, 22, 2, 1),
            vop(0x30, 24, 2, 1), vop(0x3D, 24, 2, 1),
            vop(0x30, 26, 2, 1), vop(0x3E, 26, 2, 1),
            vop(0x30, 28, 2, 1), vop(0x3F, 28, 2, 1),
            0x0000006F,
        ]
        program += [nop()] * (192 - len(program))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=len(program), init=program)
        self.dmem = SimpleDMem(words=8, init=[
            0x40000000, 0x40400000, 0x40A00000,
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
            c.dmem_rdata.eq(dm.rsp_rdata), c.dmem_error.eq(0),
            c.gc_enq_ready.eq(1), c.gc_rsp_valid.eq(0), c.gc_rsp_tag.eq(0),
            c.gc_rsp_rd.eq(0), c.gc_rsp_data.eq(0), c.wb_enq_ready.eq(1),
            c.mv_cmd_ready.eq(1), c.mv_rsp_valid.eq(0), c.mv_rsp_tag.eq(0),
            c.mv_rsp_rd.eq(0), c.mv_rsp_data.eq(0),
        ]
        return m


def run(extensions):
    dut = _Bench(extensions)
    return run_v_program(
        extensions, dut.imem.init, dut.dmem.init, 800,
        vregs=range(4, 30), v_units=("vffma",),
    )


def f32x4(value):
    lane = struct.pack("<f", value)
    return int.from_bytes(lane * 4, "little")


def f64x4(value):
    lane = struct.pack("<d", value)
    data = lane * 4
    return (int.from_bytes(data[:16], "little"),
            int.from_bytes(data[16:], "little"))


@pytest.mark.parametrize("extensions", ("RV32I+GC+V", "RV32I+GC+*"))
def test_v_fma_and_widening_families(extensions):
    result = run(extensions)
    for reg, value in zip(range(4, 12), (7.0, -7.0, 1.0, -1.0,
                                        11.0, -11.0, 1.0, -1.0)):
        assert result[reg] == f32x4(value)

    wide = {
        12: 6.0,
        14: 5.0,
        16: 1.0,
        18: 7.0,
        20: 3.0,
        22: 11.0,
        24: -11.0,
        26: 1.0,
        28: -1.0,
    }
    for reg, value in wide.items():
        low, high = f64x4(value)
        assert result[reg] == low
        assert result[reg + 1] == high
    assert result["flags"] == 0
    assert result["traps"] == 0
