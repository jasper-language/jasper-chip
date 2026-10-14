"""Executable V floating min/max reduction closure."""

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


def reduce(vd, vs2, vs1, funct6, vm=1):
    return ((funct6 << 26) | ((vm & 1) << 25) | ((vs2 & 0x1F) << 20) |
            ((vs1 & 0x1F) << 15) | (0b001 << 12) | ((vd & 0x1F) << 7) | OP_V)


def csrrwi(csr, value):
    return ((csr & 0xFFF) << 20) | ((value & 0x1F) << 15) | (0b101 << 12) | SYSTEM


def csrrs(rd, csr):
    return ((csr & 0xFFF) << 20) | (0b010 << 12) | ((rd & 0x1F) << 7) | SYSTEM


class _Bench(Elaboratable):
    def __init__(self, extensions):
        loads = []
        for freg, funct3, offset in (
            (1, 0b010, 0), (2, 0b010, 4), (3, 0b010, 8),
            (4, 0b010, 12), (5, 0b010, 16), (6, 0b010, 20),
            (7, 0b010, 24), (8, 0b010, 28),
            (9, 0b011, 32), (10, 0b011, 40),
        ):
            loads += [enc_i(LOAD_FP, freg, funct3, 0, offset), *([nop()] * 4)]
        program = loads + [
            vsetivli(8, vlmul=1),
            vfmv_v_f(2, 2), vfmv_v_f(4, 3),
            reduce(6, 2, 4, 0x05), reduce(7, 2, 4, 0x07),
            vfmv_v_f(0, 8), nop(), nop(), reduce(8, 2, 4, 0x05, vm=0),
            vsetivli(4), vfmv_v_f(10, 4),
            csrrwi(0x001, 0), reduce(11, 10, 4, 0x05), csrrs(20, 0x001),
            vfmv_v_f(12, 5), csrrwi(0x001, 0),
            reduce(13, 10, 12, 0x05), csrrs(21, 0x001),
            vfmv_v_f(14, 6), vfmv_v_f(15, 7),
            reduce(16, 15, 14, 0x05), reduce(17, 15, 14, 0x07),
            vsetivli(0), csrrwi(0x001, 0),
            reduce(18, 10, 4, 0x05), csrrs(22, 0x001),
            vsetivli(4, vta=1), reduce(19, 2, 4, 0x05),
            csrrwi(0x008, 1), reduce(20, 2, 4, 0x05),
            csrrwi(0x008, 0), vsetivli(2, vsew=3),
            vfmv_v_f(22, 9), vfmv_v_f(24, 10),
            reduce(26, 22, 24, 0x05), reduce(27, 22, 24, 0x07),
            0x0000006F,
        ]
        if extensions == "RV32I+F+V":
            program = [vsetivli(2, vsew=3), reduce(20, 0, 2, 0x05), 0x0000006F]
        program += [nop()] * (192 - len(program))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=len(program), init=program)
        self.dmem = SimpleDMem(words=16, init=[
            0x3F800000, 0xC0000000, 0x40400000, 0x7F812345,
            0x7FC12345, 0x00000000, 0x80000000, 0x0000000F,
            0x00000000, 0xC0000000, 0x00000000, 0x40080000,
            0, 0, 0, 0,
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
        for _ in range(260):
            traps += (yield dut.core.trap)
            yield Tick()
        for reg in (6, 7, 8, 11, 13, 16, 17, 18, 19, 20, 26, 27):
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
def test_v_float_reduction_minmax_nan_zero_mask_tail_and_groups(extensions):
    result = run(extensions)
    assert result[6] & 0xFFFFFFFF == 0xC0000000
    assert result[7] & 0xFFFFFFFF == 0x40400000
    assert result[8] & 0xFFFFFFFF == 0xC0000000
    assert result[11] & 0xFFFFFFFF == 0x40400000
    assert result["x20"] == 0x10
    assert result[13] & 0xFFFFFFFF == 0x7FC00000
    assert result["x21"] == 0x10
    assert result[16] & 0xFFFFFFFF == 0x80000000
    assert result[17] & 0xFFFFFFFF == 0
    assert result[18] == 0
    assert result["x22"] == 0
    assert result[19] == int.from_bytes((0xC0000000).to_bytes(4, "little") + b"\xff" * 12, "little")
    assert result[20] == 0
    assert result[26] & 0xFFFFFFFFFFFFFFFF == 0xC000000000000000
    assert result[27] & 0xFFFFFFFFFFFFFFFF == 0x4008000000000000
    assert result["traps"] > 0


def test_v_float_reduction_minmax_disabled_without_v():
    assert all(value == 0 for value in run("RV32I+GC").values())


def test_v_float_reduction_minmax_sew64_requires_d():
    assert run("RV32I+F+V")[20] == 0
