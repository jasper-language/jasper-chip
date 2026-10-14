"""Executable closure for VFWREDUSUM.VS and VFWREDOSUM.VS."""

import pytest
from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.isa import LOAD_FP, OP_IMM, OP_V, SYSTEM, enc_i
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core

EXTENSIONS = ("RV32I+GC+V", "RV32I+GC+*")


def nop():
    return enc_i(OP_IMM, 0, 0, 0, 0)


def vsetivli(avl, vsew=2, vlmul=0, vta=0):
    vtype = ((vta & 1) << 6) | ((vsew & 7) << 3) | (vlmul & 7)
    return ((0b11 << 30) | (vtype << 20) | ((avl & 0x1F) << 15) |
            (0b111 << 12) | (17 << 7) | OP_V)


def vfmv_v_f(vd, fs1):
    return ((0x17 << 26) | (1 << 25) | ((fs1 & 0x1F) << 15) |
            (0b101 << 12) | ((vd & 0x1F) << 7) | OP_V)


def widen_reduce(vd, vs2, vs1, ordered=False, vm=1):
    funct6 = 0x33 if ordered else 0x31
    return ((funct6 << 26) | ((vm & 1) << 25) | ((vs2 & 0x1F) << 20) |
            ((vs1 & 0x1F) << 15) | (0b001 << 12) |
            ((vd & 0x1F) << 7) | OP_V)


def csrrwi(csr, value):
    return ((csr & 0xFFF) << 20) | ((value & 0x1F) << 15) | (0b101 << 12) | SYSTEM


def csrrs(rd, csr):
    return ((csr & 0xFFF) << 20) | (0b010 << 12) | ((rd & 0x1F) << 7) | SYSTEM


class _Bench(Elaboratable):
    def __init__(self, extensions):
        loads = []
        for freg, funct3, offset in (
            (1, 0b010, 0), (2, 0b010, 4), (3, 0b010, 8),
            (4, 0b010, 12), (5, 0b011, 16), (6, 0b011, 24),
            (7, 0b011, 32),
        ):
            loads += [enc_i(LOAD_FP, freg, funct3, 0, offset), *([nop()] * 4)]
        program = loads + [
            vsetivli(1, vsew=3), vfmv_v_f(4, 5),
            vsetivli(4), vfmv_v_f(2, 1),
            widen_reduce(6, 2, 4), widen_reduce(7, 2, 4, ordered=True),
            csrrwi(0x002, 6), widen_reduce(9, 2, 4), csrrwi(0x002, 0),
            vfmv_v_f(0, 4), widen_reduce(8, 2, 4, vm=0),
            vsetivli(1, vsew=3), vfmv_v_f(12, 6),
            vsetivli(1), vfmv_v_f(10, 2),
            csrrwi(0x001, 0), widen_reduce(14, 10, 12), csrrs(20, 0x001),
            csrrwi(0x002, 3), csrrwi(0x001, 0),
            widen_reduce(15, 10, 12, ordered=True), csrrs(21, 0x001),
            csrrwi(0x002, 0), vfmv_v_f(16, 3), csrrwi(0x001, 0),
            widen_reduce(17, 16, 12), csrrs(22, 0x001),
            vsetivli(0), widen_reduce(18, 2, 4),
            vsetivli(4, vta=1), widen_reduce(19, 2, 4),
            vsetivli(8, vlmul=1), vfmv_v_f(22, 1),
            widen_reduce(24, 22, 4),
            vsetivli(1), vfmv_v_f(26, 2),
            csrrwi(0x001, 0), widen_reduce(30, 26, 28), csrrs(23, 0x001),
            csrrwi(0x008, 1), widen_reduce(9, 2, 4),
            csrrwi(0x008, 0), vsetivli(1, vsew=3), widen_reduce(9, 2, 4),
            vsetivli(2), widen_reduce(2, 2, 4),
            0x0000006F,
        ]
        self.cycles = 220
        if extensions in ("RV32I+GC", "RV32I+F+V"):
            program = [vsetivli(2), widen_reduce(4, 2, 6), 0x0000006F]
            self.cycles = 80
        program += [nop()] * (144 - len(program))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=len(program), init=program)
        self.dmem = SimpleDMem(words=10, init=[
            0x3F800000, 0x00000001, 0x7F812345, 0x00000005,
            0x00000000, 0x40000000, 0x00000000, 0x3FF00000,
            0x00000000, 0x00000000,
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
        for reg in (2, 6, 7, 8, 14, 15, 17, 18, 19, 24, 30):
            yield dut.core.dbg_vreg_addr.eq(reg)
            yield Tick()
            result[reg] = yield dut.core.dbg_vreg_rdata
        for reg in (20, 21, 22, 23):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield dut.core.dbg_reg_rdata
        result["traps"] = traps

    sim.add_process(process)
    sim.run()
    return result


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_v_float_widening_reduction_sum_ieee_mask_tail_groups_and_illegal(extensions):
    result = run(extensions)
    assert result[6] & ((1 << 64) - 1) == 0x4018000000000000
    assert result[7] & ((1 << 64) - 1) == 0x4018000000000000
    assert result[8] & ((1 << 64) - 1) == 0x4010000000000000
    assert result[14] & ((1 << 64) - 1) == 0x3FF0000000000000
    assert result["x20"] == 0x01
    assert result[15] & ((1 << 64) - 1) == 0x3FF0000000000001
    assert result["x21"] == 0x01
    assert result[17] & ((1 << 64) - 1) == 0x7FF8000000000000
    assert result["x22"] == 0x10
    assert result[18] == 0
    assert result[19] == int.from_bytes(
        (0x4018000000000000).to_bytes(8, "little") + b"\xff" * 8,
        "little")
    assert result[24] & ((1 << 64) - 1) == 0x4024000000000000
    assert result[30] & ((1 << 64) - 1) == 0x36A0000000000000
    assert result["x23"] == 0
    assert result[2] & ((1 << 64) - 1) == 0x4010000000000000
    assert result["traps"] >= 3


def test_v_float_widening_reduction_sum_disabled_without_v():
    assert all(value == 0 for value in run("RV32I+GC").values())


def test_v_float_widening_reduction_sum_requires_d():
    assert run("RV32I+F+V")[6] == 0
