"""Complete Zfa double-precision round-to-integer execution semantics."""

import pytest
from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.isa import LOAD_FP, OP_FP, OP_IMM, SYSTEM, enc_i, enc_r
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


def nop():
    return enc_i(OP_IMM, 0, 0, 0, 0)


class _ZfaRoundDBench(Elaboratable):
    def __init__(self, extensions):
        values = (
            0x3FF8000000000000,  # 1.5
            0x4004000000000000,  # 2.5
            0xBFF8000000000000,  # -1.5
            0x3FE8000000000000,  # 0.75
            0xBFE8000000000000,  # -0.75
            0x7FF8000000001234,  # quiet NaN
            0x7FF0000000000001,  # signaling NaN
            0x7FF0000000000000,  # +infinity
        )
        data = []
        for value in values:
            data += [value & 0xFFFFFFFF, value >> 32]
        program = []

        def emit(value_index, fd, rm, exact=True):
            program.extend([enc_i(LOAD_FP, 1, 0b011, 0, value_index * 8), *([nop()] * 4)])
            program.extend([
                enc_r(OP_FP, fd, rm, 1, 4 if exact else 5, 0b0100001),
                *([nop()] * 4),
            ])

        program.append(enc_i(SYSTEM, 0, 0b101, 0, 0x001))
        emit(0, 10, 0b000)
        program.extend([enc_i(SYSTEM, 20, 0b010, 0, 0x001), *([nop()] * 4)])
        emit(1, 11, 0b000, exact=False)
        program.extend([enc_i(SYSTEM, 21, 0b010, 0, 0x001), *([nop()] * 4)])
        program.extend([enc_i(SYSTEM, 0, 0b101, 0, 0x001), *([nop()] * 4)])
        emit(2, 12, 0b010)
        emit(2, 13, 0b011)
        emit(3, 14, 0b001)
        emit(4, 15, 0b011)
        emit(3, 16, 0b100)
        program.extend([enc_i(SYSTEM, 0, 0b101, 1, 0x002), *([nop()] * 4)])
        emit(0, 17, 0b111)
        emit(5, 18, 0b000)
        program.extend([enc_i(SYSTEM, 22, 0b010, 0, 0x001), *([nop()] * 4)])
        emit(6, 19, 0b000)
        program.extend([enc_i(SYSTEM, 23, 0b010, 0, 0x001), *([nop()] * 4)])
        emit(7, 24, 0b000)
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


@pytest.mark.parametrize("extensions", ["RV32I+GC+ZFA", "RV32I+GC+*"])
def test_zfa_fround_d_all_rounding_modes_flags_and_special_values(extensions):
    dut = _ZfaRoundDBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    fprs = {}
    xregs = {}

    def process():
        for _ in range(600):
            yield Tick()
        for reg in (*range(10, 20), 24):
            yield dut.core.dbg_freg_addr.eq(reg)
            yield Tick()
            fprs[reg] = yield dut.core.dbg_freg_rdata
        for reg in range(20, 24):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            xregs[reg] = yield dut.core.dbg_reg_rdata

    sim.add_process(process)
    sim.run()
    assert fprs == {
        10: 0x4000000000000000,
        11: 0x4000000000000000,
        12: 0xC000000000000000,
        13: 0xBFF0000000000000,
        14: 0x0000000000000000,
        15: 0x8000000000000000,
        16: 0x3FF0000000000000,
        17: 0x3FF0000000000000,
        18: 0x7FF8000000000000,
        19: 0x7FF8000000000000,
        24: 0x7FF0000000000000,
    }
    assert xregs == {20: 0, 21: 0b00001, 22: 0, 23: 0b10000}
