"""Complete Zfa FLI.H constant table, legality, NaN-box, and fflags tests."""

import pytest
from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.isa import OP_FP, OP_IMM, SYSTEM, enc_i, enc_r
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


FLI_H = (
    0xBC00, 0x0400, 0x0100, 0x0200,
    0x1C00, 0x2000, 0x2C00, 0x3000,
    0x3400, 0x3500, 0x3600, 0x3700,
    0x3800, 0x3900, 0x3A00, 0x3B00,
    0x3C00, 0x3D00, 0x3E00, 0x3F00,
    0x4000, 0x4100, 0x4200, 0x4400,
    0x4800, 0x4C00, 0x5800, 0x5C00,
    0x7800, 0x7C00, 0x7C00, 0x7E00,
)


def _nop():
    return enc_i(OP_IMM, 0, 0, 0, 0)


class _FliHBench(Elaboratable):
    def __init__(self, extensions, all_constants=True):
        program = [enc_i(OP_IMM, 31, 0, 0, 0x1f),
                   enc_i(SYSTEM, 0, 0b001, 31, 0x001)]
        if all_constants:
            program += [enc_r(OP_FP, index, 0, index, 1, 0b1111010)
                        for index in range(32)]
        else:
            program += [enc_r(OP_FP, 1, 0, 16, 1, 0b1111010)]
        program += [enc_i(SYSTEM, 30, 0b010, 0, 0x001)]
        program += [_nop()] * (128 - len(program))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=128, init=program)
        self.dmem = SimpleDMem(words=16)

    def elaborate(self, platform):
        m = Module(); m.submodules.core = c = self.core
        m.submodules.imem = im = self.imem; m.submodules.dmem = dm = self.dmem
        m.d.comb += [
            im.addr.eq(c.imem_addr), c.imem_rdata.eq(im.rdata),
            dm.req_valid.eq(c.dmem_valid), dm.req_we.eq(c.dmem_we),
            dm.req_addr.eq(c.dmem_addr), dm.req_wdata.eq(c.dmem_wdata),
            c.dmem_rdata.eq(dm.rsp_rdata), c.gc_enq_ready.eq(0),
            c.gc_rsp_valid.eq(0), c.gc_rsp_tag.eq(0), c.gc_rsp_rd.eq(0),
            c.gc_rsp_data.eq(0), c.wb_enq_ready.eq(1), c.mv_cmd_ready.eq(1),
            c.mv_rsp_valid.eq(0), c.mv_rsp_tag.eq(0), c.mv_rsp_rd.eq(0),
            c.mv_rsp_data.eq(0),
        ]
        return m


def _run(extensions, all_constants=True):
    dut = _FliHBench(extensions, all_constants)
    sim = Simulator(dut); sim.add_clock(1e-6)
    observed = []; state = {}

    def process():
        for _ in range(240):
            yield Tick()
        count = 32 if all_constants else 2
        for index in range(count):
            yield dut.core.dbg_freg_addr.eq(index); yield Tick()
            observed.append((yield dut.core.dbg_freg_rdata))
        yield dut.core.dbg_reg_addr.eq(30); yield Tick()
        state["fflags"] = yield dut.core.dbg_reg_rdata

    sim.add_process(process); sim.run()
    return tuple(observed), state["fflags"]


@pytest.mark.parametrize("extensions", ["RV32I+GC+ZFH+ZFA", "RV32I+GC+*"])
def test_zfa_fli_h_all_standard_constants_nan_box_and_preserve_fflags(extensions):
    observed, fflags = _run(extensions)
    assert observed == tuple(0xFFFFFFFFFFFF0000 | value for value in FLI_H)
    assert fflags == 0x1f


def test_zfa_fli_h_requires_zfh():
    observed, fflags = _run("RV32I+GC+ZFA", all_constants=False)
    assert observed[1] == 0
    assert fflags == 0x1f
