"""Executable closure for VFWCVT.F.F.V."""

import pytest
from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.isa import LOAD_FP, OP_IMM, OP_V, SYSTEM, enc_i
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core

EXTENSIONS = ("RV32I+GC+V", "RV32I+GC+*")


def nop():
    return enc_i(OP_IMM, 0, 0, 0, 0)


def vsetivli(avl, vsew=2, vlmul=0, vta=0, vma=0):
    vtype = ((vma & 1) << 7) | ((vta & 1) << 6) | ((vsew & 7) << 3) | (vlmul & 7)
    return ((0b11 << 30) | (vtype << 20) | ((avl & 0x1F) << 15) |
            (0b111 << 12) | (17 << 7) | OP_V)


def vop(funct6, funct3, vd, vs2, operand, vm=1):
    return ((funct6 << 26) | ((vm & 1) << 25) | ((vs2 & 0x1F) << 20) |
            ((operand & 0x1F) << 15) | (funct3 << 12) | ((vd & 0x1F) << 7) | OP_V)


def vfmv_v_f(vd, fs1):
    return vop(0x17, 0b101, vd, 0, fs1)


def vfwcvt_f_f(vd, vs2, vm=1):
    return vop(0x12, 0b001, vd, vs2, 0x0C, vm)


def csrrwi(csr, value):
    return ((csr & 0xFFF) << 20) | ((value & 0x1F) << 15) | (0b101 << 12) | SYSTEM


def csrrs(rd, csr):
    return ((csr & 0xFFF) << 20) | (0b010 << 12) | ((rd & 0x1F) << 7) | SYSTEM


class _Bench(Elaboratable):
    def __init__(self, extensions):
        loads = []
        for freg, offset in ((1, 0), (2, 4), (3, 8), (4, 12),
                             (5, 16), (6, 20), (7, 24)):
            loads += [enc_i(LOAD_FP, freg, 0b010, 0, offset), *([nop()] * 4)]
        program = loads + [
            vsetivli(4), vfmv_v_f(2, 1), vfwcvt_f_f(4, 2),
            vfmv_v_f(6, 2), vfwcvt_f_f(8, 6),
            vfmv_v_f(10, 3), vfwcvt_f_f(12, 10),
            vfmv_v_f(14, 4), vfwcvt_f_f(16, 14),
            csrrwi(0x001, 0), vfmv_v_f(18, 5),
            vfwcvt_f_f(20, 18), csrrs(20, 0x001),
            csrrwi(0x001, 0), vfmv_v_f(22, 6),
            vfwcvt_f_f(24, 22), csrrs(21, 0x001),
            vfmv_v_f(0, 7), vsetivli(4, vma=1), csrrwi(0x001, 0),
            vfwcvt_f_f(26, 18, vm=0), csrrs(22, 0x001),
            vsetivli(4), vfmv_v_f(29, 1), vfwcvt_f_f(28, 29),
            csrrwi(0x008, 2), vfwcvt_f_f(6, 2), csrrwi(0x008, 0),
            vsetivli(3, vta=1), vfwcvt_f_f(6, 2),
            vsetivli(2), vfwcvt_f_f(2, 2),
            vsetivli(2, vlmul=3), vfwcvt_f_f(4, 8),
            vsetivli(2, vsew=3), vfwcvt_f_f(4, 8),
            csrrwi(0x002, 6), vsetivli(2), vfwcvt_f_f(4, 8),
            0x0000006F,
        ]
        self.cycles = 300
        if extensions in ("RV32I+GC", "RV32I+F+V"):
            program = [vsetivli(2), vfwcvt_f_f(4, 2), 0x0000006F]
            self.cycles = 80
        program += [nop()] * (192 - len(program))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=len(program), init=program)
        self.dmem = SimpleDMem(words=8, init=[
            0x3F800000, 0x80000000, 0x00000001, 0x7F800000,
            0x7F812345, 0x7FC12345, 0x00000005, 0,
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
    dut = _Bench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    result = {}

    def process():
        traps = 0
        for _ in range(dut.cycles):
            traps += (yield dut.core.trap)
            yield Tick()
        for reg in (4, 5, 8, 12, 16, 20, 24, 26, 27, 28, 29, 6, 7):
            yield dut.core.dbg_vreg_addr.eq(reg)
            yield Tick()
            result[reg] = yield dut.core.dbg_vreg_rdata
        for reg in (20, 21, 22):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield dut.core.dbg_reg_rdata
        result["traps"] = traps

    sim.add_process(process)
    sim.run()
    return result


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_vfwcvt_f_f_ieee_mask_tail_restart_overlap_and_illegal(extensions):
    result = run(extensions)
    one = (0x3FF0000000000000).to_bytes(8, "little")
    assert result[4] == int.from_bytes(one * 2, "little")
    assert result[5] == int.from_bytes(one * 2, "little")
    assert result[8] == int.from_bytes((0x8000000000000000).to_bytes(8, "little") * 2, "little")
    assert result[12] == int.from_bytes((0x36A0000000000000).to_bytes(8, "little") * 2, "little")
    assert result[16] == int.from_bytes((0x7FF0000000000000).to_bytes(8, "little") * 2, "little")
    qnan = (0x7FF8000000000000).to_bytes(8, "little")
    assert result[20] == int.from_bytes(qnan * 2, "little")
    assert result[24] == int.from_bytes(qnan * 2, "little")
    assert result[26] == int.from_bytes(qnan + b"\xff" * 8, "little")
    assert result[27] == int.from_bytes(qnan + b"\xff" * 8, "little")
    assert result[28] == int.from_bytes(one * 2, "little")
    assert result[29] == int.from_bytes(one * 2, "little")
    assert result[6] == int.from_bytes(one * 2, "little")
    assert result[7] == int.from_bytes(one + b"\xff" * 8, "little")
    assert result["x20"] == 0x10
    assert result["x21"] == 0
    assert result["x22"] == 0x10
    assert result["traps"] >= 4


def test_vfwcvt_f_f_disabled_without_v():
    assert all(value == 0 for value in run("RV32I+GC").values())


def test_vfwcvt_f_f_requires_d():
    assert run("RV32I+F+V")[4] == 0
