from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick
import pytest

from rtl.isa import LUI, OP, OP_IMM, enc_i, enc_r, enc_u
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


def _nop():
    return enc_i(OP_IMM, 0, 0b000, 0, 0)


class _ZbkbBench(Elaboratable):
    def __init__(self, extensions):
        program = [
            enc_u(LUI, 1, 0x12345),
            enc_i(OP_IMM, 1, 0b000, 1, 0x678),
            enc_u(LUI, 2, 0xABCDF),
            enc_i(OP_IMM, 2, 0b000, 2, -0xFF),
            enc_r(OP, 3, 0b100, 1, 2, 0b0000100),  # PACK
            enc_r(OP, 4, 0b111, 1, 2, 0b0000100),  # PACKH
            enc_i(OP_IMM, 5, 0b101, 1, 0x687),  # BREV8
            enc_u(LUI, 1, 0x00010),
            enc_i(OP_IMM, 1, 0b000, 1, -1),
            enc_i(OP_IMM, 6, 0b001, 1, 0x08F),  # ZIP
            enc_i(OP_IMM, 7, 0b101, 6, 0x08F),  # UNZIP
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


def _run_zbkb(extensions):
    dut = _ZbkbBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    results = []

    def process():
        for _ in range(240):
            yield Tick()
        for register in range(3, 8):
            yield dut.core.dbg_reg_addr.eq(register)
            yield Tick()
            results.append((yield dut.core.dbg_reg_rdata))

    sim.add_process(process)
    sim.run()
    return tuple(results)


@pytest.mark.parametrize("extensions", ["RV32I+GC+ZBKB", "RV32I+GC+*"])
def test_rv32_zbkb_standard_pack_reverse_and_zip_family_executes(extensions):
    assert _run_zbkb(extensions) == (
        0xEF015678,
        0x00000178,
        0x482C6A1E,
        0x55555555,
        0x0000FFFF,
    )
