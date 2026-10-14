# -*- coding: utf-8 -*-
"""Step12：验证 ‘GC 等待期间不应全局卡死’ + ‘GC 结果依赖必须被 scoreboard 阻塞’。

背景
- 早期版本的 core 用 gc_waiting 当作强屏障：GC 发出去后 can_fetch=0，整条流水停住。
  只要 GC 协处理器慢一点，CPU 就像“死机”一样无法执行任何无关指令。

Step12 改动
- core 不再用 gc_waiting 全局阻塞 fetch/execute。
- 只在两种情况下 stall（保证不丢 GC 指令、也不乱序执行 GC 指令）：
  1) GC 指令到达 IS 但协处理器 ready=0
  2) 前一条 GC 还在等待响应，又遇到下一条 GC
- 同时把 GC 写回纳入 pending_rd_mask scoreboard：依赖 GC 结果的后续指令会被 stall_dep 阻塞。

本测试思路
- 用 GCSweepCoProc(engine_latency=40) 人为制造“响应很慢”。
- 程序：
    0:  gc_new  x1
    4:  addi    x5,x0,7        (与 GC 无关，应在 GC 响应回来前就能写回)
    8:  addi    x2,x1,1        (依赖 GC 结果，必须等 x1 写回后再执行)
   12:  addi    x6,x0,9

断言
1) 运行 25 cycle：x5 已经=7，但 x1 仍为 0（GC 还没回），x2 也还没得到正确值。
   => 证明 ‘GC 等待期间 CPU 没被全局卡死’，至少能推进无关指令。
2) 运行到 120 cycle：x1 已经写回（alloc_ptr 初值=1），且 x2==x1+1。
   => 证明 scoreboard 对 GC 依赖是正确的（不会读到旧 x1）。

运行：
  python -m tests.test_gc_no_global_stall
"""

from __future__ import annotations

from amaranth import *
from amaranth.sim import Simulator, Tick

from rtl.rv12_core import RV12Core
from rtl.mem import SimpleIMem, SimpleDMem
from rtl.gc_sweep_coproc import GCSweepCoProc
from rtl.isa import enc_i, enc_gc_new, enc_jal, OP_IMM


def nop() -> int:
    return enc_i(OP_IMM, 0, 0b000, 0, 0)


class TbGcProg(Elaboratable):
    def __init__(self):
        prog = [
            enc_gc_new(1, 0, 0),
            enc_i(OP_IMM, 5, 0b000, 0, 7),
            enc_i(OP_IMM, 2, 0b000, 1, 1),
            enc_i(OP_IMM, 6, 0b000, 0, 9),
            enc_jal(0, 0),  # 死循环：避免 IMEM 地址溢出后绕回 0，导致程序重复执行影响观测
        ] + [nop()] * (64 - 5)

        self.core = RV12Core(core_id=0)
        self.imem = SimpleIMem(words=64, init=prog)
        self.dmem = SimpleDMem(words=64, init=[0] * 64)
        # 关键：把 GC 响应人为变慢，用来观察 core 是否还能推进无关指令
        self.sweep = GCSweepCoProc(ncores=1, engine_latency=40)

    def elaborate(self, platform):
        m = Module()
        m.submodules.core = c = self.core
        m.submodules.imem = im = self.imem
        m.submodules.dmem = dm = self.dmem
        m.submodules.sweep = sw = self.sweep

        # IMEM
        m.d.comb += [
            im.addr.eq(c.imem_addr),
            c.imem_rdata.eq(im.rdata),
        ]

        # DMEM（本程序不触发 load/store，但把接口接好避免悬空）
        m.d.comb += [
            dm.req_valid.eq(c.dmem_valid),
            dm.req_we.eq(c.dmem_we),
            dm.req_addr.eq(c.dmem_addr),
            dm.req_wdata.eq(c.dmem_wdata),
            c.dmem_rdata.eq(dm.rsp_rdata),
        ]

        # 禁用 mv/scan 写屏障：本测试只关心 sweep/GC 指令
        m.d.comb += [
            c.mv_cmd_ready.eq(1),
            c.mv_rsp_valid.eq(0),
            c.mv_rsp_tag.eq(0),
            c.mv_rsp_rd.eq(0),
            c.mv_rsp_data.eq(0),

            c.wb_enq_ready.eq(1),
        ]

        # core <-> sweep
        m.d.comb += [
            sw.cmd_enq_valid[0].eq(c.gc_enq_valid),
            sw.cmd_tag[0].eq(c.gc_tag),
            sw.cmd_op[0].eq(c.gc_op),
            sw.cmd_rd[0].eq(c.gc_rd),
            sw.cmd_rs1[0].eq(c.gc_rs1),
            sw.cmd_rs2[0].eq(c.gc_rs2),

            c.gc_enq_ready.eq(sw.cmd_enq_ready[0]),

            c.gc_rsp_valid.eq(sw.rsp_valid[0]),
            c.gc_rsp_tag.eq(sw.rsp_tag[0]),
            c.gc_rsp_rd.eq(sw.rsp_rd[0]),
            c.gc_rsp_data.eq(sw.rsp_data[0]),

            sw.rsp_take[0].eq(c.gc_rsp_take),
        ]

        return m


def main() -> None:
    dut = TbGcProg()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    c = dut.core

    def read_reg(idx: int):
        # dbg 读口是一拍延迟：先设 addr，再 Tick，再读 rdata
        yield c.dbg_reg_addr.eq(idx)
        yield Tick()
        return (yield c.dbg_reg_rdata)

    def proc():
        # 先跑 25 cycle：addi x5 应该已经写回，但 GC_NEW 的响应还没到
        for _ in range(25):
            yield Tick()

        x1 = (yield from read_reg(1))
        x2 = (yield from read_reg(2))
        x5 = (yield from read_reg(5))
        pm = (yield c.dbg_pending_rd_mask)
        gw = (yield c.dbg_gc_waiting)
        print(f"C25: x1=0x{x1:08x} x2=0x{x2:08x} x5=0x{x5:08x}")
        print(f"C25: pending_mask=0x{pm:08x} gc_waiting={gw}")

        assert x5 == 7, "x5 should have retired even while GC response is pending"
        assert x1 == 0, "x1 should still be 0 before delayed GC response arrives"
        assert x2 != 2, "x2 must not become correct before x1 writeback (scoreboard should block)"

        # 再跑到 120 cycle：GC 响应应已经写回，且依赖 addi 能得到正确结果
        for _ in range(120 - 25):
            yield Tick()

        x1 = (yield from read_reg(1))
        x2 = (yield from read_reg(2))
        x6 = (yield from read_reg(6))
        pm = (yield c.dbg_pending_rd_mask)
        gw = (yield c.dbg_gc_waiting)
        print(f"C120: x1=0x{x1:08x} x2=0x{x2:08x} x6=0x{x6:08x}")
        print(f"C120: pending_mask=0x{pm:08x} gc_waiting={gw}")

        assert x1 == 1, "GC_NEW should allocate handle=1 (alloc_ptr reset=1)"
        assert x2 == 2, "dependent addi must see GC result (x2=x1+1)"
        assert x6 == 9, "x6 should retire normally"

        print("OK: core keeps executing independent instructions while GC is pending, and scoreboard blocks dependent op until GC writeback.")

    sim.add_sync_process(proc)
    sim.run()


if __name__ == "__main__":
    main()
