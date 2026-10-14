"""Complete Zfhmin half-precision integer/floating move execution."""

import pytest
from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.isa import LOAD, OP_FP, OP_IMM, enc_i, enc_r
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


VALUES = (0x3C55, 0xBC55, 0x7E35)


def nop():
    return enc_i(OP_IMM, 0, 0, 0, 0)


class _ZfhMoveBench(Elaboratable):
    def __init__(self, extensions):
        program = []
        for index in range(3):
            program.extend([enc_i(LOAD, index + 1, 0b010, 0, index * 4), *([nop()] * 4)])
            program.extend([
                enc_r(OP_FP, 10 + index, 0b000, index + 1, 0, 0b1111010),
                *([nop()] * 4),
            ])
        for index in range(3):
            program.extend([
                enc_r(OP_FP, 20 + index, 0b000, 10 + index, 0, 0b1110010),
                *([nop()] * 4),
            ])
        program += [nop()] * (128 - len(program))
        self.core = RV12Core(core_id=0, xlen=32, rb_mode=1, extensions=extensions)
        self.imem = SimpleIMem(words=128, init=program)
        self.dmem = SimpleDMem(words=16, init=list(VALUES) + [0] * 13)

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


@pytest.mark.parametrize("extensions", [
    "RV32I+GC+ZFHMIN",
    "RV32I+GC+ZFH",
    "RV32I+GC+*",
])
def test_zfh_moves_nan_box_sign_extend_and_preserve_payload(extensions):
    dut = _ZfhMoveBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    fprs = []
    xregs = []

    def process():
        for _ in range(280):
            yield Tick()
        for reg in range(10, 13):
            yield dut.core.dbg_freg_addr.eq(reg)
            yield Tick()
            fprs.append((yield dut.core.dbg_freg_rdata))
        for reg in range(20, 23):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            xregs.append((yield dut.core.dbg_reg_rdata))

    sim.add_process(process)
    sim.run()
    assert tuple(fprs) == tuple(0xFFFFFFFFFFFF0000 | value for value in VALUES)
    assert tuple(xregs) == (0x00003C55, 0xFFFFBC55, 0x00007E35)
