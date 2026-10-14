# tests/test_step74_cpu_mv_reloc.py
# Step74 "实际测试效果"：验证CPU可以直接向MV协处理器发起RELOC指令
#
# 测试场景：
#   1) CPU执行GC_MV_RELOC x1, x2（x1=old, x2=new）
#   2) MV协处理器更新forwarding table
#   3) 后续load读取old值时，read barrier应返回new值

from amaranth import *
from amaranth.sim import Simulator, Tick

from rtl.rv12_core import RV12Core
from rtl.mem import SimpleIMem, SimpleDMem
from rtl.gc_mv_coproc import GCMvCoProc
from rtl.isa import enc_i, enc_s, OP_IMM, LOAD, STORE, enc_gc_mv_reloc


def nop():
    return enc_i(OP_IMM, 0, 0b000, 0, 0)


class TbCpuMvReloc(Elaboratable):
    def __init__(self):
        # 程序：
        #   1) addi x1, x0, 100     => x1 = 100 (old handle)
        #   2) addi x2, x0, 200     => x2 = 200 (new handle)
        #   3) GC_MV_RELOC x1, x2   => 更新forwarding table: 100->200
        #   4) sw x1, 0(x0)         => 写入old handle 100
        #   5) lw x3, 0(x0)         => 读取100，但read barrier应返回200
        prog = [
            enc_i(OP_IMM, 1, 0b000, 0, 100),
            enc_i(OP_IMM, 2, 0b000, 0, 200),
            enc_gc_mv_reloc(rs1_old=1, rs2_new=2, rd=3),  # rd=3用于接收返回值
            nop(), nop(), nop(),
            enc_s(STORE, 0b010, 0, 1, 0),   # sw x1, 0(x0)
            enc_i(LOAD, 4, 0b010, 0, 0),    # lw x4, 0(x0)
            nop(), nop(), nop(), nop(),
        ] + [nop()] * (64 - 13)

        dmem_init = [0] * 64

        self.core = RV12Core(core_id=0, rb_mode=0)  # 所有load都触发RB
        self.imem = SimpleIMem(words=64, init=prog)
        self.dmem = SimpleDMem(words=64, init=dmem_init)
        self.mv = GCMvCoProc(ncores=1)

    def elaborate(self, platform):
        m = Module()
        m.submodules.core = c = self.core
        m.submodules.imem = im = self.imem
        m.submodules.dmem = dm = self.dmem
        m.submodules.mv = mv = self.mv

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
            c.gc_enq_ready.eq(0),
            c.gc_rsp_valid.eq(0),
            c.gc_rsp_tag.eq(0),
            c.gc_rsp_rd.eq(0),
            c.gc_rsp_data.eq(0),
            c.wb_enq_ready.eq(1),
        ]

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
    dut = TbCpuMvReloc()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    c = dut.core

    def proc():
        # 运行足够长时间让所有指令完成
        for _ in range(200):
            yield Tick()

        # 读取寄存器
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

        print(f"x1={x1} x2={x2} x3={x3} x4={x4}")

        # x1应该还是100（GC_MV_RELOC不修改x1）
        assert x1 == 100, f"x1 should be 100, got {x1}"
        # x2应该还是200
        assert x2 == 200, f"x2 should be 200, got {x2}"
        # x3是GC_MV_RELOC的返回值，应该是0（MV_RELOC返回0表示成功）
        # 或者根据MV协处理器的实现可能返回其他值
        print(f"GC_MV_RELOC return value (x3) = {x3}")
        # x4是load的结果，经过read barrier查询forwarding table后应返回200
        assert x4 == 200, f"x4 should be 200 (after MV_QUERY), got {x4}"

        print("OK: CPU GC_MV_RELOC directly updates MV forwarding table; load read barrier returns new handle.")

    sim.add_sync_process(proc)
    sim.run()


if __name__ == "__main__":
    main()
