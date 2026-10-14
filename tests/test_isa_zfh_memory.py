"""Complete Zfh/Zfhmin half-precision load and store execution semantics."""

import pytest
from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.isa import LOAD, LOAD_FP, OP_IMM, STORE_FP, enc_i, enc_s
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


def nop():
    return enc_i(OP_IMM, 0, 0, 0, 0)


class _ZfhMemoryBench(Elaboratable):
    def __init__(self, extensions):
        program = [
            enc_i(LOAD_FP, 1, 0b001, 0, 0),
            *([nop()] * 4),
            enc_i(LOAD_FP, 2, 0b001, 0, 2),
            *([nop()] * 4),
            enc_s(STORE_FP, 0b001, 0, 1, 4),
            *([nop()] * 4),
            enc_s(STORE_FP, 0b001, 0, 2, 6),
            *([nop()] * 4),
            enc_i(LOAD, 10, 0b010, 0, 4),
            *([nop()] * 4),
        ]
        program += [nop()] * (96 - len(program))
        self.core = RV12Core(core_id=0, xlen=32, rb_mode=1, extensions=extensions)
        self.imem = SimpleIMem(words=96, init=program)
        self.dmem = SimpleDMem(words=16, init=[0x7E353C00, 0xA5A55A5A] + [0] * 14)

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
def test_zfh_flh_nan_boxes_and_fsh_preserves_unselected_halfword(extensions):
    dut = _ZfhMemoryBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    observed = {}

    def process():
        for _ in range(220):
            yield Tick()
        for reg in (1, 2):
            yield dut.core.dbg_freg_addr.eq(reg)
            yield Tick()
            observed[f"f{reg}"] = yield dut.core.dbg_freg_rdata
        yield dut.core.dbg_reg_addr.eq(10)
        yield Tick()
        observed["x10"] = yield dut.core.dbg_reg_rdata

    sim.add_process(process)
    sim.run()
    assert observed == {
        "f1": 0xFFFFFFFFFFFF3C00,
        "f2": 0xFFFFFFFFFFFF7E35,
        "x10": 0x7E353C00,
    }
