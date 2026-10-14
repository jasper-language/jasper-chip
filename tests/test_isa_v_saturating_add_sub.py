"""Executable V saturating add/subtract and vxsat CSR closure."""

import pytest
from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.isa import OP_IMM, OP_V, SYSTEM, enc_i
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


def vsat(funct6, funct3, vd, vs2, operand, vm=1):
    return ((funct6 << 26) | ((vm & 1) << 25) | ((vs2 & 0x1F) << 20) |
            ((operand & 0x1F) << 15) | (funct3 << 12) | ((vd & 0x1F) << 7) | OP_V)


def csrrs(rd, csr):
    return ((csr & 0xFFF) << 20) | (0b010 << 12) | ((rd & 0x1F) << 7) | SYSTEM


def csrrwi(csr, value):
    return ((csr & 0xFFF) << 20) | ((value & 0x1F) << 15) | (0b101 << 12) | SYSTEM


class _VSaturatingBench(Elaboratable):
    def __init__(self, extensions):
        program = [
            csrrwi(0x00F, 0),
            vsetivli(12, 4),
            enc_i(OP_IMM, 1, 0, 0, 250), vmv_v_x(1, 1),
            enc_i(OP_IMM, 2, 0, 0, 10), vmv_v_x(2, 2),
            *([nop()] * 3),
            vsat(0x20, 0b000, 3, 1, 2),
            csrrs(20, 0x009), csrrwi(0x009, 0),
            enc_i(OP_IMM, 1, 0, 0, 127), vmv_v_x(4, 1),
            *([nop()] * 3),
            vsat(0x21, 0b011, 5, 4, 1),
            csrrs(21, 0x00F), csrrwi(0x009, 0),
            enc_i(OP_IMM, 1, 0, 0, 0), vmv_v_x(6, 1),
            enc_i(OP_IMM, 2, 0, 0, 1),
            *([nop()] * 3),
            vsat(0x22, 0b100, 7, 6, 2),
            csrrs(22, 0x009), csrrwi(0x009, 0),
            enc_i(OP_IMM, 1, 0, 0, -128), vmv_v_x(8, 1),
            vmv_v_i(9, 1),
            *([nop()] * 3),
            vsat(0x23, 0b000, 10, 8, 9),
            csrrs(23, 0x009), csrrwi(0x009, 0),
            vmv_s_x(0, 0), vmv_v_i(11, 7),
            *([nop()] * 3),
            vsat(0x20, 0b000, 11, 1, 2, vm=0),
            csrrs(24, 0x009),
            csrrwi(0x00A, 3), csrrs(25, 0x00F),
            csrrwi(0x00F, 1), csrrs(26, 0x00A), csrrs(27, 0x009),
            csrrwi(0x009, 0),
            vsetivli(12, 10, vsew=1, vlmul=1),
            vmv_v_i(16, -1),
            enc_i(OP_IMM, 1, 0, 0, 1),
            *([nop()] * 3),
            vsat(0x20, 0b100, 18, 16, 1),
            csrrs(28, 0x009),
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
    dut = _VSaturatingBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    vectors = {}
    scalars = {}

    def process():
        for _ in range(960):
            yield Tick()
        for reg in (3, 5, 7, 10, 11, 18, 19):
            yield dut.core.dbg_vreg_addr.eq(reg)
            yield Tick()
            vectors[reg] = yield dut.core.dbg_vreg_rdata
        for reg in range(20, 29):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            scalars[reg] = yield dut.core.dbg_reg_rdata

    sim.add_process(process)
    sim.run()
    return vectors, scalars


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_v_saturating_add_sub_results_masks_groups_and_csrs(extensions):
    vectors, scalars = run(extensions)
    assert vectors[3] == 0xFFFFFFFF
    assert vectors[5] == 0x7F7F7F7F
    assert vectors[7] == 0
    assert vectors[10] == 0x80808080
    assert vectors[11] == 0x07070707
    assert vectors[18] == (1 << 128) - 1
    assert vectors[19] & 0xFFFFFFFF == 0xFFFFFFFF
    assert [scalars[i] for i in range(20, 24)] == [1, 1, 1, 1]
    assert scalars[24] == 0
    assert scalars[25] == 0b110
    assert scalars[26] == 0
    assert scalars[27] == 1
    assert scalars[28] == 1


def test_v_saturating_add_sub_disabled_without_v():
    vectors, scalars = run("RV32I+GC")
    assert all(value == 0 for value in vectors.values())
    assert all(value == 0 for value in scalars.values())
