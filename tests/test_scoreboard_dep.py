# tests/test_scoreboard_dep.py
# Step11 “实际测试效果”：验证 scoreboard（pending_rd_mask）真的能挡住依赖指令。
#
# 程序：
#   lw   x1,0(x0)      ; load 返回值不直接写回，而是走 mv(读屏障)
#   addi x3,x1,1       ; 依赖 x1 的新值，必须等待 mv 响应写回后才能执行
#
# 如果没有 scoreboard：
#   addi 往往会在 x1 还没写回前执行，读到旧值 0 -> x3=1（错误）
#
# 本测试要求：
#   x1 = 0x11111111
#   x3 = 0x11111112

from amaranth import *
from amaranth.sim import Simulator, Tick

from rtl.rv12_core import RV12Core
from rtl.mem import SimpleIMem, SimpleDMem
from rtl.gc_mv_coproc import GCMvCoProc
from rtl.isa import enc_i, OP_IMM, LOAD


def nop():
    return enc_i(OP_IMM, 0, 0b000, 0, 0)


class TbDep(Elaboratable):
    def __init__(self):
        # lw x1,0(x0); addi x3,x1,1; nops...
        prog = [
            enc_i(LOAD, 1, 0b010, 0, 0),
            enc_i(OP_IMM, 3, 0b000, 1, 1),
            nop(), nop(), nop(),
        ] + [nop()] * (64 - 6)

        dmem_init = [0] * 64
        dmem_init[0] = 0x11111111

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

        # 禁用 sweep/scan（本测试只看 lw->mv + scoreboard）
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
    dut = TbDep()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    c = dut.core

    def proc():
        # 让 lw 走到 MEM2 发 mv query，再等待 mv 写回，同时让 addi 有机会触发依赖停顿。
        for _ in range(120):
            yield Tick()

        # 读取寄存器
        yield c.dbg_reg_addr.eq(1)
        yield Tick()
        x1 = (yield c.dbg_reg_rdata)

        yield c.dbg_reg_addr.eq(3)
        yield Tick()
        x3 = (yield c.dbg_reg_rdata)

        print(f"x1=0x{x1:08x} x3=0x{x3:08x}")
        assert x1 == 0x11111111, "lw/mv writeback mismatch for x1"
        assert x3 == 0x11111112, "scoreboard failed: dependent addi observed old x1"
        print("OK: scoreboard blocks dependent instruction until mv writeback completes.")

    sim.add_sync_process(proc)
    sim.run()


if __name__ == "__main__":
    main()
