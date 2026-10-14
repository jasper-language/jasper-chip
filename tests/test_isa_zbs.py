from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick
import pytest

from rtl.isa import OP, OP_IMM, enc_i, enc_r
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


def _nop():
    return enc_i(OP_IMM, 0, 0b000, 0, 0)


class _ZbsBench(Elaboratable):
    def __init__(self, extensions):
        program = [
            enc_i(OP_IMM, 1, 0b000, 0, 0x5A),
            enc_i(OP_IMM, 2, 0b000, 0, 0),
            enc_r(OP, 3, 0b001, 1, 2, 0b0010100),  # BSET bit 0
            enc_i(OP_IMM, 2, 0b000, 0, 1),
            enc_r(OP, 4, 0b001, 1, 2, 0b0100100),  # BCLR bit 1
            enc_i(OP_IMM, 2, 0b000, 0, 2),
            enc_r(OP, 5, 0b001, 1, 2, 0b0110100),  # BINV bit 2
            enc_i(OP_IMM, 2, 0b000, 0, 3),
            enc_r(OP, 6, 0b101, 1, 2, 0b0100100),  # BEXT bit 3
            enc_i(OP_IMM, 7, 0b001, 1, (0b0010100 << 5) | 0),  # BSETI
            enc_i(OP_IMM, 8, 0b001, 1, (0b0100100 << 5) | 1),  # BCLRI
            enc_i(OP_IMM, 9, 0b001, 1, (0b0110100 << 5) | 2),  # BINVI
            enc_i(OP_IMM, 10, 0b101, 1, (0b0100100 << 5) | 3),  # BEXTI
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


def _run_zbs(extensions):
    dut = _ZbsBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    results = []

    def process():
        for _ in range(220):
            yield Tick()
        for register in range(3, 11):
            yield dut.core.dbg_reg_addr.eq(register)
            yield Tick()
            results.append((yield dut.core.dbg_reg_rdata))

    sim.add_process(process)
    sim.run()
    return tuple(results)


@pytest.mark.parametrize("extensions", ["RV32I+GC+ZBS", "RV32I+GC+*"])
def test_zbs_standard_single_bit_family_executes(extensions):
    assert _run_zbs(extensions) == (
        0x5B, 0x58, 0x5E, 1,
        0x5B, 0x58, 0x5E, 1,
    )
