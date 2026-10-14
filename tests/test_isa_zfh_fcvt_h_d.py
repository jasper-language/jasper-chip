"""Complete Zfhmin double-to-half narrowing conversion semantics."""

import pytest
from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.isa import LOAD_FP, OP_FP, OP_IMM, SYSTEM, enc_i, enc_r
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


CASES = (
    (0x3FF8000000000000, 0b000, 0x3E00),
    (0x3FF0020000000000, 0b000, 0x3C00),
    (0x3FF0020000000000, 0b100, 0x3C01),
    (0xBFF0020000000000, 0b010, 0xBC01),
    (0x3FF0020000000000, 0b011, 0x3C01),
    (0x3FF0020000000000, 0b111, 0x3C00),
    (0x3F10000000000000, 0b000, 0x0400),
    (0x3E70000000000000, 0b000, 0x0001),
    (0x3E60000000000000, 0b000, 0x0000),
    (0x40F0000000000000, 0b000, 0x7C00),
    (0xC0F0000000000000, 0b011, 0xFBFF),
    (0x7FF8000000001234, 0b000, 0x7E00),
    (0x7FF0000000000001, 0b000, 0x7E00),
    (0x7FF0000000000000, 0b000, 0x7C00),
)


def nop():
    return enc_i(OP_IMM, 0, 0, 0, 0)


class _ZfhFcvtHDBench(Elaboratable):
    def __init__(self, extensions):
        data = []
        for value, _, _ in CASES:
            data += [value & 0xFFFFFFFF, value >> 32]
        program = [enc_i(SYSTEM, 0, 0b101, 1, 0x002)]

        def emit(index, fd, flag_rd=0):
            program.extend([enc_i(SYSTEM, 0, 0b101, 0, 0x001), *([nop()] * 4)])
            program.extend([
                enc_i(LOAD_FP, 1, 0b011, 0, index * 8),
                *([nop()] * 4),
                enc_r(OP_FP, fd, CASES[index][1], 1, 1, 0b0100010),
                *([nop()] * 4),
            ])
            if flag_rd:
                program.extend([enc_i(SYSTEM, flag_rd, 0b010, 0, 0x001), *([nop()] * 4)])

        for index in range(len(CASES)):
            emit(index, 10 + index, {0: 25, 1: 26, 8: 27, 9: 28, 12: 29}.get(index, 0))
        program += [nop()] * (384 - len(program))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=384, init=program)
        self.dmem = SimpleDMem(words=40, init=data + [0] * (40 - len(data)))

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
def test_zfh_fcvt_h_d_rounding_flags_subnormals_and_specials(extensions):
    dut = _ZfhFcvtHDBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    fprs = {}
    flags = {}

    def process():
        for _ in range(900):
            yield Tick()
        for reg in range(10, 24):
            yield dut.core.dbg_freg_addr.eq(reg)
            yield Tick()
            fprs[reg] = yield dut.core.dbg_freg_rdata
        for reg in range(25, 30):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            flags[reg] = yield dut.core.dbg_reg_rdata

    sim.add_process(process)
    sim.run()
    assert tuple(fprs[reg] for reg in range(10, 24)) == tuple(
        0xFFFFFFFFFFFF0000 | value for _, _, value in CASES
    )
    assert flags == {
        25: 0,
        26: 0b00001,
        27: 0b00011,
        28: 0b00101,
        29: 0b10000,
    }
