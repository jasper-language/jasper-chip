# tests/test_rb_inject_ooo.py
# Step9 的“实际测试效果”：验证 CPU 侧 read-barrier pending 表能在
# MV 协处理器“乱序返回”时，仍然按 tag 正确写回对应寄存器。
#
# 测试方法：
#   - 不依赖 IMEM/DMEM（因为这部分还在持续完善），直接使用 core.rb_inj_* 注入口。
#   - 连续注入两条 MV_QUERY：
#       tag=3 (delay=3) -> rd=1, value=0xAAAA0001
#       tag=4 (delay=0) -> rd=2, value=0xBBBB0002
#     MV 协处理器模型会稳定制造“第二条先返回”。
#   - 断言最终 x1/x2 的值正确。

from amaranth import *
from amaranth.sim import Simulator, Tick

from rtl.rv12_core import RV12Core
from rtl.gc_mv_coproc import GCMvCoProc, MV_QUERY


class Tb(Elaboratable):
    def __init__(self):
        self.core = RV12Core(core_id=0)
        self.mv   = GCMvCoProc(ncores=1)

    def elaborate(self, platform):
        m = Module()
        m.submodules.core = self.core
        m.submodules.mv   = self.mv

        c = self.core
        mv = self.mv

        # IMEM/DMEM：这里不测试指令/访存，只给常量 0
        m.d.comb += [
            c.imem_rdata.eq(0),
            c.dmem_rdata.eq(0),
        ]

        # 连接 core <-> mv（仅核0）
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
    dut = Tb()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    c = dut.core

    def proc():
        # 等待 몇 拍让系统稳定
        for _ in range(2):
            yield Tick()

        # 1) 注入 tag=3 (ctr reset=3) -> rd=1
        yield c.rb_inj_rd.eq(1)
        yield c.rb_inj_value.eq(0xAAAA0001)
        yield c.rb_inj_valid.eq(1)
        while (yield c.rb_inj_ready) == 0:
            yield Tick()
        yield Tick()
        yield c.rb_inj_valid.eq(0)

        # 2) 注入 tag=4 -> rd=2（将被 mv 侧更快返回，制造乱序）
        yield c.rb_inj_rd.eq(2)
        yield c.rb_inj_value.eq(0xBBBB0002)
        yield c.rb_inj_valid.eq(1)
        while (yield c.rb_inj_ready) == 0:
            yield Tick()
        yield Tick()
        yield c.rb_inj_valid.eq(0)

        # 等待响应全部回来并写回
        for _ in range(20):
            yield Tick()

        # 读取 x1/x2
        yield c.dbg_reg_addr.eq(1)
        yield Tick()
        x1 = (yield c.dbg_reg_rdata)

        yield c.dbg_reg_addr.eq(2)
        yield Tick()
        x2 = (yield c.dbg_reg_rdata)

        print(f"x1=0x{x1:08x} x2=0x{x2:08x}")
        assert x1 == 0xAAAA0001, "x1 mismatch"
        assert x2 == 0xBBBB0002, "x2 mismatch"
        print("OK: core read-barrier tag matching survives out-of-order mv responses.")

    sim.add_sync_process(proc)
    sim.run()


if __name__ == "__main__":
    main()
