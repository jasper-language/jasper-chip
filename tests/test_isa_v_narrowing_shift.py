"""Executable V narrowing logical/arithmetic shift family closure."""

import pytest
from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.isa import OP_IMM, OP_V, SYSTEM, enc_i
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


EXTENSIONS = ("RV32I+GC+V", "RV32I+GC+*")


def nop():
    return enc_i(OP_IMM, 0, 0, 0, 0)


def vsetivli(rd, avl, vsew=0, vlmul=0, vta=0):
    vtype = ((vta & 1) << 6) | ((vsew & 7) << 3) | (vlmul & 7)
    return ((0b11 << 30) | (vtype << 20) | ((avl & 0x1F) << 15) |
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


def vnshift(funct6, funct3, vd, vs2, operand, vm=1):
    return ((funct6 << 26) | ((vm & 1) << 25) | ((vs2 & 0x1F) << 20) |
            ((operand & 0x1F) << 15) | (funct3 << 12) | ((vd & 0x1F) << 7) | OP_V)


def csrrwi(csr, value):
    return ((csr & 0xFFF) << 20) | ((value & 0x1F) << 15) | (0b101 << 12) | SYSTEM


class _VNarrowingShiftBench(Elaboratable):
    def __init__(self, extensions):
        program = [
            vsetivli(17, 4, vsew=1),
            enc_i(OP_IMM, 1, 0, 0, 0x123), vmv_v_x(4, 1),
            enc_i(OP_IMM, 2, 0, 0, -256), vmv_v_x(6, 2),
            vsetivli(17, 4), vmv_v_i(1, 1),
            enc_i(OP_IMM, 2, 0, 0, 2), *([nop()] * 3),
            vnshift(0x2C, 0b000, 8, 4, 1),
            vnshift(0x2C, 0b100, 9, 4, 2),
            vnshift(0x2C, 0b011, 10, 4, 3),
            vnshift(0x2D, 0b000, 11, 6, 1),
            vnshift(0x2D, 0b100, 12, 6, 2),
            vnshift(0x2D, 0b011, 13, 6, 3),
            enc_i(OP_IMM, 3, 0, 0, 5), vmv_s_x(0, 3), vmv_v_i(14, 7),
            *([nop()] * 3), vnshift(0x2C, 0b000, 14, 4, 1, vm=0),
            vmv_v_i(15, 7), csrrwi(0x008, 2), vnshift(0x2C, 0b000, 15, 4, 1),
            vsetivli(17, 2, vta=1), vnshift(0x2C, 0b000, 16, 4, 1),
            vsetivli(17, 10, vsew=2, vlmul=2),
            enc_i(OP_IMM, 1, 0, 0, -300), vmv_v_x(20, 1),
            vsetivli(17, 10, vsew=1, vlmul=1),
            enc_i(OP_IMM, 3, 0, 0, 4), *([nop()] * 3),
            vnshift(0x2D, 0b100, 24, 20, 3),
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
    dut = _VNarrowingShiftBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    result = {}

    def process():
        for _ in range(1150):
            yield Tick()
        for reg in (8, 9, 10, 11, 12, 13, 14, 15, 16, 24, 25):
            yield dut.core.dbg_vreg_addr.eq(reg)
            yield Tick()
            result[reg] = yield dut.core.dbg_vreg_rdata

    sim.add_process(process)
    sim.run()
    return result


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_v_narrowing_shift_forms_mask_vstart_tail_and_groups(extensions):
    result = run(extensions)
    assert result[8] & 0xFFFFFFFF == 0x91919191
    assert result[9] & 0xFFFFFFFF == 0x48484848
    assert result[10] & 0xFFFFFFFF == 0x24242424
    assert result[11] & 0xFFFFFFFF == 0x80808080
    assert result[12] & 0xFFFFFFFF == 0xC0C0C0C0
    assert result[13] & 0xFFFFFFFF == 0xE0E0E0E0
    assert result[14] & 0xFFFFFFFF == 0x07910791
    assert result[15] & 0xFFFFFFFF == 0x91910707
    assert result[16] == int.from_bytes(b"\x91\x91" + b"\xff" * 14, "little")
    expected = int.from_bytes(b"\xed\xff" * 8, "little")
    assert result[24] == expected
    assert result[25] & 0xFFFFFFFF == int.from_bytes(b"\xed\xff" * 2, "little")


def test_v_narrowing_shift_disabled_without_v():
    assert all(value == 0 for value in run("RV32I+GC").values())
