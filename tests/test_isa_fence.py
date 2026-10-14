"""MISC-MEM FENCE smoke test for RV32I+GC and RV64I+GC."""

from amaranth import *
from amaranth.sim import Simulator, Tick

from rtl.rv12_core import RV12Core
from rtl.mem import SimpleIMem, SimpleDMem
from rtl.isa import OP_IMM, enc_fence, enc_i

def nop():
    return enc_i(OP_IMM, 0, 0b000, 0, 0)


def run_fence_case(xlen):
    prog = [
        enc_i(OP_IMM, 1, 0b000, 0, 1),
        enc_fence(),
        enc_i(OP_IMM, 2, 0b000, 0, 2),
        nop(),
    ]
    imem_words = 32
    prog = prog + [nop()] * (imem_words - len(prog))

    class _Bench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=xlen, extensions=f"RV{xlen}I+GC")
            self.imem = SimpleIMem(words=imem_words, init=prog)
            self.dmem = SimpleDMem(words=16)

        def elaborate(self, platform):
            m = Module()
            m.submodules.core = c = self.core
            m.submodules.imem = im = self.imem
            m.submodules.dmem = dm = self.dmem

            m.d.comb += [
                im.addr.eq(c.imem_addr),
                c.imem_rdata.eq(im.rdata),
                dm.req_valid.eq(c.dmem_valid),
                dm.req_we.eq(c.dmem_we),
                dm.req_addr.eq(c.dmem_addr),
                dm.req_wdata.eq(c.dmem_wdata),
                c.dmem_rdata.eq(dm.rsp_rdata),
                c.gc_enq_ready.eq(1),
                c.gc_rsp_valid.eq(0),
                c.gc_rsp_tag.eq(0),
                c.gc_rsp_rd.eq(0),
                c.gc_rsp_data.eq(0),
                c.wb_enq_ready.eq(1),
                c.mv_cmd_ready.eq(1),
                c.mv_rsp_valid.eq(0),
                c.mv_rsp_tag.eq(0),
                c.mv_rsp_rd.eq(0),
                c.mv_rsp_data.eq(0),
            ]
            return m

    dut = _Bench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core

    def proc():
        for _ in range(180):
            yield Tick()

        yield c.dbg_reg_addr.eq(1)
        yield Tick()
        v1 = yield c.dbg_reg_rdata
        yield c.dbg_reg_addr.eq(2)
        yield Tick()
        v2 = yield c.dbg_reg_rdata
        yield c.dbg_reg_addr.eq(0)
        yield Tick()
        x0 = yield c.dbg_reg_rdata

        assert v1 == 1
        assert v2 == 2
        assert x0 == 0
        assert (yield c.trap) == 0

    sim.add_process(proc)
    sim.run()


def test_fence_rv32():
    run_fence_case(32)


def test_fence_rv64():
    run_fence_case(64)
