"""IEEE and subset-boundary audit for the Zhinxmin conversion subset."""

import pytest
from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.isa import OP_FP, OP_IMM, SYSTEM, enc_i, enc_r
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core
from tests.test_isa_zhinxmin import li


EXTENSIONS = (
    "RV32I+GC+ZFINX+ZHINXMIN",
    "RV32I+GC+*+ZFINX+ZHINXMIN",
)


def nop():
    return enc_i(OP_IMM, 0, 0, 0, 0)


def fcvt_h_s(rd, rs1, rm):
    return enc_r(OP_FP, rd, rm, rs1, 0, 0b0100010)


def fcvt_s_h(rd, rs1, rm=0):
    return enc_r(OP_FP, rd, rm, rs1, 2, 0b0100000)


class _ZhinxminIEEEBench(Elaboratable):
    def __init__(self, extensions):
        program = []

        # All static modes and dynamic RUP for a positive halfway input.
        for rd, rm in zip(range(10, 15), (0, 1, 2, 3, 4)):
            program += li(1, 0x3F801000)
            program += [fcvt_h_s(rd, 1, rm), *([nop()] * 4)]
        program += [enc_i(SYSTEM, 0, 0b101, 3, 0x002), *([nop()] * 4)]
        program += li(1, 0x3F801000)
        program += [fcvt_h_s(15, 1, 7), *([nop()] * 4)]
        program += [enc_i(SYSTEM, 20, 0b010, 0, 0x001), *([nop()] * 4)]

        # Overflow and signaling NaN must report OF|NX and NV respectively.
        program += [enc_i(SYSTEM, 0, 0b101, 0, 0x001), *([nop()] * 4)]
        program += li(1, 0x7F7FFFFF)
        program += [fcvt_h_s(16, 1, 0), *([nop()] * 4)]
        program += [enc_i(SYSTEM, 21, 0b010, 0, 0x001), *([nop()] * 4)]
        program += [enc_i(SYSTEM, 0, 0b101, 0, 0x001), *([nop()] * 4)]
        program += li(1, 0x7F800001)
        program += [fcvt_h_s(17, 1, 0), *([nop()] * 4)]
        program += [enc_i(SYSTEM, 22, 0b010, 0, 0x001), *([nop()] * 4)]

        # Widening is exact; malformed H NaN-boxes become canonical qNaN.
        program += [enc_i(SYSTEM, 0, 0b101, 0, 0x001), *([nop()] * 4)]
        program += li(1, 0xFFFF3E00)
        program += [fcvt_s_h(23, 1), *([nop()] * 4)]
        program += li(1, 0x00003E00)
        program += [fcvt_s_h(24, 1), *([nop()] * 4)]
        program += li(1, 0xFFFF7C01)
        program += [fcvt_s_h(25, 1), *([nop()] * 4)]
        program += [enc_i(SYSTEM, 26, 0b010, 0, 0x001), *([nop()] * 4)]

        # Zhinxmin must reject full Zhinx arithmetic and illegal rounding modes.
        program += li(27, 0x13579BDF)
        program += [enc_r(OP_FP, 27, 0, 1, 1, 0b0000010), *([nop()] * 4)]  # FADD.H
        program += li(28, 0x2468ACE0)
        program += [fcvt_h_s(28, 1, 5), *([nop()] * 4)]
        program += [enc_i(SYSTEM, 0, 0b101, 5, 0x002), *([nop()] * 4)]
        program += li(29, 0x55AA55AA)
        program += [fcvt_h_s(29, 1, 7), *([nop()] * 4)]

        program += [nop()] * (320 - len(program))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=320, init=program)
        self.dmem = SimpleDMem(words=4, init=[0] * 4)

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


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_zhinxmin_ieee_rounding_nan_box_flags_and_subset_boundary(extensions):
    dut = _ZhinxminIEEEBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    regs = {}

    def process():
        for _ in range(800):
            yield Tick()
        for reg in range(10, 30):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            regs[reg] = yield dut.core.dbg_reg_rdata

    sim.add_process(process)
    sim.run()

    assert tuple(regs[reg] for reg in range(10, 16)) == (
        0xFFFF3C00, 0xFFFF3C00, 0xFFFF3C00,
        0xFFFF3C01, 0xFFFF3C01, 0xFFFF3C01,
    )
    assert regs[16] == 0xFFFF7C00
    assert regs[21] == 0b00101
    assert regs[17] == 0xFFFF7E00
    assert regs[22] == 0b10000
    assert regs[23] == 0x3FC00000
    assert regs[24] == 0x7FC00000
    assert regs[25] == 0x7FC00000
    assert regs[26] == 0b10000
    assert regs[27] == (0xFFFF7E00 if "+*" in extensions else 0x13579BDF)
    assert regs[28] == 0x2468ACE0
    assert regs[29] == 0x55AA55AA
