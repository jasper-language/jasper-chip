# tests/test_load_rb_program.py
# Step9 “实际测试效果”二：在修复 IMEM/DMEM 组合读时序后，
# 用一段极小程序驱动真实的 LW -> 读屏障(mv) -> 写回链路。
#
# 预期：
#   - 两条 lw 分别读取 dmem[0] 和 dmem[1]
#   - core 不直接写回 lw 原值，而是发起 MV_QUERY；mv 协处理器返回 rs1 原值
#   - mv 侧用 tag[1:0] 制造稳定乱序（tag=3 delay=3, tag=4 delay=0）
#   - core 必须按 tag 匹配，最终 x1/x2 正确

from amaranth import *
from amaranth.sim import Simulator, Tick

from rtl.rv12_core import RV12Core
from rtl.mem import SimpleIMem, SimpleDMem
from rtl.gc_mv_coproc import GCMvCoProc
from rtl.isa import enc_i, OP_IMM, LOAD


def nop():
    return enc_i(OP_IMM, 0, 0b000, 0, 0)


class TbProg(Elaboratable):
    def __init__(self):
        # Program: lw x1,0(x0); lw x2,4(x0); nops...
        prog = [
            enc_i(LOAD, 1, 0b010, 0, 0),
            enc_i(LOAD, 2, 0b010, 0, 4),
            nop(), nop(), nop(),
        ] + [nop()] * (64 - 5)

        dmem_init = [0] * 64
        dmem_init[0] = 0x11111111
        dmem_init[1] = 0x22222222

        self.core = RV12Core(core_id=0)
        self.imem = SimpleIMem(words=64, init=prog)
        self.dmem = SimpleDMem(words=64, init=dmem_init)
        self.mv   = GCMvCoProc(ncores=1)

    def elaborate(self, platform):
        m = Module()
        m.submodules.core = c = self.core
        m.submodules.imem = im = self.imem
        m.submodules.dmem = dm = self.dmem
        m.submodules.mv   = mv = self.mv

        # IMEM
        m.d.comb += [
            im.addr.eq(c.imem_addr),
            c.imem_rdata.eq(im.rdata),
        ]

        # DMEM
        m.d.comb += [
            dm.req_valid.eq(c.dmem_valid),
            dm.req_we.eq(c.dmem_we),
            dm.req_addr.eq(c.dmem_addr),
            dm.req_wdata.eq(c.dmem_wdata),
            c.dmem_rdata.eq(dm.rsp_rdata),
        ]

        # 禁用 sweep/scan（本测试只看 lw->mv）
        m.d.comb += [
            c.gc_enq_ready.eq(0),
            c.gc_rsp_valid.eq(0),
            c.gc_rsp_tag.eq(0),
            c.gc_rsp_rd.eq(0),
            c.gc_rsp_data.eq(0),
            c.wb_enq_ready.eq(1),
        ]

        # core <-> mv
        m.d.comb += [
            mv.cmd_enq_valid[0].eq(c.mv_cmd_valid),
            c.mv_cmd_ready.eq(mv.cmd_enq_ready[0]),
            mv.cmd_tag[0].eq(c.mv_cmd_tag),
            mv.cmd_op[0].eq(c.mv_cmd_op),
            mv.cmd_rd[0].eq(c.mv_cmd_rd),
            mv.cmd_rs1[0].eq(c.mv_cmd_rs1),
            mv.cmd_rs2[0].eq(c.mv_cmd_rs2),

            c.mv_rsp_valid.eq(mv.rsp_valid[0]),
            c.mv_rsp_tag.eq(mv.rsp_tag[0]),
            c.mv_rsp_rd.eq(mv.rsp_rd[0]),
            c.mv_rsp_data.eq(mv.rsp_data[0]),
            mv.rsp_take[0].eq(c.mv_rsp_take),
        ]

        return m


def main():
    dut = TbProg()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    c = dut.core

    def proc():
        # 运行一段时间，让两条 lw 走到 MEM2 并入队，再等待 mv 返回
        for _ in range(80):
            yield Tick()

        # 读取寄存器
        yield c.dbg_reg_addr.eq(1)
        yield Tick()
        x1 = (yield c.dbg_reg_rdata)
        yield c.dbg_reg_addr.eq(2)
        yield Tick()
        x2 = (yield c.dbg_reg_rdata)

        print(f"x1=0x{x1:08x} x2=0x{x2:08x}")
        assert x1 == 0x11111111, "lw/mv writeback mismatch for x1"
        assert x2 == 0x22222222, "lw/mv writeback mismatch for x2"
        print("OK: program-driven lw -> mv(read barrier) -> writeback works under out-of-order mv responses.")

    sim.add_sync_process(proc)
    sim.run()


if __name__ == "__main__":
    main()
