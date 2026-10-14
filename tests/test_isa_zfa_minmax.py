"""Complete Zfa minimumNumber/maximumNumber execution semantics."""

import pytest
from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.isa import LOAD_FP, OP_FP, OP_IMM, SYSTEM, enc_i, enc_r
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


def nop():
    return enc_i(OP_IMM, 0, 0, 0, 0)


class _ZfaMinMaxBench(Elaboratable):
    def __init__(self, extensions, is_double):
        if is_double:
            funct7 = 0b0010101
            values = (
                0x7FF8000000001234, 0x3FF8000000000000, 0xC000000000000000,
                0x0000000000000000, 0x8000000000000000, 0x7FF0000000000001,
            )
            data = []
            for value in values:
                data += [value & 0xFFFFFFFF, value >> 32]
            load = lambda rd, index: enc_i(LOAD_FP, rd, 0b011, 0, index * 8)
        else:
            funct7 = 0b0010100
            values = (0x7FC01234, 0x3FC00000, 0xC0000000, 0, 0x80000000, 0x7F800001)
            data = list(values)
            load = lambda rd, index: enc_i(LOAD_FP, rd, 0b010, 0, index * 4)

        program = []
        for index in range(6):
            program += [load(index + 1, index), *([nop()] * 4)]
        program += [
            enc_r(OP_FP, 20, 0b010, 1, 2, funct7),  # FMINM qNaN, 1.5 -> canonical NaN
            enc_r(OP_FP, 21, 0b011, 1, 2, funct7),  # FMAXM qNaN, 1.5 -> canonical NaN
            enc_r(OP_FP, 22, 0b010, 2, 3, funct7),  # min(1.5, -2) -> -2
            enc_r(OP_FP, 23, 0b011, 2, 3, funct7),  # max(1.5, -2) -> 1.5
            enc_r(OP_FP, 24, 0b010, 4, 5, funct7),  # min(+0, -0) -> -0
            enc_r(OP_FP, 25, 0b011, 4, 5, funct7),  # max(+0, -0) -> +0
            *([nop()] * 4),
            enc_i(SYSTEM, 10, 0b010, 0, 0x001),      # qNaN operations do not set NV
            enc_r(OP_FP, 26, 0b010, 6, 2, funct7),  # sNaN -> canonical NaN and NV
            *([nop()] * 4),
            enc_i(SYSTEM, 11, 0b010, 0, 0x001),
        ]
        program += [nop()] * (160 - len(program))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=160, init=program)
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


@pytest.mark.parametrize("extensions", ["RV32I+GC+ZFA", "RV32I+GC+*"])
@pytest.mark.parametrize("is_double", [False, True])
def test_zfa_minm_maxm_complete_nan_zero_and_finite_semantics(extensions, is_double):
    dut = _ZfaMinMaxBench(extensions, is_double)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    fp_results = {}
    int_results = {}

    def process():
        for _ in range(320):
            yield Tick()
        for reg in range(20, 27):
            yield dut.core.dbg_freg_addr.eq(reg)
            yield Tick()
            fp_results[reg] = yield dut.core.dbg_freg_rdata
        for reg in (10, 11):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            int_results[reg] = yield dut.core.dbg_reg_rdata

    sim.add_process(process)
    sim.run()
    if is_double:
        expected = (0x7FF8000000000000, 0x7FF8000000000000, 0xC000000000000000,
                    0x3FF8000000000000, 0x8000000000000000, 0, 0x7FF8000000000000)
    else:
        expected = tuple(0xFFFFFFFF00000000 | value for value in (
            0x7FC00000, 0x7FC00000, 0xC0000000, 0x3FC00000, 0x80000000, 0, 0x7FC00000,
        ))
    assert tuple(fp_results[reg] for reg in range(20, 27)) == expected
    assert int_results == {10: 0, 11: 0b10000}
