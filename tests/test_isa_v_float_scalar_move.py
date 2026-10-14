"""Executable V floating-point scalar move family closure."""

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


def vfmv(funct6, funct3, vd, vs2, rs1):
    return ((funct6 << 26) | (1 << 25) | ((vs2 & 0x1F) << 20) |
            ((rs1 & 0x1F) << 15) | (funct3 << 12) | ((vd & 0x1F) << 7) | OP_V)


def csrrwi(csr, value):
    return ((csr & 0xFFF) << 20) | ((value & 0x1F) << 15) | (0b101 << 12) | SYSTEM


def csrrs(rd, csr):
    return ((csr & 0xFFF) << 20) | (0b010 << 12) | ((rd & 0x1F) << 7) | SYSTEM


class _VFloatScalarMoveBench(Elaboratable):
    def __init__(self, extensions):
        program = [
            enc_i(LOAD_FP, 1, 0b010, 0, 0),
            *([nop()] * 4),
            enc_i(LOAD_FP, 3, 0b010, 0, 4),
            *([nop()] * 4),
            enc_i(LOAD_FP, 2, 0b011, 0, 8),
            *([nop()] * 4),
            enc_i(LOAD_FP, 5, 0b011, 0, 16),
            *([nop()] * 4),
            enc_i(LOAD_FP, 7, 0b011, 0, 24),
            *([nop()] * 6), csrrwi(0x001, 0x1F),
            vsetivli(17, 4),
            vfmv(0x17, 0b101, 4, 0, 1),
            vfmv(0x10, 0b001, 4, 4, 0),
            vfmv(0x17, 0b101, 6, 0, 1),
            vfmv(0x10, 0b101, 6, 0, 3),
            vfmv(0x17, 0b101, 8, 0, 5),
            vsetivli(17, 2, vsew=3),
            vfmv(0x17, 0b101, 10, 0, 2),
            vfmv(0x10, 0b001, 6, 10, 0),
            vfmv(0x17, 0b101, 12, 0, 2),
            vfmv(0x10, 0b101, 12, 0, 7),
            vfmv(0x17, 0b101, 14, 0, 2),
            csrrwi(0x008, 1), vfmv(0x17, 0b101, 14, 0, 7),
            vsetivli(17, 1, vsew=3, vta=1),
            vfmv(0x17, 0b101, 16, 0, 2),
            csrrs(20, 0x001),
            0x0000006F,
        ]
        if extensions == "RV32I+F+V":
            program = [
                enc_i(LOAD_FP, 1, 0b010, 0, 0),
                *([nop()] * 6),
                vsetivli(17, 2, vsew=3),
                vfmv(0x17, 0b101, 10, 0, 1),
                vfmv(0x10, 0b001, 6, 10, 0),
                0x0000006F,
            ]
        program += [nop()] * (192 - len(program))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=len(program), init=program)
        self.dmem = SimpleDMem(words=16, init=[
            0x3F800000,
            0x40000000,
            0x00000000, 0x40080000,
            0xBF800000, 0x00000000,
            0x00000000, 0xC0000000,
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
    dut = _VFloatScalarMoveBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    result = {}

    def process():
        for _ in range(1150):
            yield Tick()
        for reg in (4, 6, 8, 10, 12, 14, 16):
            yield dut.core.dbg_vreg_addr.eq(reg)
            yield Tick()
            result[f"v{reg}"] = yield dut.core.dbg_vreg_rdata
        for reg in (1, 2, 3, 4, 5, 6, 7):
            yield dut.core.dbg_freg_addr.eq(reg)
            yield Tick()
            result[f"f{reg}"] = yield dut.core.dbg_freg_rdata
        yield dut.core.dbg_reg_addr.eq(20)
        yield Tick()
        result["fflags"] = yield dut.core.dbg_reg_rdata

    sim.add_process(process)
    sim.run()
    return result


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_v_float_scalar_moves_nan_box_sew64_restart_tail_and_flags(extensions):
    result = run(extensions)
    assert result["f1"] == 0xFFFFFFFF3F800000
    assert result["f3"] == 0xFFFFFFFF40000000
    assert result["f2"] == 0x4008000000000000
    assert result["f5"] == 0x00000000BF800000
    assert result["f7"] == 0xC000000000000000
    assert result["v4"] == int.from_bytes((0x3F800000).to_bytes(4, "little") * 4, "little")
    assert result["f4"] == 0xFFFFFFFF3F800000
    assert result["v6"] == int.from_bytes(
        (0x40000000).to_bytes(4, "little") +
        (0x3F800000).to_bytes(4, "little") * 3, "little")
    assert result["v8"] == int.from_bytes((0x7FC00000).to_bytes(4, "little") * 4, "little")
    assert result["v10"] == int.from_bytes((0x4008000000000000).to_bytes(8, "little") * 2,
                                           "little")
    assert result["f6"] == 0x4008000000000000
    assert result["v12"] == int.from_bytes(
        (0xC000000000000000).to_bytes(8, "little") +
        (0x4008000000000000).to_bytes(8, "little"), "little")
    assert result["v14"] == int.from_bytes(
        (0x4008000000000000).to_bytes(8, "little") +
        (0xC000000000000000).to_bytes(8, "little"), "little")
    assert result["v16"] == int.from_bytes(
        (0x4008000000000000).to_bytes(8, "little") + b"\xff" * 8, "little")
    assert result["fflags"] == 0x1F


def test_v_float_scalar_moves_disabled_without_v():
    result = run("RV32I+GC")
    protected = [key for key in result if key.startswith("v") or
                 key in ("f4", "f6", "fflags")]
    expected = {key: 0 for key in protected}
    expected["fflags"] = 0x1F
    assert {key: result[key] for key in protected} == expected


def test_v_float_scalar_moves_sew64_requires_d():
    result = run("RV32I+F+V")
    assert result["v10"] == 0
    assert result["f6"] == 0
