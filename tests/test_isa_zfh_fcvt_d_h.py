"""Complete Zfhmin half-to-double widening conversion semantics."""

import pytest
from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.isa import LOAD_FP, OP_FP, OP_IMM, SYSTEM, enc_i, enc_r
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


CASES = (
    (0x3E00, 0x3FF8000000000000),
    (0xC000, 0xC000000000000000),
    (0x0400, 0x3F10000000000000),
    (0x0001, 0x3E70000000000000),
    (0x03FF, 0x3F0FF80000000000),
    (0x8000, 0x8000000000000000),
    (0x7C00, 0x7FF0000000000000),
    (0x7E35, 0x7FF8000000000000),
)


def nop():
    return enc_i(OP_IMM, 0, 0, 0, 0)


class _ZfhFcvtDHBench(Elaboratable):
    def __init__(self, extensions):
        data = [value for value, _ in CASES]
        data += [0x00007C01, 0x00003E00, 0x00000000]
        program = [enc_i(SYSTEM, 0, 0b101, 4, 0x002)]  # frm=RMM
        for index in range(len(CASES)):
            program.extend([enc_i(LOAD_FP, 1, 0b001, 0, index * 4), *([nop()] * 4)])
            program.extend([
                enc_r(OP_FP, 10 + index, 0b111 if index == 0 else 0b000, 1, 2, 0b0100001),
                *([nop()] * 4),
            ])
        program.extend([enc_i(SYSTEM, 20, 0b010, 0, 0x001), *([nop()] * 4)])
        program.extend([enc_i(LOAD_FP, 1, 0b001, 0, len(CASES) * 4), *([nop()] * 4)])
        program.extend([
            enc_r(OP_FP, 18, 0b000, 1, 2, 0b0100001),
            *([nop()] * 4),
            enc_i(SYSTEM, 21, 0b010, 0, 0x001),
            *([nop()] * 4),
            enc_i(SYSTEM, 0, 0b101, 0, 0x001),
            *([nop()] * 4),
        ])
        program.extend([enc_i(LOAD_FP, 1, 0b010, 0, (len(CASES) + 1) * 4), *([nop()] * 4)])
        program.extend([
            enc_r(OP_FP, 19, 0b000, 1, 2, 0b0100001),
            *([nop()] * 4),
            enc_i(SYSTEM, 22, 0b010, 0, 0x001),
            *([nop()] * 4),
        ])
        program.extend([enc_i(LOAD_FP, 24, 0b011, 0, (len(CASES) + 1) * 4), *([nop()] * 4)])
        program.extend([
            enc_r(OP_FP, 24, 0b101, 1, 2, 0b0100001),  # reserved rm: no write
            *([nop()] * 4),
        ])
        program += [nop()] * (320 - len(program))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=320, init=program)
        self.dmem = SimpleDMem(words=32, init=data + [0] * (32 - len(data)))

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
def test_zfh_fcvt_d_h_exact_special_nan_box_and_rm_legality(extensions):
    dut = _ZfhFcvtDHBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    fprs = {}
    flags = {}

    def process():
        for _ in range(700):
            yield Tick()
        for reg in (*range(10, 20), 24):
            yield dut.core.dbg_freg_addr.eq(reg)
            yield Tick()
            fprs[reg] = yield dut.core.dbg_freg_rdata
        for reg in range(20, 23):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            flags[reg] = yield dut.core.dbg_reg_rdata

    sim.add_process(process)
    sim.run()
    expected = [value for _, value in CASES]
    expected += [0x7FF8000000000000, 0x7FF8000000000000]
    assert tuple(fprs[reg] for reg in range(10, 20)) == tuple(expected)
    assert fprs[24] == 0x0000000000003E00
    assert flags == {20: 0, 21: 0b10000, 22: 0}
