# tests/test_step78_multi_gc.py
# Step78：多发 GC 请求——支持 2 条 GC 指令同时在飞。

from amaranth import *
from amaranth.sim import Simulator, Tick

from rtl.rv12_core import RV12Core
from rtl.mem import SimpleIMem, SimpleDMem
from rtl.gc_sweep_coproc import GCSweepCoProc
from rtl.isa import enc_i, enc_gc_new, OP_IMM


def nop():
    return enc_i(OP_IMM, 0, 0b000, 0, 0)


class TbMultiGc(Elaboratable):
    def __init__(self):
        prog = [
            enc_gc_new(rd=1),
            enc_gc_new(rd=2),
            nop(), nop(), nop(), nop(), nop(), nop(),
            enc_i(OP_IMM, 3, 0b000, 1, 0),      # x3 = x1 + 0
            enc_i(OP_IMM, 4, 0b000, 2, 0),      # x4 = x2 + 0
        ] + [nop()] * (120 - 12)

        dmem_init = [0] * 8

        self.core = RV12Core(core_id=0, rb_mode=0)
        self.imem = SimpleIMem(words=120, init=prog)
        self.dmem = SimpleDMem(words=8, init=dmem_init)
        self.sweep = GCSweepCoProc(ncores=1, engine_latency=5)

    def elaborate(self, platform):
        m = Module()
        m.submodules.core = c = self.core
        m.submodules.imem = im = self.imem
        m.submodules.dmem = dm = self.dmem
        m.submodules.sweep = sw = self.sweep

        m.d.comb += [
            im.addr.eq(c.imem_addr),
            c.imem_rdata.eq(im.rdata),
        ]

        m.d.comb += [
            dm.req_valid.eq(c.dmem_valid),
            dm.req_we.eq(c.dmem_we),
            dm.req_addr.eq(c.dmem_addr),
            dm.req_wdata.eq(c.dmem_wdata),
            c.dmem_rdata.eq(dm.rsp_rdata),
        ]

        m.d.comb += [
            sw.cmd_enq_valid[0].eq(c.gc_enq_valid),
            c.gc_enq_ready.eq(sw.cmd_enq_ready[0]),
            sw.cmd_tag[0].eq(c.gc_tag),
            sw.cmd_op[0].eq(c.gc_op),
            sw.cmd_rd[0].eq(c.gc_rd),
            sw.cmd_rs1[0].eq(c.gc_rs1),
            sw.cmd_rs2[0].eq(c.gc_rs2),

            c.gc_rsp_valid.eq(sw.rsp_valid[0]),
            c.gc_rsp_tag.eq(sw.rsp_tag[0]),
            c.gc_rsp_rd.eq(sw.rsp_rd[0]),
            c.gc_rsp_data.eq(sw.rsp_data[0]),
            sw.rsp_take[0].eq(c.gc_rsp_take),

            c.wb_enq_ready.eq(1),
        ]

        return m


def main():
    dut = TbMultiGc()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    c = dut.core

    def proc():
        for cyc in range(100):
            yield Tick()

        for rd in range(1, 5):
            yield c.dbg_reg_addr.eq(rd)
            yield Tick()
            v = (yield c.dbg_reg_rdata)
            print(f"  x{rd}={v}")

        yield c.dbg_reg_addr.eq(1)
        yield Tick()
        x1 = (yield c.dbg_reg_rdata)
        yield c.dbg_reg_addr.eq(2)
        yield Tick()
        x2 = (yield c.dbg_reg_rdata)
        yield c.dbg_reg_addr.eq(3)
        yield Tick()
        x3 = (yield c.dbg_reg_rdata)
        yield c.dbg_reg_addr.eq(4)
        yield Tick()
        x4 = (yield c.dbg_reg_rdata)

        assert x1 == 1, f"x1 (GC_NEW #1) should be 1, got {x1}"
        assert x2 == 2, f"x2 (GC_NEW #2) should be 2, got {x2}"
        assert x3 == 1, f"x3 (dep on x1) should be 1, got {x3}"
        assert x4 == 2, f"x4 (dep on x2) should be 2, got {x4}"

        print("OK: back-to-back GC_NEW both complete correctly.")

    sim.add_sync_process(proc)
    sim.run()


if __name__ == "__main__":
    main()
