"""Executable V fixed-point saturating multiply closure."""

import pytest
from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.isa import LUI, OP_IMM, OP_V, SYSTEM, enc_i
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


EXTENSIONS = ("RV32I+GC+V", "RV32I+GC+*")


def nop():
    return enc_i(OP_IMM, 0, 0, 0, 0)


def vsetivli(rd, avl, vsew=0, vlmul=0):
    value = ((vsew & 7) << 3) | (vlmul & 7)
    return ((0b11 << 30) | (value << 20) | ((avl & 0x1F) << 15) |
            (0b111 << 12) | ((rd & 0x1F) << 7) | OP_V)


def vmv_s_x(vd, rs1):
    return ((0x10 << 26) | (1 << 25) | ((rs1 & 0x1F) << 15) |
            (0b110 << 12) | ((vd & 0x1F) << 7) | OP_V)


def vmv_v_i(vd, imm):
    return ((0x17 << 26) | (1 << 25) | ((imm & 0x1F) << 15) |
            (0b011 << 12) | ((vd & 0x1F) << 7) | OP_V)


def vmv_v_x(vd, rs1):
    return ((0x17 << 26) | (1 << 25) | ((rs1 & 0x1F) << 15) |
            (0b100 << 12) | ((vd & 0x1F) << 7) | OP_V)


def vsmul(funct3, vd, vs2, operand, vm=1):
    return ((0x27 << 26) | ((vm & 1) << 25) | ((vs2 & 0x1F) << 20) |
            ((operand & 0x1F) << 15) | (funct3 << 12) | ((vd & 0x1F) << 7) | OP_V)


def csrrs(rd, csr):
    return ((csr & 0xFFF) << 20) | (0b010 << 12) | ((rd & 0x1F) << 7) | SYSTEM


def csrrwi(csr, value):
    return ((csr & 0xFFF) << 20) | ((value & 0x1F) << 15) | (0b101 << 12) | SYSTEM


def lui(rd, imm20):
    return ((imm20 & 0xFFFFF) << 12) | ((rd & 0x1F) << 7) | LUI


class _VSaturatingMultiplyBench(Elaboratable):
    def __init__(self, extensions):
        program = [
            csrrwi(0x00F, 0), vsetivli(17, 4),
            enc_i(OP_IMM, 1, 0, 0, 64), vmv_v_x(1, 1), vmv_v_i(2, 1),
            *([nop()] * 3),
            csrrwi(0x00A, 0), vsmul(0b000, 3, 1, 2),
            csrrwi(0x00A, 1), vsmul(0b000, 4, 1, 2),
            csrrwi(0x00A, 2), vsmul(0b000, 5, 1, 2),
            csrrwi(0x00A, 3), vsmul(0b000, 6, 1, 2),
            enc_i(OP_IMM, 1, 0, 0, -64), vmv_v_x(7, 1),
            enc_i(OP_IMM, 2, 0, 0, 1),
            *([nop()] * 3),
            csrrwi(0x00A, 0), vsmul(0b100, 8, 7, 2),
            csrrwi(0x00A, 1), vsmul(0b100, 9, 7, 2),
            csrrwi(0x00A, 2), vsmul(0b100, 10, 7, 2),
            csrrwi(0x00A, 3), vsmul(0b100, 11, 7, 2),
            enc_i(OP_IMM, 1, 0, 0, -128), vmv_v_x(12, 1),
            *([nop()] * 3),
            csrrwi(0x009, 0), vsmul(0b000, 13, 12, 12),
            csrrs(20, 0x009), csrrwi(0x009, 0),
            vmv_s_x(0, 0), vmv_v_i(14, 7),
            *([nop()] * 3),
            vsmul(0b000, 14, 12, 12, vm=0), csrrs(21, 0x009),
            vsetivli(17, 10, vsew=1, vlmul=1),
            lui(1, 4), vmv_v_x(16, 1), enc_i(OP_IMM, 2, 0, 0, 1),
            *([nop()] * 3),
            csrrwi(0x00A, 0), vsmul(0b100, 18, 16, 2),
            vsetivli(17, 2, vsew=2, vlmul=7),
            lui(1, 0x80000), vmv_v_x(24, 1),
            *([nop()] * 3),
            csrrwi(0x009, 0), vsmul(0b000, 25, 24, 24), csrrs(22, 0x009),
            0x0000006F,
        ]
        program += [nop()] * (192 - len(program))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=len(program), init=program)
        self.dmem = SimpleDMem(words=16, init=[0] * 16)

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
    dut = _VSaturatingMultiplyBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    vectors = {}
    scalars = {}

    def process():
        for _ in range(1000):
            yield Tick()
        for reg in (3, 4, 5, 6, 8, 9, 10, 11, 13, 14, 18, 19, 25):
            yield dut.core.dbg_vreg_addr.eq(reg)
            yield Tick()
            vectors[reg] = yield dut.core.dbg_vreg_rdata
        for reg in (20, 21, 22):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            scalars[reg] = yield dut.core.dbg_reg_rdata

    sim.add_process(process)
    sim.run()
    return vectors, scalars


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_vsmul_rounding_saturation_mask_and_groups(extensions):
    vectors, scalars = run(extensions)
    assert vectors[3] == 0x01010101
    assert vectors[4] == 0
    assert vectors[5] == 0
    assert vectors[6] == 0x01010101
    assert vectors[8] == 0
    assert vectors[9] == 0
    assert vectors[10] == 0xFFFFFFFF
    assert vectors[11] == 0xFFFFFFFF
    assert vectors[13] == 0x7F7F7F7F
    assert vectors[14] == 0x07070707
    assert vectors[18] == int.from_bytes(bytes([1, 0] * 8), "little")
    assert vectors[19] == 0x00010001
    assert vectors[25] == 0x7FFFFFFF7FFFFFFF
    assert scalars == {20: 1, 21: 0, 22: 1}


def test_vsmul_disabled_without_v():
    vectors, scalars = run("RV32I+GC")
    assert all(value == 0 for value in vectors.values())
    assert all(value == 0 for value in scalars.values())
