"""Executable V 1.0 vsetvli/vsetivli/vsetvl configuration closure."""

import pytest
from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.isa import OP_IMM, OP_V, enc_i, enc_vsetvli
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


EXTENSIONS = ("RV32I+GC+V", "RV32I+GC+*")


def vtype(vsew, vlmul, vta=1, vma=1):
    return ((vma & 1) << 7) | ((vta & 1) << 6) | ((vsew & 7) << 3) | (vlmul & 7)


def vsetivli(rd, avl, value):
    return ((0b11 << 30) | ((value & 0x3FF) << 20) | ((avl & 0x1F) << 15) |
            (0b111 << 12) | ((rd & 0x1F) << 7) | OP_V)


def vsetvl(rd, rs1, rs2):
    return ((0b1000000 << 25) | ((rs2 & 0x1F) << 20) | ((rs1 & 0x1F) << 15) |
            (0b111 << 12) | ((rd & 0x1F) << 7) | OP_V)


def nop():
    return enc_i(OP_IMM, 0, 0, 0, 0)


class _VConfigBench(Elaboratable):
    def __init__(self, extensions):
        e8m1 = vtype(0, 0)
        e16m2 = vtype(1, 1)
        e32m4 = vtype(2, 2)
        e32m1 = vtype(2, 0)
        e32mf2 = vtype(2, 7)
        program = [
            enc_i(OP_IMM, 1, 0, 0, 20),
            enc_vsetvli(5, 1, e8m1),
            enc_i(OP_IMM, 6, 0, 5, 1),
            *([nop()] * 4),
            vsetivli(7, 5, e16m2),
            *([nop()] * 4),
            enc_i(OP_IMM, 2, 0, 0, e32m4),
            enc_i(OP_IMM, 3, 0, 0, 30),
            vsetvl(8, 3, 2),
            *([nop()] * 4),
            enc_i(OP_IMM, 4, 0, 0, 0x100),
            vsetvl(9, 3, 4),
            *([nop()] * 4),
            enc_vsetvli(10, 0, e32m1),
            *([nop()] * 4),
            vsetivli(11, 3, vtype(0, 4)),
            *([nop()] * 4),
            vsetivli(12, 31, e32mf2),
            *([nop()] * 4),
            0x0000006F,
        ]
        program += [nop()] * (96 - len(program))
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


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_v_configuration_avl_vlmax_vill_and_integer_dependency(extensions):
    dut = _VConfigBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    result = {}

    def process():
        for _ in range(420):
            yield Tick()
        for reg in range(5, 13):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            result[reg] = yield dut.core.dbg_reg_rdata

    sim.add_process(process)
    sim.run()
    assert result == {
        5: 16,   # e8,m1: VLMAX=16, AVL=20 clamps to 16
        6: 17,   # immediate RAW dependency on vsetvli result
        7: 5,    # vsetivli immediate AVL
        8: 16,   # e32,m4: VLMAX=16, register AVL clamps
        9: 0,    # reserved upper vtype bit sets vill and vl=0
        10: 4,   # rs1=x0, rd!=x0 selects VLMAX
        11: 0,   # reserved vlmul=100 sets vill and vl=0
        12: 2,   # legal fractional LMUL e32,mf2
    }


def test_v_configuration_is_not_enabled_without_v():
    dut = _VConfigBench("RV32I+GC")
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    result = {}

    def process():
        for _ in range(420):
            yield Tick()
        for reg in (5, 7, 8, 9, 10, 11, 12):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            result[reg] = yield dut.core.dbg_reg_rdata

    sim.add_process(process)
    sim.run()
    assert all(value == 0 for value in result.values())
