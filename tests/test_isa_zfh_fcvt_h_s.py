"""Complete Zfhmin single-to-half narrowing conversion semantics."""

import pytest
from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.isa import LOAD_FP, OP_FP, OP_IMM, SYSTEM, enc_i, enc_r
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


CASES = (
    (0x3FC00000, 0b000, 0x3E00),  # exact 1.5
    (0x3F801000, 0b000, 0x3C00),  # RNE tie to even
    (0x3F801000, 0b100, 0x3C01),  # RMM tie away
    (0xBF801000, 0b010, 0xBC01),  # RDN negative
    (0x3F801000, 0b011, 0x3C01),  # RUP positive
    (0x3F801000, 0b111, 0x3C00),  # dynamic RTZ
    (0x38800000, 0b000, 0x0400),  # minimum half normal
    (0x33800000, 0b000, 0x0001),  # minimum half subnormal
    (0x33000000, 0b000, 0x0000),  # half-min-subnormal tie to zero
    (0x47800000, 0b000, 0x7C00),  # positive overflow to infinity
    (0xC7800000, 0b011, 0xFBFF),  # negative overflow under RUP
    (0x7FC01234, 0b000, 0x7E00),  # qNaN
    (0x7F800001, 0b000, 0x7E00),  # sNaN
    (0x7F800000, 0b000, 0x7C00),  # infinity
)


def nop():
    return enc_i(OP_IMM, 0, 0, 0, 0)


class _ZfhFcvtHSBench(Elaboratable):
    def __init__(self, extensions):
        data = [value for value, _, _ in CASES] + [0x3F800000, 0x00000000]
        program = [enc_i(SYSTEM, 0, 0b101, 1, 0x002)]  # frm=RTZ

        def emit(index, fd, flag_rd=0, double_load=False):
            program.extend([enc_i(SYSTEM, 0, 0b101, 0, 0x001), *([nop()] * 4)])
            program.extend([
                enc_i(LOAD_FP, 1, 0b011 if double_load else 0b010, 0, index * 4),
                *([nop()] * 4),
                enc_r(OP_FP, fd, CASES[index][1] if index < len(CASES) else 0, 1, 0, 0b0100010),
                *([nop()] * 4),
            ])
            if flag_rd:
                program.extend([enc_i(SYSTEM, flag_rd, 0b010, 0, 0x001), *([nop()] * 4)])

        for index in range(len(CASES)):
            flag_rd = {0: 25, 1: 26, 8: 27, 9: 28, 12: 29}.get(index, 0)
            emit(index, 10 + index, flag_rd)
        emit(len(CASES), 24, 30, double_load=True)  # invalid single NaN-box
        program += [nop()] * (384 - len(program))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=384, init=program)
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
def test_zfh_fcvt_h_s_rounding_flags_specials_and_nan_box(extensions):
    dut = _ZfhFcvtHSBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    fprs = {}
    flags = {}

    def process():
        for _ in range(900):
            yield Tick()
        for reg in range(10, 25):
            yield dut.core.dbg_freg_addr.eq(reg)
            yield Tick()
            fprs[reg] = yield dut.core.dbg_freg_rdata
        for reg in range(25, 31):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            flags[reg] = yield dut.core.dbg_reg_rdata

    sim.add_process(process)
    sim.run()
    expected = [0xFFFFFFFFFFFF0000 | value for _, _, value in CASES]
    expected.append(0xFFFFFFFFFFFF7E00)
    assert tuple(fprs[reg] for reg in range(10, 25)) == tuple(expected)
    assert flags == {
        25: 0,
        26: 0b00001,
        27: 0b00011,
        28: 0b00101,
        29: 0b10000,
        30: 0,
    }
