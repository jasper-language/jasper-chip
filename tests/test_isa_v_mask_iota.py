"""Executable V mask iota prefix-count closure."""

import pytest
from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.isa import OP_IMM, OP_V, enc_i
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


def viota(vd, vs2, vm=1):
    return ((0x14 << 26) | ((vm & 1) << 25) | ((vs2 & 0x1F) << 20) |
            (0b10000 << 15) | (0b010 << 12) | ((vd & 0x1F) << 7) | OP_V)


class _VMaskIotaBench(Elaboratable):
    def __init__(self, extensions):
        program = [
            vsetivli(17, 8),
            enc_i(OP_IMM, 1, 0, 0, 0x91), vmv_s_x(2, 1),
            *([nop()] * 3), viota(1, 2),
            enc_i(OP_IMM, 1, 0, 0, 0x55), vmv_s_x(0, 1),
            enc_i(OP_IMM, 1, 0, 0, 0x91), vmv_s_x(3, 1), vmv_v_i(4, 7),
            *([nop()] * 3), viota(4, 3, vm=0),
            vsetivli(17, 10, vsew=1, vlmul=1),
            enc_i(OP_IMM, 1, 0, 0, 0x3FF), vmv_s_x(6, 1),
            *([nop()] * 3), viota(8, 6),
            0x0000006F,
        ]
        program += [nop()] * (128 - len(program))
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
    dut = _VMaskIotaBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    result = {}

    def process():
        for _ in range(800):
            yield Tick()
        for reg in (1, 4, 8, 9):
            yield dut.core.dbg_vreg_addr.eq(reg)
            yield Tick()
            result[reg] = yield dut.core.dbg_vreg_rdata

    sim.add_process(process)
    sim.run()
    return result


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_viota_prefix_mask_and_lmul_groups(extensions):
    result = run(extensions)
    assert result[1] & ((1 << 64) - 1) == int.from_bytes(
        bytes((0, 1, 1, 1, 1, 2, 2, 2)), "little")
    assert result[4] & ((1 << 64) - 1) == int.from_bytes(
        bytes((0, 7, 1, 7, 1, 7, 2, 7)), "little")
    assert result[8] == int.from_bytes(
        b"".join(index.to_bytes(2, "little") for index in range(8)), "little")
    assert result[9] == 0x00090008


def test_viota_disabled_without_v():
    result = run("RV32I+GC")
    assert all(value == 0 for value in result.values())
