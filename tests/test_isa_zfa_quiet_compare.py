"""Complete Zfa quiet floating-point comparison execution semantics."""

import pytest
from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.isa import LOAD_FP, OP_FP, OP_IMM, SYSTEM, enc_i, enc_r
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


def nop():
    return enc_i(OP_IMM, 0, 0, 0, 0)


class _ZfaQuietCompareBench(Elaboratable):
    def __init__(self, extensions, is_double):
        if is_double:
            funct7 = 0b1010001
            values = (0x7FF8000000001234, 0x7FF0000000000001, 0xC000000000000000,
                      0x3FF8000000000000, 0, 0x8000000000000000)
            data = []
            for value in values:
                data += [value & 0xFFFFFFFF, value >> 32]
            load = lambda rd, index: enc_i(LOAD_FP, rd, 0b011, 0, index * 8)
        else:
            funct7 = 0b1010000
            values = (0x7FC01234, 0x7F800001, 0xC0000000, 0x3FC00000, 0, 0x80000000)
            data = list(values)
            load = lambda rd, index: enc_i(LOAD_FP, rd, 0b010, 0, index * 4)

        program = []
        for index in range(6):
            program += [load(index + 1, index), *([nop()] * 4)]
        program += [
            enc_r(OP_FP, 10, 0b100, 1, 4, funct7),  # FLEQ qNaN,1.5 -> false, no NV
            enc_r(OP_FP, 11, 0b101, 1, 4, funct7),  # FLTQ qNaN,1.5 -> false, no NV
            enc_r(OP_FP, 12, 0b100, 3, 4, funct7),  # -2 <= 1.5
            enc_r(OP_FP, 13, 0b101, 4, 3, funct7),  # 1.5 < -2
            enc_r(OP_FP, 14, 0b100, 5, 6, funct7),  # +0 <= -0
            *([nop()] * 4),
            enc_i(SYSTEM, 20, 0b010, 0, 0x001),
            enc_r(OP_FP, 15, 0b100, 2, 4, funct7),  # FLEQ sNaN,1.5 -> false and NV
            *([nop()] * 4),
            enc_i(SYSTEM, 21, 0b010, 0, 0x001),
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
def test_zfa_quiet_compare_qnan_snan_finite_and_signed_zero(extensions, is_double):
    dut = _ZfaQuietCompareBench(extensions, is_double)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    observed = {}

    def process():
        for _ in range(300):
            yield Tick()
        for reg in (10, 11, 12, 13, 14, 15, 20, 21):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            observed[reg] = yield dut.core.dbg_reg_rdata

    sim.add_process(process)
    sim.run()
    assert observed == {10: 0, 11: 0, 12: 1, 13: 0, 14: 1, 15: 0, 20: 0, 21: 0b10000}
