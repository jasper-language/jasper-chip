"""Executable V floating classification closure."""

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


def vfclass(vd, vs2, vm=1):
    return vop(0x13, 0b001, vd, vs2, 0b10000, vm)


def vmv_s_x(vd, rs1):
    return vop(0x10, 0b110, vd, 0, rs1)


def csrrwi(csr, value):
    return ((csr & 0xFFF) << 20) | ((value & 0x1F) << 15) | (0b101 << 12) | SYSTEM


def csrrs(rd, csr):
    return ((csr & 0xFFF) << 20) | (0b010 << 12) | ((rd & 0x1F) << 7) | SYSTEM


class _VFloatClassifyBench(Elaboratable):
    def __init__(self, extensions):
        program = []
        for freg, offset in enumerate(range(0, 40, 4), start=1):
            program += [enc_i(LOAD_FP, freg, 0b010, 0, offset), *([nop()] * 4)]
        for freg, offset in ((11, 40), (12, 48), (13, 56)):
            program += [enc_i(LOAD_FP, freg, 0b011, 0, offset), *([nop()] * 4)]
        program += [csrrwi(0x001, 0x1F), vsetivli(17, 4)]
        for freg, vd in zip(range(1, 11), range(4, 14)):
            program += [vfmv_v_f(1, freg), vfclass(vd, 1)]
        program += [
            vfmv_v_f(1, 7), vfclass(14, 1),
            enc_i(OP_IMM, 3, 0, 0, 5), vmv_s_x(0, 3),
            vfmv_v_f(2, 10), vfclass(14, 2, vm=0),
            vfmv_v_f(1, 7), vfclass(15, 1),
            vfmv_v_f(2, 10), csrrwi(0x008, 2), vfclass(15, 2),
            vsetivli(17, 2, vta=1), vfclass(16, 2),
            vsetivli(17, 8, vlmul=1), vfmv_v_f(18, 10), vfclass(26, 18),
            vsetivli(17, 2, vsew=3),
            vfmv_v_f(18, 11), vfclass(20, 18),
            vfmv_v_f(22, 12), vfclass(24, 22),
            vfmv_v_f(30, 13), vfclass(28, 30),
            csrrs(20, 0x001),
            0x0000006F,
        ]
        if extensions == "RV32I+F+V":
            program = [
                enc_i(LOAD_FP, 1, 0b010, 0, 0), *([nop()] * 6),
                vsetivli(17, 2, vsew=3), vfclass(20, 0),
                0x0000006F,
            ]
        program += [nop()] * (256 - len(program))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=len(program), init=program)
        self.dmem = SimpleDMem(words=16, init=[
            0xFF800000, 0xBF800000, 0x80000001, 0x80000000,
            0x00000000, 0x00000001, 0x3F800000, 0x7F800000,
            0x7F812345, 0x7FC12345,
            0x00000000, 0x40080000,
            0x00000001, 0x7FF80000,
            0x00000001, 0x7FF00000,
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
    dut = _VFloatClassifyBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    result = {}

    def process():
        for _ in range(1800):
            yield Tick()
        for reg in range(4, 17):
            yield dut.core.dbg_vreg_addr.eq(reg)
            yield Tick()
            result[reg] = yield dut.core.dbg_vreg_rdata
        for reg in (20, 24, 26, 27, 28):
            yield dut.core.dbg_vreg_addr.eq(reg)
            yield Tick()
            result[reg] = yield dut.core.dbg_vreg_rdata
        yield dut.core.dbg_reg_addr.eq(20)
        yield Tick()
        result["fflags"] = yield dut.core.dbg_reg_rdata

    sim.add_process(process)
    sim.run()
    return result


def repeated(value, width, count):
    return int.from_bytes(value.to_bytes(width // 8, "little") * count, "little")


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_v_float_classify_all_classes_mask_restart_tail_and_groups(extensions):
    result = run(extensions)
    for reg, class_bit in zip(range(4, 14), range(10)):
        assert result[reg] == repeated(1 << class_bit, 32, 4)
    assert result[14] == int.from_bytes(
        (0x200).to_bytes(4, "little") + (0x40).to_bytes(4, "little") +
        (0x200).to_bytes(4, "little") + (0x40).to_bytes(4, "little"),
        "little")
    assert result[15] == int.from_bytes(
        (0x40).to_bytes(4, "little") * 2 + (0x200).to_bytes(4, "little") * 2,
        "little")
    assert result[16] == int.from_bytes((0x200).to_bytes(4, "little") * 2 + b"\xff" * 8,
                                        "little")
    assert result[26] == repeated(0x200, 32, 4)
    assert result[27] == repeated(0x200, 32, 4)
    assert result[20] == repeated(0x40, 64, 2)
    assert result[24] == repeated(0x200, 64, 2)
    assert result[28] == repeated(0x100, 64, 2)
    assert result["fflags"] == 0x1F


def test_v_float_classify_disabled_without_v():
    result = run("RV32I+GC")
    assert all(value == 0 for key, value in result.items() if key != "fflags")
    assert result["fflags"] == 0x1F


def test_v_float_classify_sew64_requires_d():
    assert run("RV32I+F+V")[20] == 0
