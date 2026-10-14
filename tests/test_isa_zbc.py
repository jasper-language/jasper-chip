from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick
import pytest

from rtl.isa import OP, OP_IMM, enc_i, enc_r
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


def _nop():
    return enc_i(OP_IMM, 0, 0b000, 0, 0)


def _carryless_results(a, b, width=32):
    product = 0
    for bit in range(width):
        if (b >> bit) & 1:
            product ^= a << bit
    mask = (1 << width) - 1
    return (
        product & mask,
        (product >> width) & mask,
        (product >> (width - 1)) & mask,
    )


class _ZbcBench(Elaboratable):
    def __init__(self, extensions):
        program = [
            enc_i(OP_IMM, 1, 0b000, 0, 0x53),
            enc_i(OP_IMM, 2, 0b000, 0, 0xCA),
            enc_r(OP, 3, 0b001, 1, 2, 0b0000101),  # CLMUL
            enc_r(OP, 4, 0b011, 1, 2, 0b0000101),  # CLMULH
            enc_r(OP, 5, 0b010, 1, 2, 0b0000101),  # CLMULR
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


def _run_zbc(extensions):
    dut = _ZbcBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    results = []

    def process():
        for _ in range(180):
            yield Tick()
        for register in (3, 4, 5):
            yield dut.core.dbg_reg_addr.eq(register)
            yield Tick()
            results.append((yield dut.core.dbg_reg_rdata))

    sim.add_process(process)
    sim.run()
    return tuple(results)


@pytest.mark.parametrize("extensions", ["RV32I+GC+ZBC", "RV32I+GC+*"])
def test_zbc_standard_carryless_multiply_family_executes(extensions):
    assert _run_zbc(extensions) == _carryless_results(0x53, 0xCA)
