"""Executable V floating multiply family closure."""

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


def vop(vd, vs2, operand, funct3=0b001, vm=1):
    return ((0x24 << 26) | ((vm & 1) << 25) | ((vs2 & 0x1F) << 20) |
            ((operand & 0x1F) << 15) | (funct3 << 12) | ((vd & 0x1F) << 7) | OP_V)


def vfmv_v_f(vd, fs1):
    return ((0x17 << 26) | (1 << 25) | ((fs1 & 0x1F) << 15) |
            (0b101 << 12) | ((vd & 0x1F) << 7) | OP_V)


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
            (9, 0b011, 32), (10, 0b011, 40), (11, 0b010, 48),
        ):
            loads += [enc_i(LOAD_FP, freg, funct3, 0, offset), *([nop()] * 4)]
        program = loads + [
            vsetivli(4), vfmv_v_f(1, 1), vfmv_v_f(2, 2),
            vop(4, 1, 2), vop(5, 1, 2, funct3=0b101),
            csrrwi(0x001, 0), vop(6, 1, 3, funct3=0b101), csrrs(20, 0x001),
            csrrwi(0x001, 0), vfmv_v_f(3, 5),
            vop(7, 3, 4, funct3=0b101), csrrs(21, 0x001),
            vfmv_v_f(0, 7), nop(), nop(), vop(8, 1, 2, vm=0),
            csrrwi(0x008, 2), vop(9, 1, 2),
            vsetivli(2, vta=1), vop(10, 1, 2),
            vsetivli(8, vlmul=1), vfmv_v_f(12, 1), vfmv_v_f(14, 2),
            vop(16, 12, 14),
            csrrwi(0x001, 0), vsetivli(2, vsew=3),
            vfmv_v_f(18, 9), vfmv_v_f(20, 10),
            vop(22, 18, 20), csrrs(22, 0x001),
            vsetivli(4), vfmv_v_f(26, 6), csrrwi(0x001, 0),
            vop(26, 26, 2, funct3=0b101), csrrs(23, 0x001),
            vfmv_v_f(28, 11), csrrwi(0x001, 0),
            vop(28, 28, 8, funct3=0b101), csrrs(24, 0x001),
            csrrwi(0x002, 6), vop(30, 1, 2),
            0x0000006F,
        ]
        if extensions == "RV32I+F+V":
            program = [vsetivli(2, vsew=3), vop(20, 0, 2), 0x0000006F]
        program += [nop()] * (224 - len(program))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=len(program), init=program)
        self.dmem = SimpleDMem(words=16, init=[
            0x3FC00000, 0x40000000, 0x7F812345, 0x7F800000,
            0x00000000, 0x7F7FFFFF, 0x00000003, 0x3F000000,
            0x00000000, 0x3FF80000, 0x00000000, 0x40000000,
            0x00800000, 0, 0, 0,
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
        for _ in range(800):
            traps += (yield dut.core.trap)
            yield Tick()
        for reg in (4, 5, 6, 7, 8, 9, 10, 16, 17, 20, 22, 26, 28, 30):
            yield dut.core.dbg_vreg_addr.eq(reg)
            yield Tick()
            result[reg] = yield dut.core.dbg_vreg_rdata
        for reg in (20, 21, 22, 23, 24):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield dut.core.dbg_reg_rdata
        result["traps"] = traps

    sim.add_process(process)
    sim.run()
    return result


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_v_float_multiply_ieee_mask_restart_tail_and_groups(extensions):
    result = run(extensions)
    f3 = (0x40400000).to_bytes(4, "little")
    assert result[4] == int.from_bytes(f3 * 4, "little")
    assert result[5] == int.from_bytes(f3 * 4, "little")
    assert result[6] == int.from_bytes((0x7FC00000).to_bytes(4, "little") * 4, "little")
    assert result[7] == int.from_bytes((0x7FC00000).to_bytes(4, "little") * 4, "little")
    assert result["x20"] == 0x10
    assert result["x21"] == 0x10
    assert result[8] == int.from_bytes(f3 * 2 + b"\x00" * 8, "little")
    assert result[9] == int.from_bytes(b"\x00" * 8 + f3 * 2, "little")
    assert result[10] == int.from_bytes(f3 * 2 + b"\xff" * 8, "little")
    assert result[16] == int.from_bytes(f3 * 4, "little")
    assert result[17] == int.from_bytes(f3 * 4, "little")
    d3 = (0x4008000000000000).to_bytes(8, "little")
    assert result[22] == int.from_bytes(d3 * 2, "little")
    assert result["x22"] == 0
    assert result[26] == int.from_bytes((0x7F800000).to_bytes(4, "little") * 4, "little")
    assert result["x23"] == 0x5
    assert result[28] == int.from_bytes((0x00400000).to_bytes(4, "little") * 4, "little")
    assert result["x24"] == 0
    assert result[30] == 0
    assert result["traps"] > 0


def test_v_float_multiply_disabled_without_v():
    assert all(value == 0 for value in run("RV32I+GC").values())


def test_v_float_multiply_sew64_requires_d():
    assert run("RV32I+F+V")[20] == 0
