"""Complete RV32 Zfa floating-point load-immediate execution matrix."""

import pytest
from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.isa import OP_FP, OP_IMM, enc_i, enc_r
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


FLI_S = (
    0xBF800000, 0x00800000, 0x37800000, 0x38000000,
    0x3B800000, 0x3C000000, 0x3D800000, 0x3E000000,
    0x3E800000, 0x3EA00000, 0x3EC00000, 0x3EE00000,
    0x3F000000, 0x3F200000, 0x3F400000, 0x3F600000,
    0x3F800000, 0x3FA00000, 0x3FC00000, 0x3FE00000,
    0x40000000, 0x40200000, 0x40400000, 0x40800000,
    0x41000000, 0x41800000, 0x43000000, 0x43800000,
    0x47000000, 0x47800000, 0x7F800000, 0x7FC00000,
)

FLI_D = (
    0xBFF0000000000000, 0x0010000000000000,
    0x3EF0000000000000, 0x3F00000000000000,
    0x3F70000000000000, 0x3F80000000000000,
    0x3FB0000000000000, 0x3FC0000000000000,
    0x3FD0000000000000, 0x3FD4000000000000,
    0x3FD8000000000000, 0x3FDC000000000000,
    0x3FE0000000000000, 0x3FE4000000000000,
    0x3FE8000000000000, 0x3FEC000000000000,
    0x3FF0000000000000, 0x3FF4000000000000,
    0x3FF8000000000000, 0x3FFC000000000000,
    0x4000000000000000, 0x4004000000000000,
    0x4008000000000000, 0x4010000000000000,
    0x4020000000000000, 0x4030000000000000,
    0x4060000000000000, 0x4070000000000000,
    0x40E0000000000000, 0x40F0000000000000,
    0x7FF0000000000000, 0x7FF8000000000000,
)


def nop():
    return enc_i(OP_IMM, 0, 0, 0, 0)


class _ZfaFliBench(Elaboratable):
    def __init__(self, extensions, funct7):
        program = [enc_r(OP_FP, index, 0, index, 1, funct7) for index in range(32)]
        program += [nop()] * (128 - len(program))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=128, init=program)
        self.dmem = SimpleDMem(words=16)

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
@pytest.mark.parametrize("funct7,expected", [
    (0b1111000, tuple(0xFFFFFFFF00000000 | value for value in FLI_S)),
    (0b1111001, FLI_D),
])
def test_zfa_fli_s_and_d_execute_all_32_standard_constants(extensions, funct7, expected):
    dut = _ZfaFliBench(extensions, funct7)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    observed = []

    def process():
        for _ in range(220):
            yield Tick()
        for index in range(32):
            yield dut.core.dbg_freg_addr.eq(index)
            yield Tick()
            observed.append((yield dut.core.dbg_freg_rdata))

    sim.add_process(process)
    sim.run()
    assert tuple(observed) == expected
