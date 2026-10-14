from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick
import pytest

from rtl.isa import LUI, OP, OP_IMM, enc_i, enc_r, enc_u
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


def _nop():
    return enc_i(OP_IMM, 0, 0b000, 0, 0)


class _ZbkxBench(Elaboratable):
    def __init__(self, extensions):
        program = [
            enc_u(LUI, 1, 0x44332),
            enc_i(OP_IMM, 1, 0b000, 1, 0x211),
            enc_u(LUI, 2, 0x00010),
            enc_i(OP_IMM, 2, 0b000, 2, 0x203),
            enc_r(OP, 3, 0b100, 1, 2, 0b0010100),  # XPERM8
            enc_u(LUI, 1, 0x76543),
            enc_i(OP_IMM, 1, 0b000, 1, 0x210),
            enc_u(LUI, 2, 0x01234),
            enc_i(OP_IMM, 2, 0b000, 2, 0x567),
            enc_r(OP, 4, 0b010, 1, 2, 0b0010100),  # XPERM4
        ]
        program += [_nop()] * (64 - len(program))
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=64, init=program)
        self.dmem = SimpleDMem(words=16)

    def elaborate(self, platform):
        m = Module()
        m.submodules.core = core = self.core
        m.submodules.imem = imem = self.imem
        m.submodules.dmem = dmem = self.dmem
        m.d.comb += [
            imem.addr.eq(core.imem_addr),
            core.imem_rdata.eq(imem.rdata),
            dmem.req_valid.eq(core.dmem_valid),
            dmem.req_we.eq(core.dmem_we),
            dmem.req_addr.eq(core.dmem_addr),
            dmem.req_wdata.eq(core.dmem_wdata),
            core.dmem_rdata.eq(dmem.rsp_rdata),
            core.gc_enq_ready.eq(0),
            core.gc_rsp_valid.eq(0),
            core.gc_rsp_tag.eq(0),
            core.gc_rsp_rd.eq(0),
            core.gc_rsp_data.eq(0),
            core.wb_enq_ready.eq(1),
            core.mv_cmd_ready.eq(1),
            core.mv_rsp_valid.eq(0),
            core.mv_rsp_tag.eq(0),
            core.mv_rsp_rd.eq(0),
            core.mv_rsp_data.eq(0),
        ]
        return m


def _run_zbkx(extensions):
    dut = _ZbkxBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    results = []

    def process():
        for _ in range(220):
            yield Tick()
        for register in (3, 4):
            yield dut.core.dbg_reg_addr.eq(register)
            yield Tick()
            results.append((yield dut.core.dbg_reg_rdata))

    sim.add_process(process)
    sim.run()
    return tuple(results)


@pytest.mark.parametrize("extensions", ["RV32I+GC+ZBKX", "RV32I+GC+*"])
def test_zbkx_standard_crossbar_permutations_execute(extensions):
    assert _run_zbkx(extensions) == (0x11223344, 0x01234567)
