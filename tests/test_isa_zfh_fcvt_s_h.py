"""Complete Zfhmin half-to-single widening conversion semantics."""

import pytest
from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.isa import LOAD_FP, OP_FP, OP_IMM, SYSTEM, enc_i, enc_r
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


HALF_CASES = (
    (0x3E00, 0x3FC00000),  # 1.5
    (0xC000, 0xC0000000),  # -2.0
    (0x0400, 0x38800000),  # minimum normal
    (0x0001, 0x33800000),  # minimum subnormal
    (0x03FF, 0x387FC000),  # maximum subnormal
    (0x8000, 0x80000000),  # negative zero
    (0x7C00, 0x7F800000),  # positive infinity
    (0x7E35, 0x7FC00000),  # quiet NaN
)


def nop():
    return enc_i(OP_IMM, 0, 0, 0, 0)


class _ZfhFcvtSHBench(Elaboratable):
    def __init__(self, extensions):
        data = [value for value, _ in HALF_CASES]
        data += [0x00007C01, 0x00003E00]  # sNaN half, then invalid-box single word
        program = [enc_i(SYSTEM, 0, 0b101, 0, 0x001)]
        for index in range(len(HALF_CASES)):
            program.extend([enc_i(LOAD_FP, 1, 0b001, 0, index * 4), *([nop()] * 4)])
            program.extend([
                enc_r(OP_FP, 10 + index, 0b000, 1, 2, 0b0100000),
                *([nop()] * 4),
            ])
        program.extend([enc_i(SYSTEM, 20, 0b010, 0, 0x001), *([nop()] * 4)])
        program.extend([enc_i(LOAD_FP, 1, 0b001, 0, len(HALF_CASES) * 4), *([nop()] * 4)])
        program.extend([
            enc_r(OP_FP, 18, 0b000, 1, 2, 0b0100000),
            *([nop()] * 4),
            enc_i(SYSTEM, 21, 0b010, 0, 0x001),
            *([nop()] * 4),
            enc_i(SYSTEM, 0, 0b101, 0, 0x001),
            *([nop()] * 4),
        ])
        program.extend([enc_i(LOAD_FP, 1, 0b010, 0, (len(HALF_CASES) + 1) * 4), *([nop()] * 4)])
        program.extend([
            enc_r(OP_FP, 19, 0b000, 1, 2, 0b0100000),
            *([nop()] * 4),
            enc_i(SYSTEM, 22, 0b010, 0, 0x001),
            *([nop()] * 4),
        ])
        program += [nop()] * (256 - len(program))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=256, init=program)
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
def test_zfh_fcvt_s_h_normals_subnormals_specials_and_nan_box(extensions):
    dut = _ZfhFcvtSHBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    fprs = {}
    flags = {}

    def process():
        for _ in range(500):
            yield Tick()
        for reg in range(10, 20):
            yield dut.core.dbg_freg_addr.eq(reg)
            yield Tick()
            fprs[reg] = yield dut.core.dbg_freg_rdata
        for reg in range(20, 23):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            flags[reg] = yield dut.core.dbg_reg_rdata

    sim.add_process(process)
    sim.run()
    expected = [0xFFFFFFFF00000000 | value for _, value in HALF_CASES]
    expected += [0xFFFFFFFF7FC00000, 0xFFFFFFFF7FC00000]
    assert tuple(fprs[reg] for reg in range(10, 20)) == tuple(expected)
    assert flags == {20: 0, 21: 0b10000, 22: 0}
