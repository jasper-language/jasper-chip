"""Complete RV32D Zfa integer-pair and floating-register move execution."""

import pytest
from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.isa import LOAD, OP_FP, OP_IMM, enc_i, enc_r
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


VALUES = (
    0x0123456789ABCDEF,
    0xFFF81234DEADBEEF,
    0x8000000000000000,
)


def nop():
    return enc_i(OP_IMM, 0, 0, 0, 0)


class _ZfaRv32dMoveBench(Elaboratable):
    def __init__(self, extensions):
        data = []
        for value in VALUES:
            data += [value & 0xFFFFFFFF, value >> 32]

        program = []
        for reg in range(1, 7):
            program += [enc_i(LOAD, reg, 0b010, 0, (reg - 1) * 4), *([nop()] * 4)]
        for index in range(3):
            program.append(enc_r(OP_FP, 10 + index, 0, 1 + 2 * index, 2 + 2 * index, 0b1011001))
        program += [nop()] * 4
        for index in range(3):
            program += [
                enc_r(OP_FP, 20 + index, 0, 10 + index, 1, 0b1110001),  # FMVH.X.D
                enc_r(OP_FP, 23 + index, 0, 10 + index, 0, 0b1110000),  # FMV.X.W
            ]
        program += [nop()] * (128 - len(program))

        self.core = RV12Core(core_id=0, xlen=32, rb_mode=1, extensions=extensions)
        self.imem = SimpleIMem(words=128, init=program)
        self.dmem = SimpleDMem(words=16, init=data + [0] * (16 - len(data)))

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
def test_zfa_rv32d_move_pair_preserves_all_64_bits(extensions):
    dut = _ZfaRv32dMoveBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    fprs = []
    xregs = {}

    def process():
        for _ in range(260):
            yield Tick()
        for reg in range(10, 13):
            yield dut.core.dbg_freg_addr.eq(reg)
            yield Tick()
            fprs.append((yield dut.core.dbg_freg_rdata))
        for reg in range(20, 26):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            xregs[reg] = yield dut.core.dbg_reg_rdata

    sim.add_process(process)
    sim.run()
    assert tuple(fprs) == VALUES
    assert tuple(xregs[20 + index] for index in range(3)) == tuple(value >> 32 for value in VALUES)
    assert tuple(xregs[23 + index] for index in range(3)) == tuple(value & 0xFFFFFFFF for value in VALUES)
