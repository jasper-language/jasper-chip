"""Complete RV32 Zfa modular double-to-word conversion execution semantics."""

import pytest
from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.isa import LOAD_FP, OP_FP, OP_IMM, SYSTEM, enc_i, enc_r
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


def nop():
    return enc_i(OP_IMM, 0, 0, 0, 0)


CASES = (
    (0x4017000000000000, 0x00000005, 0b00001),  # 5.75 -> 5, NX
    (0xC017000000000000, 0xFFFFFFFB, 0b00001),  # -5.75 -> -5, NX
    (0x41F0000000100000, 0x00000001, 0b10000),  # 2^32 + 1 -> 1, NV
    (0xC1F0000000100000, 0xFFFFFFFF, 0b10000),  # -2^32 - 1 -> -1, NV
    (0x41DFFFFFFFC00000, 0x7FFFFFFF, 0),         # INT_MAX
    (0xC1E0000000000000, 0x80000000, 0),         # INT_MIN
    (0x7FF8000000001234, 0x00000000, 0b10000),  # qNaN -> 0, NV
    (0x7FF0000000000000, 0x00000000, 0b10000),  # +infinity -> 0, NV
    (0x3FE0000000000000, 0x00000000, 0b00001),  # 0.5 -> 0, NX
)


class _ZfaFcvtmodBench(Elaboratable):
    def __init__(self, extensions):
        data = []
        for value, _, _ in CASES:
            data += [value & 0xFFFFFFFF, value >> 32]
        program = []
        for index in range(len(CASES)):
            program.extend([enc_i(SYSTEM, 0, 0b101, 0, 0x001), *([nop()] * 4)])
            program.extend([enc_i(LOAD_FP, 1, 0b011, 0, index * 8), *([nop()] * 4)])
            program.extend([
                enc_r(OP_FP, 10 + index, 0b001, 1, 8, 0b1100001),
                *([nop()] * 4),
                enc_i(SYSTEM, 20 + index, 0b010, 0, 0x001),
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


@pytest.mark.parametrize("extensions", ["RV32I+GC+ZFA", "RV32I+GC+*"])
def test_zfa_fcvtmod_w_d_modular_results_and_standard_flags(extensions):
    dut = _ZfaFcvtmodBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    results = []
    flags = []

    def process():
        for _ in range(700):
            yield Tick()
        for reg in range(10, 10 + len(CASES)):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            results.append((yield dut.core.dbg_reg_rdata))
        for reg in range(20, 20 + len(CASES)):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            flags.append((yield dut.core.dbg_reg_rdata))

    sim.add_process(process)
    sim.run()
    assert tuple(results) == tuple(case[1] for case in CASES)
    assert tuple(flags) == tuple(case[2] for case in CASES)
