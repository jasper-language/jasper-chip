"""Complete Zfa single-precision round-to-integer execution semantics."""

import pytest
from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.isa import LOAD_FP, OP_FP, OP_IMM, SYSTEM, enc_i, enc_r
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


def nop():
    return enc_i(OP_IMM, 0, 0, 0, 0)


class _ZfaRoundSBench(Elaboratable):
    def __init__(self, extensions):
        values = (
            0x3FC00000,  # 1.5
            0x40200000,  # 2.5
            0xBFC00000,  # -1.5
            0x3F400000,  # 0.75
            0xBF400000,  # -0.75
            0x7FC01234,  # quiet NaN
            0x7F800001,  # signaling NaN
            0x7F800000,  # +infinity
        )
        program = []

        def emit(value_index, rd, rm, exact=True):
            program.extend([enc_i(LOAD_FP, 1, 0b010, 0, value_index * 4), *([nop()] * 4)])
            program.extend([
                enc_r(OP_FP, 2, rm, 1, 4 if exact else 5, 0b0100000),
                *([nop()] * 4),
                enc_r(OP_FP, rd, 0b000, 2, 0, 0b1110000),
                *([nop()] * 4),
            ])

        program.append(enc_i(SYSTEM, 0, 0b101, 0, 0x001))  # clear fflags
        emit(0, 10, 0b000)              # FROUND.S 1.5 RNE -> 2.0, no NX
        program.extend([enc_i(SYSTEM, 20, 0b010, 0, 0x001), *([nop()] * 4)])
        emit(1, 11, 0b000, exact=False) # FROUNDNX.S 2.5 RNE -> 2.0, NX
        program.extend([enc_i(SYSTEM, 21, 0b010, 0, 0x001), *([nop()] * 4)])
        program.extend([enc_i(SYSTEM, 0, 0b101, 0, 0x001), *([nop()] * 4)])
        emit(2, 12, 0b010)              # -1.5 RDN -> -2.0
        emit(2, 13, 0b011)              # -1.5 RUP -> -1.0
        emit(3, 14, 0b001)              # 0.75 RTZ -> +0
        emit(4, 15, 0b011)              # -0.75 RUP -> -0
        emit(3, 16, 0b100)              # 0.75 RMM -> 1.0
        program.extend([enc_i(SYSTEM, 0, 0b101, 1, 0x002), *([nop()] * 4)])  # frm=RTZ
        emit(0, 17, 0b111)              # dynamic RTZ: 1.5 -> 1.0
        emit(5, 18, 0b000)              # qNaN -> canonical NaN, no NV
        program.extend([enc_i(SYSTEM, 22, 0b010, 0, 0x001), *([nop()] * 4)])
        emit(6, 19, 0b000)              # sNaN -> canonical NaN and NV
        program.extend([enc_i(SYSTEM, 23, 0b010, 0, 0x001), *([nop()] * 4)])
        emit(7, 24, 0b000)              # infinity copied
        program += [nop()] * (256 - len(program))

        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=256, init=program)
        self.dmem = SimpleDMem(words=32, init=list(values) + [0] * 24)

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
def test_zfa_fround_s_all_rounding_modes_flags_and_special_values(extensions):
    dut = _ZfaRoundSBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    observed = {}

    def process():
        for _ in range(650):
            yield Tick()
        for reg in range(10, 25):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            observed[reg] = yield dut.core.dbg_reg_rdata

    sim.add_process(process)
    sim.run()
    assert observed == {
        10: 0x40000000,
        11: 0x40000000,
        12: 0xC0000000,
        13: 0xBF800000,
        14: 0x00000000,
        15: 0x80000000,
        16: 0x3F800000,
        17: 0x3F800000,
        18: 0x7FC00000,
        19: 0x7FC00000,
        20: 0,
        21: 0b00001,
        22: 0,
        23: 0b10000,
        24: 0x7F800000,
    }
